"""lib/db.py の保存処理のテスト（インメモリの Supabase クライアントを使う）

実行: python -m unittest discover tests
"""
import unittest

from lib import db
from tests.fake_supabase import FakeClient

SETUP = {"location": "鎌倉駅東口", "survey_type": "pretest", "input_method": "field",
         "group_size": 2}
ANSWERS = {1: {"Q1": {"value": "kamakura"}}, 2: {"Q1": {"value": "overseas"}}}


class TestSaveWithDraft(unittest.TestCase):
    def setUp(self):
        self.fc = FakeClient()
        self._orig = db.client
        db.client = lambda: self.fc

    def tearDown(self):
        db.client = self._orig

    def _groups(self):
        return self.fc.db.get("survey_groups", [])

    def test_normal_flow(self):
        did = db.save_draft(SETUP, {"draft_id": None})
        gid = db.save_survey({**SETUP, "draft_id": did}, ANSWERS, {}, {1: None, 2: None})
        self.assertEqual(gid, did)
        self.assertEqual(len(self._groups()), 1)
        self.assertIsNone(self._groups()[0]["session_draft"])
        self.assertEqual(len(self.fc.db["responses"]), 2)

    def test_draft_discarded_then_restarted(self):
        """本番で起きた不具合: 下書きを「破棄」した後、古いIDのまま入力して保存すると失敗していた"""
        did = db.save_draft(SETUP, {"draft_id": None})
        db.delete_draft(did)
        did2 = db.save_draft(SETUP, {"draft_id": did})   # 古いIDのまま「入力開始」
        self.assertNotEqual(did2, did)
        self.assertTrue(any(g["id"] == did2 for g in self._groups()))
        gid = db.save_survey({**SETUP, "draft_id": did2}, ANSWERS, {}, {1: None, 2: None})
        self.assertEqual([r["group_id"] for r in self.fc.db["responses"]], [gid, gid])

    def test_save_survives_missing_draft(self):
        """保存時点で下書きが消えていても、新しいグループとして保存できる"""
        gid = db.save_survey({**SETUP, "draft_id": "deleted-draft"}, ANSWERS, {}, {1: None, 2: None})
        self.assertEqual(len(self._groups()), 1)
        self.assertEqual(self._groups()[0]["id"], gid)
        self.assertEqual(len(self.fc.db["answers"]), 2)


if __name__ == "__main__":
    unittest.main()
