"""ダミーデータ生成スクリプト — ソロ・グループ混在の回答をDBに投入する"""
import random
import sys
import os
import uuid
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.config_loader import get_questions, get_question_ids, get_locations, should_show_question

# Supabase 直接操作（Streamlit なしで使うため secrets を手動読み込み）
SECRETS_PATH = os.path.join(os.path.dirname(__file__), "..", ".streamlit", "secrets.toml")

JST = timezone(timedelta(hours=9))


def get_client():
    import toml
    from supabase import create_client
    secrets = toml.load(SECRETS_PATH)
    return create_client(secrets["supabase"]["url"], secrets["supabase"]["key"])


# --- ランダム回答生成 ---

QUESTIONS = get_questions()

def random_answer(qid, q, branch):
    """設問に対するランダム回答を生成"""
    if q["type"] in ("single_choice", "scale"):
        opt = random.choice(q["options"])
        ans = {"value": opt["value"]}
        if q.get("has_other") and random.random() < 0.15:
            ans["value"] = "other"
            ans["other_text"] = f"ダミーその他_{qid}"
        return ans

    elif q["type"] == "multi_choice":
        max_sel = q.get("max_select", len(q["options"]))
        n = random.randint(1, min(max_sel, len(q["options"])))
        sel = random.sample(q["options"], n)
        vals = [o["value"] for o in sel]
        ans = {"values": vals}

        if q.get("has_other") and random.random() < 0.2:
            if len(vals) < max_sel:
                vals.append("other")
                ans["other_text"] = f"ダミー自由記述_{qid}"
        return ans

    elif q["type"] == "free_text":
        texts = {
            "Q4_name": ["クルッポ", "まちのコイン", "鎌倉コイン", "聞いたことある気がする"],
            "A6": [
                "面白かった。ポイントが貯まるのが楽しい",
                "チェックインが簡単で良かった",
                "使える場所が少なくて困った",
                "地元の人との交流ができてよかった",
                "終了するのが残念",
            ],
            "B2": [
                "特にない",
                "旅行中にアプリを使うのは面倒",
                "還元率が低そう",
                "現金やPayPayで十分",
                "",
            ],
        }
        pool = texts.get(qid, [f"テスト回答_{qid}"])
        return {"value": random.choice(pool)}

    return {}


def generate_one_member(force_branch=None):
    """1 人分の回答と分岐を生成"""
    answers = {}
    branch = None

    for qid in get_question_ids():
        q = QUESTIONS[qid]

        # Q6 で分岐を制御
        if qid == "Q6" and force_branch:
            if force_branch == "A":
                val = random.choice(["active", "lapsed"])
            elif force_branch == "B":
                val = random.choice(["installed_unused", "never"])
                # "never" で B になるには Q5=yes が必要
                if val == "never":
                    answers["Q5"] = {"value": "yes"}
            else:
                val = "never"
            answers[qid] = {"value": val}
            opt = next((o for o in q["options"] if o["value"] == val), None)
            if opt and "branch" in opt:
                branch = opt["branch"]
            elif opt and "branch_if" in opt:
                cond = opt["branch_if"]
                dep = answers.get(cond["question_id"], {}).get("value")
                if dep == cond["value"]:
                    branch = cond["branch"]
            continue

        if not should_show_question(qid, answers, branch):
            continue

        ans = random_answer(qid, q, branch)
        answers[qid] = ans

        # 分岐判定
        if q.get("determines_branch") and "value" in ans:
            opt = next((o for o in q["options"] if o["value"] == ans["value"]), None)
            if opt:
                if "branch" in opt:
                    branch = opt["branch"]
                elif "branch_if" in opt:
                    cond = opt["branch_if"]
                    dep = answers.get(cond["question_id"], {}).get("value")
                    if dep == cond["value"]:
                        branch = cond["branch"]

        # _other 用レコード
        if ans.get("other_text"):
            answers[f"{qid}_other"] = {"value": ans.pop("other_text")}

    return answers, branch


def build_dummy_dataset(n_groups=15, seed=None):
    """
    ダミーの調査データを、DBの行と同じ形の dict で作る（DBには書き込まない）。
    戻り値は db.load_all_for_aggregation() と同じ形:
    dict(groups, responses, answers, classifications, refusals, day_notes)
    """
    if seed is not None:
        random.seed(seed)
    locations = get_locations()
    qids = get_question_ids()
    days = [date(2026, 10, 24), date(2026, 10, 25), date(2026, 11, 1)]
    out = dict(groups=[], responses=[], answers=[], classifications=[], refusals=[],
               day_notes=[])

    for _ in range(n_groups):
        day = random.choice(days)
        t = datetime(day.year, day.month, day.day, random.randint(10, 16),
                     random.randint(0, 59), tzinfo=JST)
        loc = random.choice(locations)
        stype = random.choice(["main", "main", "main", "pretest"])
        method = random.choice(["field", "field", "field", "transcription"])
        gs = 1 if random.random() < 0.6 else random.randint(2, 4)   # ソロ60%, グループ40%
        force = random.choice(["A", "B", None])                     # 分岐の指定
        dur = random.randint(60, 150) + 40 * (gs - 1)
        stumbles = {}
        if random.random() < 0.3:
            qid = random.choice(["Q4", "Q5", "C1", "C3", "B1"])
            stumbles[qid] = random.choice(["", "意味が伝わらなかった", "選択肢で迷った"])

        gid = str(uuid.uuid4())
        out["groups"].append(dict(
            id=gid, created_at=t.isoformat(), location=loc, survey_type=stype,
            input_method=method, group_size=gs, started_at=t.isoformat(),
            saved_at=(t + timedelta(seconds=dur)).isoformat(), duration_sec=dur,
            stumble_flags=stumbles))
        mode = random.choice(["interviewer", "interviewer", "self"])

        for m in range(1, gs + 1):
            ans, br = generate_one_member(force_branch=force)
            rid = str(uuid.uuid4())
            out["responses"].append(dict(
                id=rid, group_id=gid, member_number=m,
                conformity_flag=(gs > 1 and random.random() < 0.15),
                branch=br, response_mode=mode))
            for qid in sorted(ans, key=lambda k: qids.index(k.replace("_other", ""))
                              if k.replace("_other", "") in qids else 99):
                a = ans[qid]
                out["answers"].append(dict(
                    id=str(uuid.uuid4()), response_id=rid, question_id=qid,
                    value=str(a["value"]) if "value" in a else None,
                    values=a.get("values")))

        # 回答してくれた組の前後に、断られた声かけを0〜2件
        if method == "field":
            for _ in range(random.choice([0, 0, 1, 1, 2])):
                rt = t - timedelta(minutes=random.randint(1, 20))
                out["refusals"].append(dict(id=str(uuid.uuid4()), created_at=rt.isoformat(),
                                            location=loc, survey_type=stype))

    out["day_notes"] = [
        dict(survey_date="2026-10-24", weather="晴れ", crowd="混んでいる",
             note="午後から団体客が増えた"),
        dict(survey_date="2026-10-25", weather="くもり", crowd="ふつう",
             note="駅前は立ち止まってもらいにくい"),
    ]
    return out


def insert_dataset(client, ds):
    """build_dummy_dataset() の結果を Supabase に書き込む"""
    gid_map, rid_map = {}, {}
    for g in ds["groups"]:
        row = {k: v for k, v in g.items() if k != "id"}
        gid_map[g["id"]] = client.table("survey_groups").insert(row).execute().data[0]["id"]
    for r in ds["responses"]:
        row = {k: v for k, v in r.items() if k != "id"}
        row["group_id"] = gid_map[r["group_id"]]
        rid_map[r["id"]] = client.table("responses").insert(row).execute().data[0]["id"]
    for a in ds["answers"]:
        row = {"response_id": rid_map[a["response_id"]], "question_id": a["question_id"]}
        if a["value"] is not None:
            row["value"] = a["value"]
        if a["values"]:
            row["values"] = a["values"]
        client.table("answers").insert(row).execute()
    for x in ds["refusals"]:
        client.table("refusals").insert({k: v for k, v in x.items() if k != "id"}).execute()


def main():
    n_groups = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    ds = build_dummy_dataset(n_groups)
    insert_dataset(get_client(), ds)
    print(f"完了: {len(ds['groups'])} グループ / {len(ds['responses'])} 人 / "
          f"断られた {len(ds['refusals'])} 件を生成しました")


if __name__ == "__main__":
    main()
