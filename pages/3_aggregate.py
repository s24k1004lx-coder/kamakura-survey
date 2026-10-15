"""集計画面 — 単純集計・クロス集計・検定・感度分析・調査記録"""
from datetime import datetime

import pandas as pd
import streamlit as st

from lib import db, stats
from lib.config_loader import (
    get_questions, get_aggregation_config, load_codebook,
)
from lib.export import bar_chart_png, tables_to_csv, html_report

SURVEY_TYPES = {"main": "本調査", "pretest": "プレテスト"}
INDEPENDENCE_NOTE = ("※ グループ回答を含むため、回答の独立性が完全には保証されない"
                     "（感度分析タブで代表1人のみの結果と比較）")


# ============================================================
# 表示ヘルパー
# ============================================================

@st.cache_data(show_spinner=False)
def _chart(table, title, note):
    return bar_chart_png(table, table.columns[0], table.columns[1], title,
                         pct_col="割合(%)" if "割合(%)" in table.columns else None, note=note)


def _chart_block(table, title, note, fname):
    """グラフ表示＋PNGダウンロード"""
    if table is None or len(table) == 0 or table.iloc[:, 1].sum() == 0:
        st.caption("（データなし）")
        return
    png = _chart(table, title, note)
    st.image(png, use_container_width=True)
    st.download_button("PNGをダウンロード", png, file_name=f"{fname}.png", mime="image/png",
                       key=f"png_{fname}")


def _show(table):
    """表を表示（RangeIndex は隠す）"""
    st.dataframe(table, use_container_width=True,
                 hide_index=isinstance(table.index, pd.RangeIndex))


def _test_line(test, has_group_members):
    if test.p_value is None:
        st.caption(test.summary())
        return
    st.markdown(f"**{test.summary()}**")
    if test.note:
        st.caption(test.note)
    if has_group_members:
        st.caption(INDEPENDENCE_NOTE)


# ============================================================
# 絞り込み条件
# ============================================================

st.title("集計")

questions = get_questions()
agg_cfg = get_aggregation_config()
codebooks = load_codebook().get("codebooks", {})

single_qids = [qid for qid, q in questions.items() if q["type"] in ("single_choice", "scale")]
default_targets = [q for q in ["Q4", "Q5", "Q6", "C3"] if q in single_qids]

with st.container(border=True):
    st.markdown("**絞り込み条件**")
    stypes = st.multiselect("調査区分", list(SURVEY_TYPES), default=["main"],
                            format_func=SURVEY_TYPES.get, key="ag_stypes")
    excl_res = st.checkbox("鎌倉市内在住者（住民）を除外し、観光客のみで集計", value=True,
                           key="ag_excl_res")
    scope = st.radio("回答者の範囲", list(stats.SCOPES), format_func=stats.SCOPES.get,
                     key="ag_scope")
    seed = 0
    if scope == "rep_random":
        seed = int(st.number_input("乱数シード（同じ値なら同じ人が選ばれます）", min_value=0,
                                   value=2026, step=1, key="ag_seed"))
    excl_conf = st.checkbox("「同調の可能性あり」の回答を除外", key="ag_excl_conf")
    targets = st.multiselect(
        "クロス集計で比べる設問（属性 × この設問）", single_qids, default=default_targets,
        format_func=lambda q: f"{q} {questions[q]['text'][:20]}", key="ag_targets")
    run = st.button("集計を実行", type="primary", use_container_width=True)

if run:
    if not stypes:
        st.error("調査区分を1つ以上選んでください")
        st.stop()
    try:
        with st.spinner("集計中…"):
            data = db.load_all_for_aggregation()
            result = stats.run_aggregation(
                data, questions, agg_cfg, codebooks, survey_types=tuple(stypes),
                exclude_residents=excl_res, scope=scope, seed=seed,
                exclude_conformity=excl_conf, target_qids=targets)
    except Exception as e:
        st.error("データを読み込めませんでした。Supabase で docs/migration_phase2_5.sql を"
                 f"実行済みか確認してください。\n\n詳細: {e}")
        st.stop()
    st.session_state.ag_result = result
    st.session_state.pop("ag_report", None)  # 条件が変わったので古いレポートは捨てる
    st.session_state.ag_conditions = [
        "調査区分: " + "・".join(SURVEY_TYPES[s] for s in stypes),
        "住民: " + ("除外" if excl_res else "含む"),
        "回答者の範囲: " + stats.SCOPES[scope] + (f"（乱数シード {seed}）" if scope == "rep_random" else ""),
        "同調フラグ: " + ("除外" if excl_conf else "含む"),
        "集計日時: " + datetime.now(db.JST).strftime("%Y-%m-%d %H:%M"),
    ]

res = st.session_state.get("ag_result")
if res is None:
    st.info("条件を選んで「集計を実行」を押してください")
    st.stop()

conditions = st.session_state.ag_conditions
st.caption(" ／ ".join(conditions))
for note in res["notes"]:
    st.caption(note)
st.markdown(f"### 集計対象: {res['n']}人（{res['n_groups']}グループ）")
if res["n"] == 0:
    st.warning("条件に合う回答がありません。調査区分にプレテストを含めるなど条件を見直してください。")

tabs = st.tabs(["単純集計", "クロス集計・検定", "感度分析", "想起・利用", "自由記述",
                "調査記録", "ダウンロード"])

# ============================================================
# 単純集計
# ============================================================

with tabs[0]:
    st.markdown("#### グループ人数の分布")
    _show(res["group_sizes"])
    st.markdown("#### 分岐の内訳")
    _show(res["branches"])
    st.markdown("#### 各設問")
    # グラフ描画は1枚0.1秒ほどかかるので、必要なときだけ描く（一度描いたものはキャッシュ）
    show_charts = st.toggle("グラフを表示（論文用PNGのダウンロード付き）", key="ag_charts")
    for item in res["simple"]:
        multi = item["type"] == "multi_choice"
        head = f"{item['qid']} {item['text']}（n={item['n']}{'・複数回答' if multi else ''}）"
        with st.expander(head):
            _show(item["table"])
            if show_charts:
                note = f"n={item['n']}" + ("（複数回答・割合は回答者に対する%）" if multi else "")
                _chart_block(item["table"], f"{item['qid']} {item['text']}", note,
                             f"simple_{item['qid']}")

# ============================================================
# クロス集計・検定
# ============================================================

with tabs[1]:
    st.caption(f"期待度数{stats.MIN_EXPECTED}未満のセルがある場合はフィッシャーの正確確率検定に自動で切り替えます。"
               "* p<.05, ** p<.01, n.s. 有意差なし。V はクラメールの連関係数（効果量）。")
    if not res["cross"]:
        st.caption("クロス集計の対象設問が選ばれていません")
    for c in res["cross"]:
        t = c["test"]
        badge = "検定不可" if t.p_value is None else f"p = {stats.format_p(t.p_value)}"
        with st.expander(f"{c['label']}（{badge}）"):
            if c["table"].empty:
                st.caption("（データなし）")
                continue
            st.markdown("度数")
            _show(c["table"])
            st.markdown("行％")
            _show(stats.row_percent(c["table"]))
            _test_line(c["test"], res["has_group_members"])

# ============================================================
# 感度分析
# ============================================================

with tabs[2]:
    n_all, n_rep = res["sensitivity_n"]
    st.markdown(f"全回答者（n={n_all}）と、各グループから代表1人のみ（n={n_rep}）で"
                "同じ集計・検定を行い、グループ回答が結果に与える影響を確認します。"
                "（調査区分・住民・同調フラグの条件は共通）")
    st.markdown("#### 検定結果の比較")
    if len(res["sensitivity"]):
        _show(res["sensitivity"])
        st.caption("判定の一致: 有意水準5%で「有意／有意でない」の判定が両者で同じかどうか")
    st.markdown("#### 主要設問の割合の比較")
    if len(res["sensitivity_simple"]):
        _show(res["sensitivity_simple"])

# ============================================================
# 想起・利用
# ============================================================

with tabs[3]:
    aw = res["awareness"]
    if aw:
        st.markdown("#### 純粋想起と助成想起の比較")
        _show(aw["summary"])
        _chart_block(aw["summary"].rename(columns={"指標": "選択肢", "人数": "度数"})[["選択肢", "度数", "割合(%)"]],
                     "純粋想起と助成想起", "割合は各設問の回答者に対する%", "awareness")
        st.markdown("#### 純粋想起 × 助成想起")
        if not aw["table"].empty:
            _show(aw["table"])
    st.markdown("#### 利用意向・未利用理由")
    for item in res["simple"]:
        if item["qid"] in ("Q6", "B1", "C1", "C2", "C3"):
            st.markdown(f"**{item['qid']} {item['text']}**（n={item['n']}）")
            _show(item["table"])

# ============================================================
# 自由記述
# ============================================================

with tabs[4]:
    for f in res["free_text"]:
        st.markdown(f"#### {f['qid']} {f['text']}")
        st.caption(" ／ ".join(f"{k} {v}件" for k, v in f["counts"].items()))
        if f["counts"]["分類済み"]:
            _show(f["table"])
        else:
            st.caption("まだ分類されていません（分類画面は Phase 4 で実装予定）")

# ============================================================
# 調査記録（Phase 2.5）
# ============================================================

with tabs[5]:
    rec = res["records"]
    st.caption("調査記録は調査区分のみで絞り込みます（住民・範囲の条件は回答方式以外には適用しません）")
    st.markdown("#### 声かけ数・回答率")
    st.caption("回答 = 保存した組数（現地入力のみ）、声かけ = 回答 + 断られた")
    for key, label in [("contact_location", "調査地点別"), ("contact_hour", "時間帯別"),
                       ("contact_date", "日別")]:
        st.markdown(f"**{label}**")
        _show(rec[key])
    st.markdown("#### 所要時間（入力開始〜保存）")
    st.caption("現地入力のみ。下書きから再開した場合は中断時間を含みます")
    _show(rec["duration"])
    st.markdown("#### つまずきが多かった設問ランキング")
    if len(rec["stumbles"]):
        _show(rec["stumbles"])
    else:
        st.caption("つまずきフラグはまだありません")
    st.markdown("#### 回答方式")
    _show(rec["response_mode"])
    st.markdown("#### 調査日メモ")
    if len(rec["day_notes"]):
        _show(rec["day_notes"])
    else:
        st.caption("調査日メモはまだありません")

# ============================================================
# ダウンロード
# ============================================================


def _all_tables():
    out = [("集計条件", pd.DataFrame({"条件": conditions + res["notes"]})),
           ("グループ人数の分布", res["group_sizes"]), ("分岐の内訳", res["branches"])]
    for i in res["simple"]:
        out.append((f"単純集計 {i['qid']} {i['text']} (n={i['n']})", i["table"]))
    for c in res["cross"]:
        out.append((f"クロス集計 {c['label']} / {c['test'].summary()}", c["table"]))
    out.append(("感度分析 検定結果", res["sensitivity"]))
    out.append(("感度分析 主要設問の割合", res["sensitivity_simple"]))
    if res["awareness"]:
        out.append(("想起の比較", res["awareness"]["summary"]))
        out.append(("純粋想起×助成想起", res["awareness"]["table"]))
    for f in res["free_text"]:
        out.append((f"自由記述の分類 {f['qid']}", f["table"]))
    rec = res["records"]
    out += [("声かけ 調査地点別", rec["contact_location"]), ("声かけ 時間帯別", rec["contact_hour"]),
            ("声かけ 日別", rec["contact_date"]), ("所要時間", rec["duration"]),
            ("つまずきランキング", rec["stumbles"]), ("回答方式", rec["response_mode"]),
            ("調査日メモ", rec["day_notes"])]
    return out


def _report():
    sections = [dict(heading="集計対象", text=[f"{res['n']}人（{res['n_groups']}グループ）"] + res["notes"],
                     tables=[("グループ人数の分布", res["group_sizes"]), ("分岐の内訳", res["branches"])])]
    imgs = []
    for i in res["simple"]:
        if len(i["table"]) and i["table"]["度数"].sum():
            imgs.append(_chart(i["table"], f"{i['qid']} {i['text']}", f"n={i['n']}"))
    sections.append(dict(heading="単純集計", images=imgs,
                         tables=[(f"{i['qid']} {i['text']} (n={i['n']})", i["table"]) for i in res["simple"]]))
    cross_text = [INDEPENDENCE_NOTE] if res["has_group_members"] else []
    sections.append(dict(heading="クロス集計・検定", text=cross_text,
                         tables=[(f"{c['label']} — {c['test'].summary()}", c["table"]) for c in res["cross"]]))
    n_all, n_rep = res["sensitivity_n"]
    sections.append(dict(heading="感度分析", text=[f"全回答者 n={n_all} / 代表1人 n={n_rep}"],
                         tables=[("検定結果の比較", res["sensitivity"]),
                                 ("主要設問の割合の比較", res["sensitivity_simple"])]))
    if res["awareness"]:
        sections.append(dict(heading="想起の比較", tables=[("", res["awareness"]["summary"]),
                                                          ("純粋想起×助成想起", res["awareness"]["table"])]))
    sections.append(dict(heading="自由記述の分類",
                         tables=[(f"{f['qid']} {f['text']}", f["table"]) for f in res["free_text"]]))
    rec = res["records"]
    sections.append(dict(heading="調査記録", tables=[
        ("声かけ 調査地点別", rec["contact_location"]), ("声かけ 時間帯別", rec["contact_hour"]),
        ("所要時間", rec["duration"]), ("つまずきランキング", rec["stumbles"]),
        ("回答方式", rec["response_mode"]), ("調査日メモ", rec["day_notes"])]))
    return html_report("鎌倉アンケート 集計レポート", conditions, sections)


with tabs[6]:
    stamp = datetime.now(db.JST).strftime("%Y%m%d_%H%M")
    st.download_button("集計結果CSV（全表）", tables_to_csv(_all_tables()),
                       file_name=f"aggregate_{stamp}.csv", mime="text/csv",
                       use_container_width=True)
    if st.button("HTMLレポートを作成", use_container_width=True):
        st.session_state.ag_report = _report()
    if st.session_state.get("ag_report"):
        st.download_button("HTMLレポートをダウンロード", st.session_state.ag_report.encode("utf-8"),
                           file_name=f"report_{stamp}.html", mime="text/html",
                           use_container_width=True, type="primary")
    st.caption("論文用の図（PNG）は「単純集計」タブで「グラフを表示」をオンにすると各設問からダウンロードできます")
