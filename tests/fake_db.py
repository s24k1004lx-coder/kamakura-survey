"""テスト用のインメモリ版 lib.db（Supabase に接続せずに画面の動作確認をする）

使い方:
    from tests import fake_db
    fake_db.install()   # sys.modules["lib.db"] を差し替える
    ...AppTest で pages/1_input.py を実行...
    fake_db.STORE["saved"]  # save_survey に渡された内容
"""
import sys
import types
import uuid
from datetime import date, timedelta, timezone

STORE = {}


def reset():
    STORE.clear()
    STORE.update(saved=[], drafts={}, refusals=[], day_notes={})


def _mod():
    m = types.ModuleType("lib.db")

    def get_counts():
        return len(STORE["saved"]), sum(s["setup"]["group_size"] for s in STORE["saved"])

    def save_draft(group_data, payload):
        did = payload.get("draft_id") or str(uuid.uuid4())
        STORE["drafts"][did] = {"id": did, **group_data, "session_draft": payload,
                                "created_at": "2026-10-15T10:00:00+09:00"}
        return did

    def load_drafts():
        return list(STORE["drafts"].values())

    def delete_draft(did):
        STORE["drafts"].pop(did, None)

    def save_survey(setup, all_answers, conformity_flags, branches,
                    response_modes=None, stumble_flags=None):
        STORE["drafts"].pop(setup.get("draft_id"), None)
        STORE["saved"].append(dict(setup=setup, answers=all_answers,
                                   flags=conformity_flags, branches=branches,
                                   response_modes=response_modes,
                                   stumble_flags=stumble_flags))
        return str(uuid.uuid4())

    def add_refusal(location, survey_type):
        row = {"id": str(uuid.uuid4()), "location": location, "survey_type": survey_type}
        STORE["refusals"].append(row)
        return row

    def undo_last_refusal():
        return STORE["refusals"].pop() if STORE["refusals"] else None

    def get_today_contact_counts():
        answered = sum(1 for s in STORE["saved"] if s["setup"]["input_method"] == "field")
        return len(STORE["refusals"]), answered

    def today_jst():
        return date(2026, 10, 15)

    def get_day_note(d):
        return STORE["day_notes"].get(d.isoformat())

    def save_day_note(d, weather, crowd, note):
        STORE["day_notes"][d.isoformat()] = dict(survey_date=d.isoformat(), weather=weather,
                                                 crowd=crowd, note=note)

    def list_day_notes():
        return list(STORE["day_notes"].values())

    def load_all_for_aggregation():
        return STORE["dataset"]

    for f in [get_counts, save_draft, load_drafts, delete_draft, save_survey, add_refusal,
              undo_last_refusal, get_today_contact_counts, today_jst, get_day_note,
              save_day_note, list_day_notes, load_all_for_aggregation]:
        setattr(m, f.__name__, f)
    m.JST = timezone(timedelta(hours=9))
    m.FAKE = True
    return m


def _dataset(n_groups):
    """集計画面用のダミーデータ（乱数シード固定）。A6 の半分に分類結果を付ける。"""
    from tests.generate_dummy import build_dummy_dataset
    ds = build_dummy_dataset(n_groups, seed=42)
    cats = ["fun", "value", "few_places", "ending"]
    for i, a in enumerate(x for x in ds["answers"] if x["question_id"] == "A6"):
        if i % 2 == 0:
            ds["classifications"].append(dict(id=str(uuid.uuid4()), answer_id=a["id"],
                                              categories=[cats[i % len(cats)]],
                                              status="classified", classifier_id="classifier_1"))
    return ds


def install(n_groups=0):
    """n_groups > 0 なら集計用のダミーデータも用意する"""
    reset()
    STORE["dataset"] = _dataset(n_groups) if n_groups else dict(
        groups=[], responses=[], answers=[], classifications=[], refusals=[], day_notes=[])
    import lib
    m = _mod()
    sys.modules["lib.db"] = m
    lib.db = m
    return m
