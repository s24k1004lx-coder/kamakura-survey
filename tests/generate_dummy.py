"""ダミーデータ生成スクリプト — ソロ・グループ混在の回答をDBに投入する"""
import random
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.config_loader import get_questions, get_question_ids, get_locations, should_show_question

# Supabase 直接操作（Streamlit なしで使うため secrets を手動読み込み）
import toml
from supabase import create_client

SECRETS_PATH = os.path.join(os.path.dirname(__file__), "..", ".streamlit", "secrets.toml")

def get_client():
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


def insert_group(client, location, survey_type, input_method, group_size,
                 all_answers, branches, conformity_flags):
    """1 グループ分をDBに保存"""
    g = client.table("survey_groups").insert({
        "location": location,
        "survey_type": survey_type,
        "input_method": input_method,
        "group_size": group_size,
    }).execute()
    gid = g.data[0]["id"]

    for m in sorted(all_answers.keys()):
        r = client.table("responses").insert({
            "group_id": gid,
            "member_number": m,
            "conformity_flag": conformity_flags.get(m, False),
            "branch": branches.get(m),
        }).execute()
        rid = r.data[0]["id"]

        for qid, ans in all_answers[m].items():
            row = {"response_id": rid, "question_id": qid}
            if "value" in ans:
                row["value"] = str(ans["value"])
            if "values" in ans:
                row["values"] = ans["values"]
            client.table("answers").insert(row).execute()

    return gid


def main():
    n_groups = int(sys.argv[1]) if len(sys.argv) > 1 else 15

    c = get_client()
    locations = get_locations()

    created = 0
    for i in range(n_groups):
        loc = random.choice(locations)
        stype = random.choice(["main", "main", "main", "pretest"])
        method = random.choice(["field", "field", "transcription"])

        # ソロ60%, グループ40%
        if random.random() < 0.6:
            gs = 1
        else:
            gs = random.randint(2, 4)

        # 分岐の指定: A, B, または None（ランダム）
        force = random.choice(["A", "B", None])

        all_ans = {}
        brs = {}
        flags = {}

        for m in range(1, gs + 1):
            ans, br = generate_one_member(force_branch=force)
            all_ans[m] = ans
            brs[m] = br
            flags[m] = (gs > 1 and random.random() < 0.15)

        gid = insert_group(c, loc, stype, method, gs, all_ans, brs, flags)
        created += 1
        print(f"[{created}/{n_groups}] group_id={gid}  size={gs}  branch={list(brs.values())}")

    print(f"\n完了: {created} グループを生成しました")


if __name__ == "__main__":
    main()
