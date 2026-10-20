"""回答入力画面 — 設問ウィザード形式（一人・グループ両対応）"""
import json
from datetime import datetime, timezone
import streamlit as st
from lib.config_loader import (
    get_questions, get_question_ids, get_locations,
    should_show_question, determine_branch, get_option_label,
)
from lib import db
from lib.session import keep_input_state, INPUT_WIDGET_PREFIXES

# 回答方式（回答ごとに記録）
RESPONSE_MODES = {"interviewer": "調査員が読み上げ", "self": "本人が記入"}
# 調査日メモの選択肢
WEATHER_OPTIONS = ["晴れ", "くもり", "雨", "雪", "その他"]
CROWD_OPTIONS = ["空いている", "ふつう", "混んでいる", "非常に混んでいる"]


# ============================================================
# セッションステート操作
# ============================================================

def _init():
    """初期化（phase がなければ setup から開始）"""
    # 前の設問の回答が消えないようにする（ウィジェット描画より前に呼ぶ必要がある）
    keep_input_state()
    if "sv_phase" not in st.session_state:
        st.session_state.sv_phase = "setup"
    if "sv_history" not in st.session_state:
        st.session_state.sv_history = []


def _member_answers(m):
    """session_state のウィジェットキーからメンバー m の回答を収集して返す"""
    questions = get_questions()
    out = {}
    for qid in get_question_ids():
        q = questions[qid]
        k = f"q_{qid}_m{m}"

        if q["type"] in ("single_choice", "scale"):
            v = st.session_state.get(k)
            if v is not None:
                out[qid] = {"value": v}
                if q.get("has_other") and v == "other":
                    txt = st.session_state.get(f"{k}_other_txt", "")
                    if txt:
                        out[f"{qid}_other"] = {"value": txt}

        elif q["type"] == "multi_choice":
            sel = [o["value"] for o in q.get("options", [])
                   if st.session_state.get(f"{k}_{o['value']}", False)]
            if q.get("has_other") and st.session_state.get(f"{k}_other_chk", False):
                sel.append("other")
                txt = st.session_state.get(f"{k}_other_txt", "")
                if txt:
                    out[f"{qid}_other"] = {"value": txt}
            if sel:
                out[qid] = {"values": sel}

        elif q["type"] == "free_text":
            v = st.session_state.get(k, "")
            if v.strip():
                out[qid] = {"value": v.strip()}
    return out


def _member_branch(m):
    return determine_branch(_member_answers(m))


def _all(group_size):
    """全メンバーの回答と分岐を一括取得"""
    ans, br = {}, {}
    for m in range(1, group_size + 1):
        ans[m] = _member_answers(m)
        br[m] = _member_branch(m)
    return ans, br


# ============================================================
# 設問ナビゲーション
# ============================================================

def _anyone_needs(qid, group_size):
    """少なくとも 1 人のメンバーがこの設問に回答すべきか"""
    for m in range(1, group_size + 1):
        if should_show_question(qid, _member_answers(m), _member_branch(m)):
            return True
    return False


def _next_qid(current, gs):
    ids = get_question_ids()
    for qid in ids[ids.index(current) + 1:]:
        if _anyone_needs(qid, gs):
            return qid
    return None


def _first_qid(gs):
    for qid in get_question_ids():
        if _anyone_needs(qid, gs):
            return qid
    return None


# ============================================================
# 下書き保存・復元
# ============================================================

def _save_draft_to_db():
    """現在の入力状態をDBの session_draft に保存"""
    setup = st.session_state.sv_setup
    widgets = {k: st.session_state[k] for k in st.session_state
               if k.startswith(INPUT_WIDGET_PREFIXES)}
    payload = {
        "draft_id": st.session_state.get("sv_draft_id"),
        "setup": setup,
        "widgets": widgets,
        "current_qid": st.session_state.get("sv_cur_qid"),
        "history": st.session_state.get("sv_history", []),
    }
    new_id = db.save_draft(setup, payload)
    st.session_state.sv_draft_id = new_id


def _restore_draft(draft_row):
    """DBの下書きから状態を復元"""
    d = draft_row["session_draft"]
    if isinstance(d, str):
        d = json.loads(d)
    st.session_state.sv_setup = d["setup"]
    st.session_state.sv_draft_id = draft_row["id"]
    st.session_state.sv_phase = "questions"
    st.session_state.sv_cur_qid = d.get("current_qid")
    st.session_state.sv_history = d.get("history", [])
    for k, v in d.get("widgets", {}).items():
        st.session_state[k] = v


# ============================================================
# ウィジェット描画
# ============================================================

def _render_widget(qid, q, m, solo):
    """メンバー m 用の設問ウィジェットを1つ描画"""
    k = f"q_{qid}_m{m}"

    if q["type"] in ("single_choice", "scale"):
        opts = [o["value"] for o in q["options"]]
        labs = {o["value"]: o["label"] for o in q["options"]}
        if q.get("has_other"):
            opts.append("other")
            labs["other"] = "その他"
        lbl = "選択" if solo else f"メンバー {m}"
        st.radio(lbl, opts, format_func=lambda v, _l=labs: _l.get(v, v),
                 index=None, key=k, label_visibility="collapsed" if solo else "visible")
        if q.get("has_other") and st.session_state.get(k) == "other":
            st.text_input("その他の内容", key=f"{k}_other_txt")

    elif q["type"] == "multi_choice":
        if q.get("max_select"):
            st.caption(f"（最大{q['max_select']}つまで）")
        for o in q["options"]:
            st.checkbox(o["label"], key=f"{k}_{o['value']}")
        if q.get("has_other"):
            st.checkbox("その他", key=f"{k}_other_chk")
            if st.session_state.get(f"{k}_other_chk", False):
                st.text_input("その他の内容", key=f"{k}_other_txt")

    elif q["type"] == "free_text":
        st.text_area("回答を入力" if solo else f"メンバー {m}",
                     key=k, label_visibility="collapsed" if solo else "visible")


def _copy_all(qid, q, members):
    """メンバー1の回答を他メンバーにコピー"""
    if 1 not in members:
        return
    s = f"q_{qid}_m1"
    for m in members:
        if m == 1:
            continue
        t = f"q_{qid}_m{m}"
        if q["type"] in ("single_choice", "scale", "free_text"):
            st.session_state[t] = st.session_state.get(s)
            if q.get("has_other"):
                st.session_state[f"{t}_other_txt"] = st.session_state.get(f"{s}_other_txt", "")
        elif q["type"] == "multi_choice":
            for o in q.get("options", []):
                st.session_state[f"{t}_{o['value']}"] = st.session_state.get(f"{s}_{o['value']}", False)
            if q.get("has_other"):
                st.session_state[f"{t}_other_chk"] = st.session_state.get(f"{s}_other_chk", False)
                st.session_state[f"{t}_other_txt"] = st.session_state.get(f"{s}_other_txt", "")


# ============================================================
# バリデーション
# ============================================================

def _validate(qid, q, members):
    """必須設問の未入力チェック。エラーメッセージのリストを返す。"""
    if not q.get("required"):
        return []
    errs = []
    gs = st.session_state.sv_setup["group_size"]
    for m in members:
        k = f"q_{qid}_m{m}"
        label = "" if gs == 1 else f"メンバー {m}: "

        if q["type"] in ("single_choice", "scale"):
            if st.session_state.get(k) is None:
                errs.append(f"{label}選択してください")

        elif q["type"] == "multi_choice":
            count = sum(1 for o in q.get("options", [])
                        if st.session_state.get(f"{k}_{o['value']}", False))
            if q.get("has_other") and st.session_state.get(f"{k}_other_chk", False):
                count += 1
            if count == 0:
                errs.append(f"{label}1つ以上選択してください")
            max_sel = q.get("max_select")
            if max_sel and count > max_sel:
                errs.append(f"{label}{max_sel}つまで選択してください")

        elif q["type"] == "free_text":
            if not st.session_state.get(k, "").strip():
                errs.append(f"{label}回答を入力してください")
    return errs


# ============================================================
# 声かけカウンター（画面上部に常時表示）
# ============================================================

def _current_place():
    """断り記録に付ける (調査地点, 調査区分)。入力中ならその設定、設定画面なら選択中の値。"""
    setup = st.session_state.get("sv_setup")
    if setup and st.session_state.get("sv_phase") in ("questions", "review"):
        return setup["location"], setup["survey_type"]
    sticky = st.session_state.get("sticky_setup", {})
    loc = st.session_state.get("su_loc") or sticky.get("location") or get_locations()[0]
    stype = st.session_state.get("su_type") or sticky.get("survey_type_label", "本調査")
    return loc, ("main" if stype == "本調査" else "pretest")


def _on_refused():
    loc, stype = _current_place()
    db.add_refusal(loc, stype)
    st.toast(f"断られた を記録しました（{loc}）")


def _on_undo_refused():
    row = db.undo_last_refusal()
    st.toast("直前の「断られた」を1件取り消しました" if row else "今日の「断られた」記録はありません")


def _render_counter():
    try:
        refused, answered = db.get_today_contact_counts()
    except Exception:
        st.warning("声かけカウンターを読み込めません。"
                   "Supabase で docs/migration_phase2_5.sql を実行してください。")
        return
    contacts = refused + answered
    rate = f"{answered / contacts * 100:.1f}%" if contacts else "—"
    with st.container(border=True):
        st.markdown(f"**声かけ {contacts}件 ／ 回答 {answered}件 ／ 回答率 {rate}**",
                    help="今日・現地入力分。回答は保存すると自動で+1（1組=声かけ1回）")
        # スマホでも横並びのままにする（st.columns は狭い画面で縦に積まれるため）
        with st.container(horizontal=True):
            st.button("🙅 断られた +1", on_click=_on_refused, key="cnt_refused", width="stretch")
            st.button("↩ 戻す", on_click=_on_undo_refused, key="cnt_undo")


# ============================================================
# 調査日メモ
# ============================================================

def _render_day_note():
    today = db.today_jst()
    with st.expander(f"📝 調査日メモ（{today.strftime('%m/%d')}の天気・混雑・気づき）"):
        try:
            cur = db.get_day_note(today) or {}
        except Exception:
            st.warning("調査日メモを読み込めません（docs/migration_phase2_5.sql が未実行かもしれません）")
            return
        with st.form("day_note_form"):
            w = cur.get("weather")
            weather = st.radio("天気", WEATHER_OPTIONS, horizontal=True,
                               index=WEATHER_OPTIONS.index(w) if w in WEATHER_OPTIONS else None)
            c = cur.get("crowd")
            crowd = st.radio("混雑具合", CROWD_OPTIONS, horizontal=True,
                             index=CROWD_OPTIONS.index(c) if c in CROWD_OPTIONS else None)
            note = st.text_area("気づいたこと", value=cur.get("note") or "",
                                placeholder="例：午後から団体客が増えた、駅前は立ち止まってもらいにくい")
            if st.form_submit_button("メモを保存", use_container_width=True):
                db.save_day_note(today, weather, crowd, note.strip())
                st.success("保存しました")


# ============================================================
# 画面: セットアップ
# ============================================================

def _sticky_index(options, key):
    """前回の設定値を初期選択にする（連続して入力するとき毎回選び直さなくて済むように）"""
    v = st.session_state.get("sticky_setup", {}).get(key)
    return options.index(v) if v in options else 0


def _page_setup():
    st.subheader("調査の設定")

    locs = get_locations()
    loc = st.selectbox("調査地点", locs, key="su_loc",
                       index=_sticky_index(locs, "location"))
    stype_opts = ["本調査", "プレテスト"]
    stype = st.radio("調査区分", stype_opts, key="su_type", horizontal=True,
                     index=_sticky_index(stype_opts, "survey_type_label"))
    meth_opts = ["現地入力", "紙からの転記"]
    imethod = st.radio("入力方法", meth_opts, key="su_meth", horizontal=True,
                       index=_sticky_index(meth_opts, "input_method_label"))
    rmode_opts = list(RESPONSE_MODES)
    rmode = st.radio("回答方式", rmode_opts, key="su_rmode", horizontal=True,
                     format_func=RESPONSE_MODES.get,
                     index=_sticky_index(rmode_opts, "response_mode"),
                     help="グループの場合は確認画面でメンバーごとに変更できます")

    st.markdown("---")
    mode = st.radio("回答者", ["一人", "グループ"], key="su_mode", horizontal=True)
    gs = 1
    if mode == "グループ":
        gs = st.slider("グループ人数", 2, 6, 2, key="su_gs")

    # 下書き復元
    drafts = db.load_drafts()
    if drafts:
        st.markdown("---")
        st.warning(f"未完了の入力が {len(drafts)} 件あります")
        for dr in drafts:
            c1, c2, c3 = st.columns([4, 1, 1])
            with c1:
                st.caption(f"{dr['location']} / {dr['group_size']}人 / {str(dr['created_at'])[:16]}")
            with c2:
                if st.button("再開", key=f"res_{dr['id']}"):
                    _restore_draft(dr)
                    st.rerun()
            with c3:
                if st.button("破棄", key=f"del_{dr['id']}"):
                    db.delete_draft(dr["id"])
                    st.rerun()

    st.markdown("---")
    if st.button("入力開始", use_container_width=True, type="primary"):
        st.session_state.sticky_setup = {
            "location": loc, "survey_type_label": stype,
            "input_method_label": imethod, "response_mode": rmode,
        }
        st.session_state.sv_setup = {
            "location": loc,
            "survey_type": "main" if stype == "本調査" else "pretest",
            "input_method": "field" if imethod == "現地入力" else "transcription",
            "group_size": gs,
            "response_mode": rmode,
            # 所要時間の計測開始（保存時との差を秒で記録する）
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        first = _first_qid(gs)
        if first:
            st.session_state.sv_phase = "questions"
            st.session_state.sv_cur_qid = first
            st.session_state.sv_history = [first]
            _save_draft_to_db()
        st.rerun()

    st.markdown("---")
    _render_day_note()


# ============================================================
# 画面: 設問入力
# ============================================================

def _page_question():
    setup = st.session_state.sv_setup
    gs = setup["group_size"]
    cur = st.session_state.sv_cur_qid
    questions = get_questions()
    q = questions[cur]

    # 進捗バー
    ids = get_question_ids()
    st.progress((ids.index(cur) + 1) / len(ids))

    # 設問テキスト ＋ つまずきフラグ
    st.subheader(q["text"])
    st.toggle("⚠️ つまずき", key=f"flag_{cur}",
              help="回答者が迷った・意味が伝わらなかった設問に印をつける")
    if st.session_state.get(f"flag_{cur}"):
        st.text_input("つまずきメモ（任意）", key=f"flagmemo_{cur}",
                      placeholder="例：「地域通貨」の意味が伝わらなかった")
    if "description" in q:
        st.caption(q["description"])

    # このメンバーが回答すべきか
    vis = [m for m in range(1, gs + 1)
           if should_show_question(cur, _member_answers(m), _member_branch(m))]

    if not vis:
        # 誰も対象でないのでスキップ
        _do_next(gs)
        st.rerun()
        return

    solo = (gs == 1)
    for m in vis:
        if not solo:
            with st.container(border=True):
                _render_widget(cur, q, m, solo)
        else:
            _render_widget(cur, q, m, solo)

    # 「全員同じ」ボタン
    # 描画済みウィジェットの値はその回の実行中に書き換えられないので、
    # コピーは on_click（次の実行でウィジェットを描画する前に動く）で行う
    if not solo and len(vis) > 1:
        st.button("全員同じ（メンバー1をコピー）", use_container_width=True,
                  on_click=_copy_all, args=(cur, q, vis))

    st.markdown("---")

    # ナビゲーション
    c1, c2 = st.columns(2)
    with c1:
        hist = st.session_state.sv_history
        if len(hist) > 1:
            if st.button("← 戻る", use_container_width=True):
                hist.pop()
                st.session_state.sv_cur_qid = hist[-1]
                st.rerun()
        else:
            if st.button("← 設定に戻る", use_container_width=True):
                _back_to_setup()
                st.rerun()
    with c2:
        if st.button("次へ →", use_container_width=True, type="primary"):
            errs = _validate(cur, q, vis)
            if errs:
                for e in errs:
                    st.error(e)
            else:
                _do_next(gs)
                _save_draft_to_db()
                st.rerun()


def _do_next(gs):
    cur = st.session_state.sv_cur_qid
    nxt = _next_qid(cur, gs)
    if nxt:
        st.session_state.sv_cur_qid = nxt
        st.session_state.sv_history.append(nxt)
    else:
        st.session_state.sv_phase = "review"


def _back_to_setup():
    # 下書きは残したまま setup に戻る
    st.session_state.sv_phase = "setup"
    st.session_state.sv_history = []


# ============================================================
# 画面: 確認・保存
# ============================================================

def _page_review():
    setup = st.session_state.sv_setup
    gs = setup["group_size"]
    questions = get_questions()
    solo = (gs == 1)

    st.subheader("回答の確認")

    for m in range(1, gs + 1):
        ans = _member_answers(m)
        br = _member_branch(m)

        if not solo:
            st.markdown(f"#### メンバー {m}")

        for qid in get_question_ids():
            if not should_show_question(qid, ans, br):
                continue
            q = questions[qid]
            a = ans.get(qid, {})
            display = _format_answer(qid, q, a, ans)
            st.text(f"{q['text']}: {display}")

        # 回答方式（設定画面の値が初期値。メンバーごとに変更可）
        rk = f"rmode_m{m}"
        if rk not in st.session_state:
            st.session_state[rk] = setup.get("response_mode", "interviewer")
        st.radio("回答方式", list(RESPONSE_MODES), key=rk, horizontal=True,
                 format_func=RESPONSE_MODES.get)
        if not solo:
            st.checkbox("同調の可能性あり", key=f"conformity_m{m}")
        st.markdown("---")

    flags = _stumble_flags()
    if flags:
        st.markdown("**⚠️ つまずきフラグ**")
        for qid, memo in flags.items():
            st.text(f"・{questions[qid]['text']}" + (f"：{memo}" if memo else ""))
        st.markdown("---")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("← 修正する", use_container_width=True):
            st.session_state.sv_phase = "questions"
            if st.session_state.sv_history:
                st.session_state.sv_cur_qid = st.session_state.sv_history[-1]
            st.rerun()
    with c2:
        if st.button("保存する", use_container_width=True, type="primary"):
            _do_save()
            st.rerun()


def _format_answer(qid, q, a, all_ans):
    """回答の表示用文字列を作る"""
    if "value" in a:
        if q["type"] in ("single_choice", "scale"):
            return get_option_label(qid, a["value"])
        return a["value"]
    if "values" in a:
        parts = []
        for v in a["values"]:
            if v == "other":
                ot = all_ans.get(f"{qid}_other", {}).get("value", "")
                parts.append(f"その他: {ot}")
            else:
                parts.append(get_option_label(qid, v))
        return "、".join(parts)
    return "（未回答）"


# ============================================================
# 保存処理
# ============================================================

def _do_save():
    setup = st.session_state.sv_setup
    gs = setup["group_size"]
    questions = get_questions()

    all_ans, all_br = _all(gs)

    # 表示対象外の設問の回答を除外して保存
    clean = {}
    for m in range(1, gs + 1):
        clean[m] = {}
        for qid in get_question_ids():
            if should_show_question(qid, all_ans[m], all_br[m]):
                if qid in all_ans[m]:
                    clean[m][qid] = all_ans[m][qid]
                # _other もあれば含める
                okey = f"{qid}_other"
                if okey in all_ans[m]:
                    clean[m][okey] = all_ans[m][okey]

    flags = {m: st.session_state.get(f"conformity_m{m}", False)
             for m in range(1, gs + 1)}
    modes = {m: st.session_state.get(f"rmode_m{m}", setup.get("response_mode"))
             for m in range(1, gs + 1)}

    save_setup = {**setup, "draft_id": st.session_state.get("sv_draft_id")}
    db.save_survey(save_setup, clean, flags, all_br,
                   response_modes=modes, stumble_flags=_stumble_flags())

    _reset()
    st.session_state.sv_phase = "done"


def _stumble_flags():
    """
    つまずきフラグを {設問ID: メモ} で返す。
    「戻る」で分岐が変わって通らなくなった設問のフラグは含めない。
    """
    out = {}
    for qid in get_question_ids():
        if qid in st.session_state.get("sv_history", []) and st.session_state.get(f"flag_{qid}"):
            out[qid] = (st.session_state.get(f"flagmemo_{qid}") or "").strip()
    return out


def _reset():
    """入力に関するセッションステートをクリア（sticky_setup は次の入力のために残す）"""
    remove = [k for k in list(st.session_state.keys())
              if k.startswith(INPUT_WIDGET_PREFIXES + ("sv_", "su_"))]
    for k in remove:
        del st.session_state[k]


# ============================================================
# 画面: 保存完了
# ============================================================

def _page_done():
    st.success("回答を保存しました")
    if st.button("次の回答者を入力", use_container_width=True, type="primary"):
        st.session_state.sv_phase = "setup"
        st.rerun()


# ============================================================
# メイン
# ============================================================

_init()
_render_counter()

phase = st.session_state.get("sv_phase", "setup")
if phase == "setup":
    _page_setup()
elif phase == "questions":
    _page_question()
elif phase == "review":
    _page_review()
elif phase == "done":
    _page_done()
