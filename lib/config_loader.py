"""設問YAML・コードブックの読み込みと設問ロジック"""
import yaml
from pathlib import Path
import streamlit as st

CONFIG_DIR = Path(__file__).parent.parent / "config"


@st.cache_data(ttl=60)
def _load_yaml(filename):
    """YAMLファイルを読み込んでキャッシュする（60秒でリフレッシュ）"""
    path = CONFIG_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_questions_config():
    return _load_yaml("questions.yaml")


def load_codebook():
    return _load_yaml("codebook.yaml")


def get_questions():
    """設問の辞書を返す（Python 3.7+ なので挿入順を保持）"""
    return load_questions_config()["questions"]


def get_question_ids():
    return list(get_questions().keys())


def get_locations():
    return load_questions_config().get("locations", [])


def get_aggregation_config():
    return load_questions_config().get("aggregation", {})


def should_show_question(qid, member_answers, member_branch):
    """
    メンバーの回答と分岐に基づいて設問を表示するか判定する。

    qid            : 設問ID
    member_answers : {question_id: {"value": ...}} 形式の回答辞書
    member_branch  : "A" / "B" / None
    """
    q = get_questions()[qid]

    # 設問が特定分岐に属していて、メンバーの分岐と異なるなら非表示
    if "branch" in q:
        if member_branch is None or q["branch"] != member_branch:
            return False

    # 表示条件つき設問: 依存設問の回答が条件値と一致しなければ非表示
    if "show_if" in q:
        cond = q["show_if"]
        actual = member_answers.get(cond["question_id"], {}).get("value")
        if actual != cond["value"]:
            return False

    return True


def determine_branch(member_answers):
    """分岐決定設問の回答から分岐先 ("A"/"B") を返す。未回答なら None。"""
    for qid, q in get_questions().items():
        if not q.get("determines_branch"):
            continue
        value = member_answers.get(qid, {}).get("value")
        if value is None:
            return None
        for opt in q["options"]:
            if opt["value"] == value and "branch" in opt:
                return opt["branch"]
    return None


def get_option_label(qid, value):
    """選択肢の value をラベルに変換する"""
    q = get_questions().get(qid)
    if q and "options" in q:
        for opt in q["options"]:
            if opt["value"] == value:
                return opt["label"]
    return str(value)
