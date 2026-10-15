"""回答入力画面の結合テスト（Streamlit AppTest ＋ インメモリDB）

実行: python -m unittest discover tests
"""
import os
import unittest

from streamlit.testing.v1 import AppTest

from tests import fake_db
from tests.drive_input import ROOT, run, _button

PAGE = os.path.join(ROOT, "pages", "1_input.py")


def _new_app():
    fake_db.install()
    return AppTest.from_file(PAGE, default_timeout=30).run()


class TestWizard(unittest.TestCase):
    def test_solo_keeps_all_answers(self):
        """1画面1設問でも、前の設問の回答が保存時まで残っている"""
        _, store = run(1)
        saved = store["saved"][0]
        ans = saved["answers"][1]
        for qid in ["Q1", "Q2", "Q3", "Q4", "Q4_name", "Q5", "Q5_2", "Q6", "C1", "C2", "C3", "Q7", "Q8"]:
            self.assertIn(qid, ans)
        self.assertEqual(saved["branches"][1], "A")
        self.assertNotIn("A4", ans)  # Q6=今も使っている なので A4 は対象外

    def test_group_keeps_all_members(self):
        _, store = run(3)
        saved = store["saved"][0]
        self.assertEqual(sorted(saved["answers"]), [1, 2, 3])
        for m in (1, 2, 3):
            self.assertIn("Q1", saved["answers"][m])
            self.assertIn("Q8", saved["answers"][m])

    def test_phase25_fields_are_saved(self):
        _, store = run(2, flag_first=True)
        saved = store["saved"][0]
        self.assertEqual(saved["stumble_flags"], {"Q1": "意味が伝わらず"})
        self.assertEqual(saved["response_modes"], {1: "interviewer", 2: "interviewer"})
        self.assertTrue(saved["setup"]["started_at"])


class TestCounter(unittest.TestCase):
    def _header(self, at):
        return next(m.value for m in at.markdown if "声かけ" in m.value)

    def test_refused_and_undo(self):
        at = _new_app()
        self.assertIn("声かけ 0件", self._header(at))
        at.button(key="cnt_refused").click().run()
        at.button(key="cnt_refused").click().run()
        self.assertIn("声かけ 2件 ／ 回答 0件 ／ 回答率 0.0%", self._header(at))
        at.button(key="cnt_undo").click().run()
        self.assertIn("声かけ 1件", self._header(at))
        self.assertEqual(fake_db.STORE["refusals"][0]["location"], "鎌倉駅東口")

    def test_refusal_uses_selected_location(self):
        at = _new_app()
        at.selectbox(key="su_loc").set_value("小町通り入口").run()
        at.radio(key="su_type").set_value("プレテスト").run()
        at.button(key="cnt_refused").click().run()
        self.assertEqual(fake_db.STORE["refusals"][-1],
                         {**fake_db.STORE["refusals"][-1],
                          "location": "小町通り入口", "survey_type": "pretest"})

    def test_answer_counts_up_and_setup_is_sticky(self):
        at, store = run(1)
        at.button[[b.label for b in at.button].index("次の回答者を入力")].click().run()
        self.assertIn("回答 1件", self._header(at))
        # 2人目以降も前回の調査地点などが初期値になっている
        self.assertEqual(at.selectbox(key="su_loc").value, store["saved"][0]["setup"]["location"])


class TestDayNote(unittest.TestCase):
    def test_save_day_note(self):
        at = _new_app()
        at.radio[[r.label for r in at.radio].index("天気")].set_value("雨")
        at.radio[[r.label for r in at.radio].index("混雑具合")].set_value("混んでいる")
        at.text_area[0].input("駅前は立ち止まってもらいにくい")
        _button(at, "メモを保存").click().run()
        note = fake_db.STORE["day_notes"]["2026-10-15"]
        self.assertEqual((note["weather"], note["crowd"], note["note"]),
                         ("雨", "混んでいる", "駅前は立ち止まってもらいにくい"))


if __name__ == "__main__":
    unittest.main()
