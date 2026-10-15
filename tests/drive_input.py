"""回答入力画面を AppTest で最後まで自動入力して、保存される内容を表示する（DBはモック）

実行: python tests/drive_input.py [グループ人数]
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from streamlit.testing.v1 import AppTest  # noqa: E402
from tests import fake_db  # noqa: E402


def _button(at, label):
    for b in at.button:
        if b.label == label:
            return b
    return None


def _fill_current(at):
    """表示中の設問ウィジェットを機械的に埋める（未回答のものだけ）"""
    for r in at.radio:
        if r.key and r.key.startswith("q_") and r.value is None:
            r.set_value(_first_value(r))
    cbs = [c for c in at.checkbox if c.key and c.key.startswith("q_")]
    members = {}
    for c in cbs:
        m = c.key.split("_m")[1].split("_")[0] if "_m" in c.key else "1"
        members.setdefault(m, []).append(c)
    for group in members.values():
        if not any(c.value for c in group):
            group[0].check()
    for t in at.text_area:
        if t.key and t.key.startswith("q_") and not t.value:
            t.input("テスト自由記述")


def _first_value(r):
    """radio のキー q_{qid}_m{n} から設問を引き、最初の選択肢の value を返す"""
    from lib.config_loader import get_questions
    qid = r.key[2:].rsplit("_m", 1)[0]
    return get_questions()[qid]["options"][0]["value"]


def run(group_size=1, flag_first=False):
    fake_db.install()
    at = AppTest.from_file(os.path.join(ROOT, "pages", "1_input.py"), default_timeout=30).run()
    if group_size > 1:
        at.radio(key="su_mode").set_value("グループ").run()
        at.slider(key="su_gs").set_value(group_size).run()
    _button(at, "入力開始").click().run()

    for step in range(60):
        if at.exception:
            raise RuntimeError(at.exception)
        save = _button(at, "保存する")
        if save:
            save.click().run()
            break
        if flag_first and step == 0 and len(at.toggle):
            at.toggle(key=next(t.key for t in at.toggle if t.key.startswith("flag_"))).set_value(True).run()
            at.text_input(key=next(t.key for t in at.text_input
                                   if t.key.startswith("flagmemo_"))).input("意味が伝わらず").run()
        _fill_current(at)
        at.run()
        _button(at, "次へ →").click().run()
        errs = [e.value for e in at.error]
        if errs:
            raise RuntimeError(f"step {step}: {errs}")
    if at.exception:
        raise RuntimeError(at.exception)
    return at, fake_db.STORE


if __name__ == "__main__":
    gs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    at, store = run(gs, flag_first=True)
    for s in store["saved"]:
        for m, ans in s["answers"].items():
            print(f"member {m}: branch={s['branches'][m]} answered={sorted(ans)}")
        print("response_modes:", s["response_modes"])
        print("stumble_flags:", s["stumble_flags"])
        print("started_at:", s["setup"].get("started_at"))
