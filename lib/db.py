"""Supabase データベース操作"""
import json
from datetime import datetime, timedelta, timezone
import streamlit as st
from supabase import create_client


def _clean(s):
    """非ASCII文字を除去してクリーンな文字列にする"""
    return s.encode("ascii", "ignore").decode("ascii").strip()


@st.cache_resource
def _get_client():
    return create_client(_clean(st.secrets["supabase"]["url"]),
                         _clean(st.secrets["supabase"]["key"]))


def client():
    return _get_client()


# --- 日付（調査は日本時間で区切る） ---

JST = timezone(timedelta(hours=9))


def today_jst():
    return datetime.now(JST).date()


def _today_start_iso():
    """日本時間の今日 0:00 を ISO 文字列で返す"""
    d = today_jst()
    return datetime(d.year, d.month, d.day, tzinfo=JST).isoformat()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


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
        # 下書きが「破棄」などで消えていると UPDATE は0行で終わる（エラーにならない）。
        # その場合は新しい下書きとして作り直す
        if c.table("survey_groups").update(row).eq("id", draft_id).execute().data:
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

def duration_seconds(started_at_iso, saved_at):
    """入力開始〜保存の秒数。開始時刻が不明・不正なら None。"""
    if not started_at_iso:
        return None
    try:
        started = datetime.fromisoformat(started_at_iso)
    except ValueError:
        return None
    sec = int((saved_at - started).total_seconds())
    return sec if sec >= 0 else None


def save_survey(setup, all_answers, conformity_flags, branches,
                response_modes=None, stumble_flags=None):
    """
    グループ全体の回答を保存する。

    setup           : {location, survey_type, input_method, group_size,
                       started_at?, draft_id?}
    all_answers     : {member_num: {qid: {"value":...} | {"values":[...]}}}
    conformity_flags: {member_num: bool}
    branches        : {member_num: str|None}
    response_modes  : {member_num: "interviewer"|"self"}  回答方式
    stumble_flags   : {qid: memo}  つまずきフラグ（メモは空文字可）
    """
    c = client()
    draft_id = setup.get("draft_id")
    response_modes = response_modes or {}

    saved_at = datetime.now(timezone.utc)
    group_row = {
        "location": setup["location"],
        "survey_type": setup["survey_type"],
        "input_method": setup["input_method"],
        "group_size": setup["group_size"],
        "started_at": setup.get("started_at"),
        "saved_at": saved_at.isoformat(),
        "duration_sec": duration_seconds(setup.get("started_at"), saved_at),
        "stumble_flags": stumble_flags or {},
    }

    group_id = None
    if draft_id:
        upd = c.table("survey_groups").update({"session_draft": None, **group_row}) \
            .eq("id", draft_id).execute()
        if upd.data:
            group_id = draft_id
    if group_id is None:
        # 下書きがない、または消えていた場合は新しいグループとして保存する
        res = c.table("survey_groups").insert(group_row).execute()
        group_id = res.data[0]["id"]

    _record_history("group", group_id, "create", None, group_row)

    for m in sorted(all_answers.keys()):
        resp = c.table("responses").insert({
            "group_id": group_id,
            "member_number": m,
            "conformity_flag": conformity_flags.get(m, False),
            "branch": branches.get(m),
            "response_mode": response_modes.get(m),
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


# --- 声かけカウンター ---

def add_refusal(location, survey_type):
    """断られた記録を1件追加する"""
    res = client().table("refusals").insert({
        "location": location,
        "survey_type": survey_type,
    }).execute()
    row = res.data[0]
    _record_history("refusal", row["id"], "create", None, row)
    return row


def undo_last_refusal():
    """今日の最新の断り記録を論理削除する（押し間違い用）。取り消した行を返す。"""
    c = client()
    rows = (c.table("refusals").select("*")
            .eq("is_deleted", False)
            .gte("created_at", _today_start_iso())
            .order("created_at", desc=True).limit(1).execute()).data
    if not rows:
        return None
    row = rows[0]
    c.table("refusals").update({"is_deleted": True, "deleted_at": _now_iso()}) \
        .eq("id", row["id"]).execute()
    _record_history("refusal", row["id"], "delete", row, None)
    return row


def get_today_contact_counts():
    """
    今日（日本時間）の (断られた件数, 回答件数) を返す。
    回答件数は保存済みグループ数（声かけ1回 = 1組）。
    紙からの転記はその場の声かけではないので除外する。
    """
    c = client()
    start = _today_start_iso()
    ref = (c.table("refusals").select("id", count="exact")
           .eq("is_deleted", False).gte("created_at", start).execute())
    ans = (c.table("survey_groups").select("id", count="exact")
           .eq("is_deleted", False).is_("session_draft", "null")
           .eq("input_method", "field")
           .gte("created_at", start).execute())
    return (ref.count or 0), (ans.count or 0)


# --- 調査日メモ ---

def get_day_note(survey_date):
    rows = (client().table("survey_day_notes").select("*")
            .eq("survey_date", survey_date.isoformat()).execute()).data
    return rows[0] if rows else None


def save_day_note(survey_date, weather, crowd, note):
    """調査日メモを保存（その日の行があれば更新、なければ作成）"""
    c = client()
    old = get_day_note(survey_date)
    row = {"weather": weather, "crowd": crowd, "note": note,
           "updated_at": _now_iso()}
    if old:
        c.table("survey_day_notes").update(row).eq("id", old["id"]).execute()
        _record_history("day_note", old["id"], "update", old, row)
    else:
        res = c.table("survey_day_notes").insert(
            {"survey_date": survey_date.isoformat(), **row}).execute()
        _record_history("day_note", res.data[0]["id"], "create", None, res.data[0])


def list_day_notes():
    return (client().table("survey_day_notes").select("*")
            .order("survey_date", desc=True).execute()).data


# --- 集計用の全件取得 ---

def _fetch_all(build_query, page=1000):
    """Supabase は1回の取得が最大1000行なので、range でページングして全件取る"""
    out, start = [], 0
    while True:
        rows = build_query().range(start, start + page - 1).execute().data
        out.extend(rows)
        if len(rows) < page:
            return out
        start += page


def load_all_for_aggregation():
    """
    集計に必要な全データを取得する（削除済み・下書きは除外）。
    戻り値: dict(groups, responses, answers, classifications, refusals, day_notes)
    """
    c = client()
    groups = _fetch_all(lambda: c.table("survey_groups")
                        .select("id,created_at,location,survey_type,input_method,"
                                "group_size,started_at,saved_at,duration_sec,stumble_flags")
                        .eq("is_deleted", False).is_("session_draft", "null")
                        .order("id"))
    responses = _fetch_all(lambda: c.table("responses")
                           .select("id,group_id,member_number,conformity_flag,"
                                   "branch,response_mode")
                           .eq("is_deleted", False).order("id"))
    answers = _fetch_all(lambda: c.table("answers")
                         .select("id,response_id,question_id,value,values").order("id"))
    classifications = _fetch_all(lambda: c.table("classifications")
                                 .select("id,answer_id,categories,status,classifier_id")
                                 .order("id"))
    refusals = _fetch_all(lambda: c.table("refusals")
                          .select("id,created_at,location,survey_type")
                          .eq("is_deleted", False).order("id"))
    return dict(groups=groups, responses=responses, answers=answers,
                classifications=classifications, refusals=refusals,
                day_notes=list_day_notes())


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
