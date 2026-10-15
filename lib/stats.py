"""集計・検定ロジック

DB や Streamlit に依存しない純粋な関数だけを置く（単体テストしやすくするため）。
すべて決定的処理：同じデータと同じ設定からは必ず同じ結果になる。
ランダムな処理（代表者のランダム抽出、R×C表のフィッシャー検定）は乱数シードを固定する。
"""
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy import stats

JST = timezone(timedelta(hours=9))

# フィッシャー検定（R×C表）のモンテカルロ法で使う固定シードと反復回数
FISHER_SEED = 20261015
FISHER_RESAMPLES = 20000
# 期待度数がこの値未満のセルが1つでもあればフィッシャーの正確確率検定に切り替える
MIN_EXPECTED = 5

OTHER_LABEL = "その他"

SCOPES = {
    "all": "全回答者",
    "solo": "一人客のみ",
    "rep_first": "グループ代表1人（メンバー番号1）",
    "rep_random": "グループ代表1人（ランダム抽出）",
}


# ============================================================
# データ整形
# ============================================================

def build_respondents(groups, responses, answers, questions):
    """
    DBの行（EAV形式）を「1行1回答者」の横持ち DataFrame にする。

    単一選択・自由記述の列には文字列、複数選択の列には list が入る（未回答は NaN）。
    「その他」の記述は "<設問ID>_other" 列に入る。
    """
    gdf = pd.DataFrame(groups)
    rdf = pd.DataFrame(responses)
    if gdf.empty or rdf.empty:
        return pd.DataFrame(columns=["response_id", "group_id", "member_number",
                                     "group_size", "survey_type", "location"])

    gcols = ["id", "created_at", "location", "survey_type", "input_method", "group_size"]
    gdf = gdf[[c for c in gcols if c in gdf.columns]].rename(columns={"id": "group_id"})
    rdf = rdf.rename(columns={"id": "response_id"})
    for col, default in [("conformity_flag", False), ("branch", None), ("response_mode", None)]:
        if col not in rdf.columns:
            rdf[col] = default
    df = rdf.merge(gdf, on="group_id", how="inner")

    # 回答値を {response_id: {question_id: 値}} にまとめる
    multi = {qid for qid, q in questions.items() if q["type"] == "multi_choice"}
    vals = {}
    for a in answers:
        qid = a["question_id"]
        if qid in multi:
            v = list(a.get("values") or [])
        else:
            v = a.get("value")
        vals.setdefault(a["response_id"], {})[qid] = v

    qcols = list(questions) + [f"{qid}_other" for qid, q in questions.items() if q.get("has_other")]
    wide = pd.DataFrame.from_dict(vals, orient="index").reindex(columns=qcols)
    wide.index.name = "response_id"
    df = df.merge(wide, left_on="response_id", right_index=True, how="left")
    df["conformity_flag"] = df["conformity_flag"].fillna(False).astype(bool)
    return df.sort_values(["created_at", "group_id", "member_number"]).reset_index(drop=True)


def resident_conditions(questions):
    """YAMLで tag: resident が付いた選択肢を [(設問ID, value)] で返す"""
    return [(qid, o["value"]) for qid, q in questions.items()
            for o in q.get("options", []) if o.get("tag") == "resident"]


@dataclass
class FilterResult:
    df: pd.DataFrame
    notes: list = field(default_factory=list)   # 何人除外したか等の説明


def filter_respondents(df, questions, survey_types=("main",), exclude_residents=False,
                       scope="all", seed=0, exclude_conformity=False):
    """
    絞り込み条件を適用する。適用順: 調査区分 → 住民除外 → 同調フラグ除外 → 回答者の範囲。

    scope:
      all        全回答者
      solo       一人客のみ（group_size == 1）
      rep_first  各グループから1人（残っている中で最小のメンバー番号。通常はメンバー1）
      rep_random 各グループから1人をランダム抽出（seed 固定。グループIDの順に抽出するので再現可能）
    """
    notes = []
    out = df[df["survey_type"].isin(survey_types)] if len(df) else df

    if exclude_residents and len(out):
        mask = pd.Series(False, index=out.index)
        for qid, val in resident_conditions(questions):
            if qid in out.columns:
                mask |= out[qid] == val
        if mask.any():
            notes.append(f"住民（鎌倉市内在住）{int(mask.sum())}人を除外")
        out = out[~mask]

    if exclude_conformity and len(out):
        n = int(out["conformity_flag"].sum())
        if n:
            notes.append(f"同調フラグあり {n}人を除外")
        out = out[~out["conformity_flag"]]

    if scope == "solo":
        out = out[out["group_size"] == 1]
    elif scope == "rep_first":
        out = (out.sort_values(["group_id", "member_number"])
               .groupby("group_id", sort=True).head(1))
    elif scope == "rep_random":
        rng = np.random.default_rng(seed)
        picks = []
        for _, g in out.sort_values(["group_id", "member_number"]).groupby("group_id", sort=True):
            picks.append(g.index[rng.integers(len(g))])
        out = out.loc[picks]
        notes.append(f"ランダム抽出の乱数シード: {seed}")
    elif scope != "all":
        raise ValueError(f"unknown scope: {scope}")

    return FilterResult(out.sort_values(["created_at", "group_id", "member_number"])
                        if len(out) else out, notes)


def includes_group_members(df):
    """同じグループの回答者が2人以上含まれているか（＝回答の独立性が完全ではない）"""
    return bool(len(df)) and bool(df["group_id"].duplicated().any())


# ============================================================
# 単純集計
# ============================================================

def _option_labels(q):
    labels = [(o["value"], o["label"]) for o in q.get("options", [])]
    if q.get("has_other"):
        labels.append(("other", OTHER_LABEL))
    return labels


def tally(df, qid, q):
    """
    1設問の度数・割合。(表, 回答者数n) を返す。
    単一選択: 割合 = 度数 / n。複数選択: 割合 = 選んだ人数 / n（合計は100%を超える）。
    選択肢の並びはYAMLの順。度数0の選択肢も残す。
    """
    if qid not in df.columns:
        return pd.DataFrame(columns=["選択肢", "度数", "割合(%)"]), 0
    col = df[qid]
    if q["type"] == "multi_choice":
        answered = col[col.apply(lambda v: isinstance(v, list) and len(v) > 0)]
        n = len(answered)
        counts = {}
        for vs in answered:
            for v in vs:
                counts[v] = counts.get(v, 0) + 1
    else:
        answered = col.dropna()
        n = len(answered)
        counts = answered.value_counts().to_dict()

    rows = [(label, int(counts.pop(v, 0))) for v, label in _option_labels(q)]
    # YAMLから消えた選択肢の回答も落とさず表示する
    rows += [(str(v), int(c)) for v, c in sorted(counts.items(), key=lambda x: str(x[0]))]
    t = pd.DataFrame(rows, columns=["選択肢", "度数"])
    t["割合(%)"] = (t["度数"] / n * 100).round(1) if n else 0.0
    return t, n


def group_size_distribution(df):
    """グループ人数の分布（グループ単位で数える）"""
    if not len(df):
        return pd.DataFrame(columns=["グループ人数", "グループ数", "回答者数"])
    g = df.drop_duplicates("group_id")
    t = g["group_size"].value_counts().sort_index()
    resp = df["group_size"].value_counts().sort_index()
    out = pd.DataFrame({"グループ人数": [f"{s}人" for s in t.index],
                        "グループ数": t.values,
                        "回答者数": [int(resp.get(s, 0)) for s in t.index]})
    return out


def branch_distribution(df):
    labels = {"A": "分岐A（利用経験あり）", "B": "分岐B（知っていたが未利用）"}
    n = len(df)
    vc = df["branch"].fillna("none").value_counts() if n else pd.Series(dtype=int)
    rows = [(labels["A"], int(vc.get("A", 0))), (labels["B"], int(vc.get("B", 0))),
            ("分岐なし（未認知・未利用）", int(vc.get("none", 0)))]
    t = pd.DataFrame(rows, columns=["分岐", "人数"])
    t["割合(%)"] = (t["人数"] / n * 100).round(1) if n else 0.0
    return t


# ============================================================
# クロス集計・検定
# ============================================================

def crosstab(df, row_qid, row_q, col_qid, col_q):
    """
    単一選択どうしのクロス集計表（度数）。行・列はYAMLの選択肢順、ラベル表示。
    両方に回答している人だけを数える。合計0の行・列は落とす。
    """
    if row_qid not in df.columns or col_qid not in df.columns:
        return pd.DataFrame()
    sub = df[[row_qid, col_qid]].dropna()
    rlab = dict(_option_labels(row_q))
    clab = dict(_option_labels(col_q))
    t = pd.crosstab(sub[row_qid], sub[col_qid])
    rows = [v for v in rlab if v in t.index] + [v for v in t.index if v not in rlab]
    cols = [v for v in clab if v in t.columns] + [v for v in t.columns if v not in clab]
    t = t.reindex(index=rows, columns=cols, fill_value=0)
    t.index = [rlab.get(v, v) for v in t.index]
    t.columns = [clab.get(v, v) for v in t.columns]
    t.index.name = row_q.get("text", row_qid)
    t.columns.name = col_q.get("text", col_qid)
    return t


def row_percent(table):
    """行ごとの割合(%)"""
    s = table.sum(axis=1).replace(0, np.nan)
    return (table.div(s, axis=0) * 100).round(1).fillna(0.0)


@dataclass(frozen=True)  # キャッシュして使い回すので変更不可にする
class TestResult:
    method: str              # 使った検定の名前
    p_value: float | None
    statistic: float | None = None
    dof: int | None = None
    cramers_v: float | None = None
    min_expected: float | None = None
    n: int = 0
    note: str = ""           # 切替理由など

    def summary(self):
        if self.p_value is None:
            return f"検定不可（{self.note}）"
        stars = "**" if self.p_value < 0.01 else "*" if self.p_value < 0.05 else "n.s."
        parts = [self.method]
        if self.statistic is not None and self.method.startswith("カイ二乗"):
            parts.append(f"χ²({self.dof}) = {self.statistic:.2f}")
        parts.append(f"p = {format_p(self.p_value)} {stars}")
        if self.cramers_v is not None:
            parts.append(f"V = {self.cramers_v:.2f}")
        return ", ".join(parts)


def format_p(p):
    return "< .001" if p < 0.001 else f"{p:.3f}"


def independence_test(table):
    """
    クロス集計表の独立性の検定。
    期待度数が MIN_EXPECTED 未満のセルが1つでもあれば、フィッシャーの正確確率検定に自動で切り替える。
      2×2  : scipy の正確検定
      R×C  : Fisher-Freeman-Halton 検定（モンテカルロ法、乱数シード固定で再現可能）
    カイ二乗検定は 2×2 のときイェーツの連続修正あり（scipy の既定）。
    """
    t = table.loc[table.sum(axis=1) > 0, table.sum(axis=0) > 0] if table.size else table
    n = int(t.values.sum()) if t.size else 0
    if t.shape[0] < 2 or t.shape[1] < 2:
        return TestResult("—", None, n=n, note="回答が1つの区分に集中しているため")
    # 同じ表の検定は結果も同じなので使い回す（感度分析で同じ表を何度も検定するため）
    return _test_counts(tuple(map(tuple, t.values.astype(int).tolist())))


@lru_cache(maxsize=512)
def _test_counts(counts):
    obs = np.array(counts)
    n = int(obs.sum())
    chi = stats.chi2_contingency(obs)
    expected = chi.expected_freq
    min_exp = float(expected.min())
    k = min(obs.shape) - 1
    # クラメールのV（効果量）は補正なしのカイ二乗値から計算する
    chi_raw = stats.chi2_contingency(obs, correction=False).statistic
    v = float(np.sqrt(chi_raw / (n * k))) if n and k else None

    if min_exp >= MIN_EXPECTED:
        method = "カイ二乗検定" + ("（イェーツの補正あり）" if obs.shape == (2, 2) else "")
        return TestResult(method, float(chi.pvalue), float(chi.statistic), int(chi.dof),
                          v, min_exp, n)

    note = f"期待度数{MIN_EXPECTED}未満のセルがあるためフィッシャーの正確確率検定に切替（最小期待度数 {min_exp:.2f}）"
    if obs.shape == (2, 2):
        res = stats.fisher_exact(obs)
        return TestResult("フィッシャーの正確確率検定", float(res.pvalue), None, None,
                          v, min_exp, n, note)
    res = stats.fisher_exact(obs, method=stats.MonteCarloMethod(
        n_resamples=FISHER_RESAMPLES, rng=np.random.default_rng(FISHER_SEED)))
    return TestResult("フィッシャーの正確確率検定（R×C, モンテカルロ法）",
                      float(res.pvalue), None, None, v, min_exp, n,
                      note + f"／モンテカルロ法 {FISHER_RESAMPLES}回・シード{FISHER_SEED}")


# ============================================================
# 想起の比較
# ============================================================

def awareness_summary(df, unaided_qid, aided_qid):
    """純粋想起（名前を出さずに）と助成想起（ロゴ提示）の認知率を並べる"""
    rows = []
    if unaided_qid in df.columns:
        u = df[unaided_qid].dropna()
        n = len(u)
        name = int((u == "can_name").sum())
        heard = int((u == "heard").sum())
        rows.append(("純粋想起：名前を言える", name, n))
        rows.append(("純粋想起：名前を言える＋聞いたことはある", name + heard, n))
    if aided_qid in df.columns:
        a = df[aided_qid].dropna()
        rows.append(("助成想起：見たことがある", int((a == "yes").sum()), len(a)))
    t = pd.DataFrame(rows, columns=["指標", "人数", "n"])
    t["割合(%)"] = [round(c / n * 100, 1) if n else 0.0 for c, n in zip(t["人数"], t["n"])]
    return t


# ============================================================
# 自由記述の分類結果
# ============================================================

def classification_summary(df, answers, classifications, qid, codebook):
    """
    自由記述1設問について、分類カテゴリごとの件数を数える。
    分類者が複数いる場合は classifier_1 の結果を使う（κ係数は Phase 5）。
    """
    resp_ids = set(df["response_id"]) if len(df) else set()
    texts = {a["id"] for a in answers
             if a["question_id"] == qid and a["response_id"] in resp_ids
             and (a.get("value") or "").strip()}
    cls = {}
    for c in classifications:
        if c["answer_id"] in texts and c.get("classifier_id", "classifier_1") == "classifier_1":
            cls[c["answer_id"]] = c
    counts = {}
    status = {"classified": 0, "pending": 0, "new_category": 0}
    for c in cls.values():
        status[c.get("status", "classified")] = status.get(c.get("status", "classified"), 0) + 1
        if c.get("status", "classified") == "classified":
            for code in c.get("categories") or []:
                counts[code] = counts.get(code, 0) + 1
    n_cls = status["classified"]
    rows = [(cat["label"], counts.pop(cat["code"], 0)) for cat in codebook.get("categories", [])]
    rows += [(code, c) for code, c in sorted(counts.items())]
    t = pd.DataFrame(rows, columns=["カテゴリ", "件数"])
    t["割合(%)"] = (t["件数"] / n_cls * 100).round(1) if n_cls else 0.0
    return t, dict(記述あり=len(texts), 分類済み=n_cls, 保留=status["pending"],
                   新カテゴリ候補=status["new_category"],
                   未分類=len(texts) - len(cls))


# ============================================================
# 調査記録（Phase 2.5）
# ============================================================

def _to_jst(series):
    return pd.to_datetime(series, utc=True, format="ISO8601").dt.tz_convert(JST)


def duration_summary(groups, survey_types):
    """
    所要時間（入力開始〜保存）の平均・中央値・最大。現地入力のみ（紙からの転記は除外）。
    一人客とグループ客は所要時間が違うので分けても出す。
    """
    g = pd.DataFrame(groups)
    cols = ["区分", "件数", "平均(秒)", "中央値(秒)", "最大(秒)"]
    if g.empty or "duration_sec" not in g.columns:
        return pd.DataFrame(columns=cols)
    g = g[g["survey_type"].isin(survey_types) & (g["input_method"] == "field")
          & g["duration_sec"].notna()]
    rows = []
    for label, sub in [("全体", g), ("一人客", g[g["group_size"] == 1]),
                       ("グループ客", g[g["group_size"] > 1])]:
        d = sub["duration_sec"].astype(float)
        if len(d):
            rows.append((label, len(d), round(d.mean(), 1), round(d.median(), 1), int(d.max())))
        else:
            rows.append((label, 0, None, None, None))
    return pd.DataFrame(rows, columns=cols)


def stumble_ranking(groups, survey_types, questions):
    """つまずきフラグが多かった設問のランキング（グループ単位で数える）とメモ一覧"""
    counts, memos = {}, {}
    for g in groups:
        if g["survey_type"] not in survey_types:
            continue
        for qid, memo in (g.get("stumble_flags") or {}).items():
            counts[qid] = counts.get(qid, 0) + 1
            if memo:
                memos.setdefault(qid, []).append(memo)
    order = list(questions)
    ranked = sorted(counts.items(),
                    key=lambda x: (-x[1], order.index(x[0]) if x[0] in order else len(order)))
    rows = [(i + 1, qid, questions.get(qid, {}).get("text", qid), c,
             " / ".join(memos.get(qid, [])))
            for i, (qid, c) in enumerate(ranked)]
    return pd.DataFrame(rows, columns=["順位", "設問ID", "設問", "件数", "メモ"])


def contact_summary(refusals, groups, survey_types, by):
    """
    声かけ数・回答数・回答率を集計する。
    by: "location"（調査地点別）/ "hour"（時間帯別）/ "date"（日別）
    回答 = 保存済みグループ（現地入力のみ）、断り = refusals。声かけ = 回答 + 断り。
    """
    def frame(rows, kind):
        f = pd.DataFrame(rows, columns=["created_at", "location", "survey_type"]) if rows \
            else pd.DataFrame(columns=["created_at", "location", "survey_type"])
        f = f[f["survey_type"].isin(survey_types)]
        f["kind"] = kind
        return f

    ans = [(g["created_at"], g["location"], g["survey_type"]) for g in groups
           if g.get("input_method") == "field"]
    ref = [(r["created_at"], r["location"], r["survey_type"]) for r in refusals]
    f = pd.concat([frame(ans, "回答"), frame(ref, "断り")], ignore_index=True)
    cols = ["声かけ", "回答", "断り", "回答率(%)"]
    if f.empty:
        return pd.DataFrame(columns=[{"location": "調査地点", "hour": "時間帯",
                                      "date": "日付"}[by]] + cols)
    t = _to_jst(f["created_at"])
    if by == "location":
        f["key"], name = f["location"], "調査地点"
    elif by == "hour":
        f["key"], name = t.dt.hour.map(lambda h: f"{h:02d}時台"), "時間帯"
    else:
        f["key"], name = t.dt.strftime("%Y-%m-%d"), "日付"
    p = f.pivot_table(index="key", columns="kind", aggfunc="size", fill_value=0)
    p = p.reindex(columns=["回答", "断り"], fill_value=0).sort_index()
    out = pd.DataFrame({name: p.index, "回答": p["回答"].values, "断り": p["断り"].values})
    out["声かけ"] = out["回答"] + out["断り"]
    total = pd.DataFrame([{name: "合計", "回答": out["回答"].sum(), "断り": out["断り"].sum(),
                           "声かけ": out["声かけ"].sum()}])
    out = pd.concat([out, total], ignore_index=True)
    out["回答率(%)"] = (out["回答"] / out["声かけ"] * 100).round(1)
    return out[[name] + cols]


def response_mode_distribution(df):
    labels = {"interviewer": "調査員が読み上げ", "self": "本人が記入"}
    n = len(df)
    vc = df["response_mode"].fillna("unknown").value_counts() if n else pd.Series(dtype=int)
    rows = [(labels["interviewer"], int(vc.get("interviewer", 0))),
            (labels["self"], int(vc.get("self", 0)))]
    if vc.get("unknown", 0):
        rows.append(("記録なし（Phase 2.5以前）", int(vc["unknown"])))
    t = pd.DataFrame(rows, columns=["回答方式", "人数"])
    t["割合(%)"] = (t["人数"] / n * 100).round(1) if n else 0.0
    return t


# ============================================================
# 一括集計
# ============================================================

def run_aggregation(data, questions, aggregation_cfg, codebooks, *, survey_types,
                    exclude_residents, scope, seed, exclude_conformity, target_qids):
    """
    集計画面の「集計を実行」で行う処理をまとめて実行し、結果を dict で返す。
    data: db.load_all_for_aggregation() の戻り値
    target_qids: クロス集計の列（結果側）にする単一選択設問
    """
    base = build_respondents(data["groups"], data["responses"], data["answers"], questions)
    common = dict(survey_types=survey_types, exclude_residents=exclude_residents,
                  exclude_conformity=exclude_conformity)
    main = filter_respondents(base, questions, scope=scope, seed=seed, **common)
    df = main.df

    # 感度分析：全回答者 vs グループ代表1人（代表の選び方は現在の設定に合わせる）
    rep_scope = "rep_random" if scope == "rep_random" else "rep_first"
    all_df = filter_respondents(base, questions, scope="all", **common).df
    rep_df = filter_respondents(base, questions, scope=rep_scope, seed=seed, **common).df

    simple = []
    for qid, q in questions.items():
        if q["type"] == "free_text":
            continue
        t, n = tally(df, qid, q)
        simple.append(dict(qid=qid, text=q["text"], type=q["type"], table=t, n=n))

    cross, sens = [], []
    for ct in aggregation_cfg.get("cross_tabs", []):
        rq = ct["question_id"]
        for cq in target_qids:
            if cq == rq or rq not in questions or cq not in questions:
                continue
            t = crosstab(df, rq, questions[rq], cq, questions[cq])
            cross.append(dict(row_qid=rq, col_qid=cq, label=f"{ct['label']} × {questions[cq]['text']}",
                              table=t, test=independence_test(t)))
            ta = independence_test(crosstab(all_df, rq, questions[rq], cq, questions[cq]))
            tr = independence_test(crosstab(rep_df, rq, questions[rq], cq, questions[cq]))
            sens.append({"クロス集計": f"{ct['label']} × {cq}",
                         "全回答者 n": ta.n, "全回答者 検定": ta.method,
                         "全回答者 p": None if ta.p_value is None else round(ta.p_value, 4),
                         "代表1人 n": tr.n, "代表1人 検定": tr.method,
                         "代表1人 p": None if tr.p_value is None else round(tr.p_value, 4),
                         "判定の一致": _same_decision(ta, tr)})

    # 単純集計の感度分析（主要設問の割合を並べる）
    sens_simple = []
    for qid in target_qids:
        if qid not in questions:
            continue
        ta, na = tally(all_df, qid, questions[qid])
        tr, nr = tally(rep_df, qid, questions[qid])
        m = ta.merge(tr, on="選択肢", how="outer", suffixes=("_a", "_r"), sort=False).fillna(0)
        for _, row in m.iterrows():
            sens_simple.append({"設問": qid, "選択肢": row["選択肢"],
                                "全回答者(%)": row["割合(%)_a"], "代表1人(%)": row["割合(%)_r"],
                                "差(ポイント)": round(row["割合(%)_r"] - row["割合(%)_a"], 1),
                                "n（全/代表）": f"{na}/{nr}"})

    aw_cfg = aggregation_cfg.get("awareness_comparison", {})
    awareness = None
    if aw_cfg.get("unaided") in questions and aw_cfg.get("aided") in questions:
        u, a = aw_cfg["unaided"], aw_cfg["aided"]
        awareness = dict(summary=awareness_summary(df, u, a),
                         table=crosstab(df, u, questions[u], a, questions[a]))

    free = []
    for qid, cb in (codebooks or {}).items():
        if qid in questions:
            t, counts = classification_summary(df, data["answers"], data["classifications"], qid, cb)
            free.append(dict(qid=qid, text=questions[qid]["text"], table=t, counts=counts))

    groups_in_scope = [g for g in data["groups"] if g["survey_type"] in survey_types]
    records = dict(
        duration=duration_summary(data["groups"], survey_types),
        stumbles=stumble_ranking(data["groups"], survey_types, questions),
        contact_location=contact_summary(data["refusals"], data["groups"], survey_types, "location"),
        contact_hour=contact_summary(data["refusals"], data["groups"], survey_types, "hour"),
        contact_date=contact_summary(data["refusals"], data["groups"], survey_types, "date"),
        response_mode=response_mode_distribution(df),
        day_notes=pd.DataFrame(data.get("day_notes") or [],
                               columns=["survey_date", "weather", "crowd", "note"])
        .rename(columns={"survey_date": "日付", "weather": "天気", "crowd": "混雑", "note": "メモ"}),
        n_groups=len(groups_in_scope),
    )

    return dict(
        n=len(df), n_groups=int(df["group_id"].nunique()) if len(df) else 0,
        notes=main.notes, has_group_members=includes_group_members(df),
        simple=simple, group_sizes=group_size_distribution(df),
        branches=branch_distribution(df), cross=cross,
        sensitivity=pd.DataFrame(sens), sensitivity_simple=pd.DataFrame(sens_simple),
        sensitivity_n=(len(all_df), len(rep_df)),
        awareness=awareness, free_text=free, records=records,
    )


def _same_decision(a, b, alpha=0.05):
    if a.p_value is None or b.p_value is None:
        return "—"
    return "一致" if (a.p_value < alpha) == (b.p_value < alpha) else "不一致"
