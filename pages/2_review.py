"""直近の入力 確認・修正・削除画面"""
import streamlit as st
from lib.config_loader import (
    get_questions, get_question_ids, should_show_question, get_option_label,
)
from lib import db


# ============================================================
# ヘルパー関数
# ============================================================

def _format(qid, q, a, ans_map):
    """回答の表示文字列を組み立てる"""
    if a.get("value") and q["type"] in ("single_choice", "scale"):
        return get_option_label(qid, a["value"])
    if a.get("value"):
        return a["value"]
    if a.get("values"):
        parts = []
        for v in a["values"]:
            if v == "other":
                ot = ans_map.get(f"{qid}_other", {}).get("value", "")
                parts.append(f"その他: {ot}")
            else:
                parts.append(get_option_label(qid, v))
        return "、".join(parts)
    return "（未回答）"


def _render_readonly(qid, q, a, ans_map):
    """読み取り専用で回答を表示"""
    display = _format(qid, q, a, ans_map)
    st.text(f"{q['text']}: {display}")


def _render_edit_widget(qid, q, a, ans_map, m, gid):
    """編集用ウィジェットを描画"""
    k = f"rve_{gid}_{m}_{qid}"

    if q["type"] in ("single_choice", "scale"):
        opts = [o["value"] for o in q["options"]]
        labs = {o["value"]: o["label"] for o in q["options"]}
        cur = a.get("value")
        idx = opts.index(cur) if cur in opts else None
        st.radio(q["text"], opts, format_func=lambda v, _l=labs: _l.get(v, v),
                 index=idx, key=k)

    elif q["type"] == "multi_choice":
        cur_vals = a.get("values") or []
        st.write(q["text"])
        for o in q["options"]:
            st.checkbox(o["label"], value=o["value"] in cur_vals,
                        key=f"{k}_{o['value']}")
        if q.get("has_other"):
            st.checkbox("その他", value="other" in cur_vals, key=f"{k}_other_chk")
            other_a = ans_map.get(f"{qid}_other")
            ot = other_a["value"] if other_a else ""
            if st.session_state.get(f"{k}_other_chk", False):
                st.text_input("その他の内容", value=ot, key=f"{k}_other_txt")

    elif q["type"] == "free_text":
        st.text_area(q["text"], value=a.get("value", ""), key=k)


def _save_edits(ans_rows, qid_prefix):
    """編集ウィジェットの値をDBに保存"""
    questions = get_questions()
    for a in ans_rows:
        qid = a["question_id"]
        if qid.endswith("_other"):
            continue
        q = questions.get(qid)
        if q is None:
            continue
        k = f"{qid_prefix}_{qid}"

        if q["type"] in ("single_choice", "scale"):
            new_val = st.session_state.get(k)
            if new_val is not None and new_val != a.get("value"):
                db.update_answer(a["id"], new_value=new_val)

        elif q["type"] == "multi_choice":
            new_vals = [o["value"] for o in q.get("options", [])
                        if st.session_state.get(f"{k}_{o['value']}", False)]
            if q.get("has_other") and st.session_state.get(f"{k}_other_chk", False):
                new_vals.append("other")
            old_vals = a.get("values") or []
            if set(new_vals) != set(old_vals):
                db.update_answer(a["id"], new_values=new_vals)

        elif q["type"] == "free_text":
            new_val = st.session_state.get(k, "").strip()
            if new_val != (a.get("value") or ""):
                db.update_answer(a["id"], new_value=new_val)


# ============================================================
# メイン画面
# ============================================================

st.title("確認・修正")

groups = db.get_recent_groups(limit=30)

if not groups:
    st.info("まだ回答がありません")
    st.stop()

# --- 表示切り替え ---
show_deleted = st.checkbox("削除済みも表示する", key="rv_show_del")

for g in groups:
    if not show_deleted and g["is_deleted"]:
        continue

    # ヘッダ
    dt = str(g["created_at"])[:16]
    tag = "プレテスト" if g["survey_type"] == "pretest" else "本調査"
    del_mark = " [削除済み]" if g["is_deleted"] else ""
    label = f"{dt} | {g['location']} | {g['group_size']}人 | {tag}{del_mark}"

    with st.expander(label, expanded=False):
        gid = g["id"]
        responses = db.get_group_responses(gid)
        questions = get_questions()

        for resp in responses:
            if resp["is_deleted"]:
                continue
            m = resp["member_number"]
            if g["group_size"] > 1:
                st.markdown(f"**メンバー {m}**"
                            + (" (同調フラグ)" if resp["conformity_flag"] else ""))

            ans_rows = db.get_response_answers(resp["id"])
            ans_map = {a["question_id"]: a for a in ans_rows}

            # 編集モードの判定
            edit_key = f"rv_edit_{gid}_{m}"
            editing = st.session_state.get(edit_key, False)

            for qid in get_question_ids():
                q = questions.get(qid)
                if q is None:
                    continue
                if qid.endswith("_other"):
                    continue

                a = ans_map.get(qid)
                if a is None:
                    continue

                if editing:
                    _render_edit_widget(qid, q, a, ans_map, m, gid)
                else:
                    _render_readonly(qid, q, a, ans_map)

            st.markdown("---")

            # 操作ボタン
            if editing:
                if st.button("変更を保存", key=f"rv_save_{gid}_{m}",
                             use_container_width=True, type="primary"):
                    _save_edits(ans_rows, qid_prefix=f"rve_{gid}_{m}")
                    st.session_state[edit_key] = False
                    st.rerun()
                if st.button("キャンセル", key=f"rv_cancel_{gid}_{m}",
                             use_container_width=True):
                    st.session_state[edit_key] = False
                    st.rerun()
            else:
                if st.button("修正", key=f"rv_btn_edit_{gid}_{m}",
                             use_container_width=True):
                    st.session_state[edit_key] = True
                    st.rerun()

        # グループ全体の操作
        st.markdown("---")
        if g["is_deleted"]:
            if st.button("復元する", key=f"rv_restore_{gid}",
                         use_container_width=True):
                db.restore_group(gid)
                st.rerun()
        else:
            if st.button("このグループを削除", key=f"rv_del_{gid}",
                         use_container_width=True):
                st.session_state[f"rv_confirm_{gid}"] = True
                st.rerun()
            if st.session_state.get(f"rv_confirm_{gid}"):
                st.warning("本当に削除しますか？（論理削除なので復元可能です）")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("はい、削除する", key=f"rv_yes_{gid}",
                                 use_container_width=True):
                        db.soft_delete_group(gid)
                        st.session_state[f"rv_confirm_{gid}"] = False
                        st.rerun()
                with c2:
                    if st.button("やめる", key=f"rv_no_{gid}",
                                 use_container_width=True):
                        st.session_state[f"rv_confirm_{gid}"] = False
                        st.rerun()
