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

    def test_unaware_gets_d_questions(self):
        """クルッポを知らない人（Q5=ない・Q6=使ったことはない）には D1・D2 が出る"""
        _, store = run(1, choices={"Q5": "no", "Q6": "never", "D1": "no"})
        saved = store["saved"][0]
        ans = saved["answers"][1]
        self.assertIsNone(saved["branches"][1])
        self.assertEqual(ans["D1"]["value"], "no")
        self.assertIn("D2", ans)
        self.assertNotIn("A1", ans)
        self.assertNotIn("B1", ans)

    def test_d2_skipped_when_willing(self):
        _, store = run(1, choices={"Q5": "no", "Q6": "never", "D1": "yes"})
        ans = store["saved"][0]["answers"][1]
        self.assertIn("D1", ans)
        self.assertNotIn("D2", ans)

    def test_aware_skips_d_questions(self):
        """Q5=ある なら Q6=使ったことはない でも分岐B に入り、D1 は出ない"""
        _, store = run(1, choices={"Q5": "yes", "Q6": "never"})
        saved = store["saved"][0]
        self.assertEqual(saved["branches"][1], "B")
        self.assertNotIn("D1", saved["answers"][1])

    def test_phase25_fields_are_saved(self):
        _, store = run(2, flag_first=True)
        saved = store["saved"][0]
        self.assertEqual(saved["stumble_flags"], {"Q1": "意味が伝わらず"})
        self.assertEqual(saved["response_modes"], {1: "interviewer", 2: "interviewer"})
        self.assertTrue(saved["setup"]["started_at"])


class TestCopyAll(unittest.TestCase):
    def test_copy_member1_on_every_question(self):
        """「全員同じ」でエラーにならず、メンバー1の回答が全員にコピーされる（単一・複数選択・自由記述）"""
        from tests.drive_input import _first_value
        fake_db.install()
        at = AppTest.from_file(PAGE, default_timeout=30).run()
        at.radio(key="su_mode").set_value("グループ").run()
        at.slider(key="su_gs").set_value(3).run()
        _button(at, "入力開始").click().run()
        for _ in range(60):
            self.assertFalse(at.exception, at.exception)
            if _button(at, "保存する"):
                _button(at, "保存する").click().run()
                break
            # メンバー1だけ入力してからコピーする（メンバー2・3は触らない）
            for r in at.radio:
                if r.key and r.key.startswith("q_") and r.key.endswith("_m1") and r.value is None:
                    r.set_value(_first_value(r))
            cbs = [c for c in at.checkbox if c.key and "_m1_" in c.key]
            if cbs and not any(c.value for c in cbs):
                cbs[0].check()
            for t in at.text_area:
                if t.key and t.key.endswith("_m1") and not t.value:
                    t.input("メンバー1の感想")
            at.run()
            copy = _button(at, "全員同じ（メンバー1をコピー）")
            if copy:
                copy.click().run()
                self.assertFalse(at.exception, at.exception)
                self.assertTrue(_button(at, "次へ →"), "コピー後に「次へ」が表示されていない")
            _button(at, "次へ →").click().run()
            # コピーされていない欄があれば「選択してください」等のエラーになる
            self.assertFalse([e.value for e in at.error])
        saved = fake_db.STORE["saved"][0]["answers"]
        self.assertEqual(saved[1], saved[2])
        self.assertEqual(saved[1], saved[3])
        self.assertEqual(saved[2].get("A6"), {"value": "メンバー1の感想"})


class TestDiscardDraft(unittest.TestCase):
    def test_back_to_setup_discard_then_restart(self):
        """「設定に戻る」→ その下書きを「破棄」→「入力開始」で、前の回答と下書きIDが残らない"""
        at = _new_app()
        at.radio(key="su_mode").set_value("グループ").run()
        at.slider(key="su_gs").set_value(2).run()
        _button(at, "入力開始").click().run()
        old_id = at.session_state["sv_draft_id"]
        at.radio(key="q_Q1_m1").set_value("kamakura").run()
        _button(at, "← 設定に戻る").click().run()
        _button(at, "破棄").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertNotIn(old_id, fake_db.STORE["drafts"])
        self.assertNotIn("q_Q1_m1", at.session_state)
        self.assertNotIn("sv_draft_id", at.session_state)
        _button(at, "入力開始").click().run()
        self.assertNotEqual(at.session_state["sv_draft_id"], old_id)
        self.assertIsNone(at.radio(key="q_Q1_m1").value)


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
