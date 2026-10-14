"""Supabase データベース操作"""
import json
from datetime import datetime, timezone
import streamlit as st
from supabase import create_client


@st.cache_resource
def _get_client():
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])


def client():
    return _get_client()


# --- 件数 ---

def get_counts():
    """(グループ数, 回答者数) を返す"""
    c = client()
    g = (c.table("survey_groups").select("id", count="exact")
         .eq("is_deleted", False).is_("session_draft", "null").execute())
    r = (c.table("responses").select("id", count="exact")
         .eq("is_deleted", False).execute())
    return (g.count or 0), (r.count or 0)


# --- 下書き ---

def save_draft(group_data, draft_payload):
    """下書きを保存。新規なら INSERT、既存なら UPDATE。group_id を返す。"""
    c = client()
    draft_id = draft_payload.get("draft_id")
    row = {
        "location": group_data["location"],
        "survey_type": group_data["survey_type"],
        "input_method": group_data["input_method"],
        "group_size": group_data["group_size"],
        "session_draft": draft_payload,
    }
    if draft_id:
        c.table("survey_groups").update(row).eq("id", draft_id).execute()
        return draft_id
    result = c.table("survey_groups").insert(row).execute()
    return result.data[0]["id"]


def load_drafts():
    c = client()
    return (c.table("survey_groups").select("*")
            .eq("is_deleted", False)
            .not_.is_("session_draft", "null")
            .order("created_at", desc=True).execute()).data


def delete_draft(draft_id):
    client().table("survey_groups").delete().eq("id", draft_id).execute()


# --- 正式保存 ---

def save_survey(setup, all_answers, conformity_flags, branches):
    """
    グループ全体の回答を保存する。

    setup           : {location, survey_type, input_method, group_size, draft_id?}
    all_answers     : {member_num: {qid: {"value":...} | {"values":[...]}}}
    conformity_flags: {member_num: bool}
    branches        : {member_num: str|None}
    """
    c = client()
    draft_id = setup.get("draft_id")

    if draft_id:
        c.table("survey_groups").update({
            "session_draft": None,
            "location": setup["location"],
            "survey_type": setup["survey_type"],
            "input_method": setup["input_method"],
            "group_size": setup["group_size"],
        }).eq("id", draft_id).execute()
        group_id = draft_id
    else:
        res = c.table("survey_groups").insert({
            "location": setup["location"],
            "survey_type": setup["survey_type"],
            "input_method": setup["input_method"],
            "group_size": setup["group_size"],
        }).execute()
        group_id = res.data[0]["id"]

    _record_history("group", group_id, "create", None, setup)

    for m in sorted(all_answers.keys()):
        resp = c.table("responses").insert({
            "group_id": group_id,
            "member_number": m,
            "conformity_flag": conformity_flags.get(m, False),
            "branch": branches.get(m),
        }).execute()
        rid = resp.data[0]["id"]

        for qid, ans in all_answers[m].items():
            row = {"response_id": rid, "question_id": qid}
            if ans.get("value") is not None:
                row["value"] = str(ans["value"])
            if ans.get("values"):
                row["values"] = ans["values"]
            c.table("answers").insert(row).execute()

    return group_id


# --- 取得 ---

def get_recent_groups(limit=20):
    c = client()
    return (c.table("survey_groups").select("*")
            .is_("session_draft", "null")
            .order("created_at", desc=True).limit(limit).execute()).data


def get_group_responses(group_id):
    c = client()
    return (c.table("responses").select("*")
            .eq("group_id", group_id)
            .order("member_number").execute()).data


def get_response_answers(response_id):
    c = client()
    return (c.table("answers").select("*")
            .eq("response_id", response_id).execute()).data


# --- 修正・削除 ---

def soft_delete_group(group_id):
    c = client()
    now = datetime.now(timezone.utc).isoformat()
    old = c.table("survey_groups").select("*").eq("id", group_id).execute().data
    if old:
        _record_history("group", group_id, "delete", old[0], None)
    c.table("survey_groups").update({"is_deleted": True, "deleted_at": now}).eq("id", group_id).execute()
    c.table("responses").update({"is_deleted": True, "deleted_at": now}).eq("group_id", group_id).execute()


def restore_group(group_id):
    c = client()
    c.table("survey_groups").update({"is_deleted": False, "deleted_at": None}).eq("id", group_id).execute()
    c.table("responses").update({"is_deleted": False, "deleted_at": None}).eq("group_id", group_id).execute()
    _record_history("group", group_id, "restore", None, None)


def update_answer(answer_id, new_value=None, new_values=None):
    c = client()
    old = c.table("answers").select("*").eq("id", answer_id).execute().data
    upd = {}
    if new_value is not None:
        upd["value"] = str(new_value)
    if new_values is not None:
        upd["values"] = new_values
    if upd:
        if old:
            _record_history("answer", answer_id, "update", old[0], upd)
        c.table("answers").update(upd).eq("id", answer_id).execute()


# --- 変更履歴 ---

def _record_history(target_type, target_id, action, old_value, new_value):
    client().table("edit_history").insert({
        "target_type": target_type,
        "target_id": str(target_id),
        "action": action,
        "old_value": _safe(old_value),
        "new_value": _safe(new_value),
    }).execute()


def _safe(obj):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
