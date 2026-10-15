"""集計画面の結合テスト（Streamlit AppTest ＋ ダミーデータ）

実行: python -m unittest discover tests
"""
import os
import time
import unittest

from streamlit.testing.v1 import AppTest

from tests import fake_db
from tests.drive_input import ROOT

PAGE = os.path.join(ROOT, "pages", "3_aggregate.py")


def _run_page(n_groups=100, **widgets):
    fake_db.install(n_groups=n_groups)
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    for key, value in widgets.items():
        w = at.radio(key=key) if key == "ag_scope" else None
        if key == "ag_scope":
            w.set_value(value)
        elif key == "ag_stypes":
            at.multiselect(key=key).set_value(value)
        else:
            at.checkbox(key=key).set_value(value)
    at.run()
    start = time.perf_counter()
    next(b for b in at.button if b.label == "集計を実行").click().run()
    return at, time.perf_counter() - start


class TestAggregatePage(unittest.TestCase):
    def test_runs_without_error_and_fast_enough(self):
        at, sec = _run_page()
        self.assertFalse(at.exception, at.exception)
        heading = next(m.value for m in at.markdown if m.value.startswith("### 集計対象"))
        self.assertRegex(heading, r"\d+人（\d+グループ）")
        # 要件: n=100規模で3秒以内（AppTest はグラフ描画を含む全体の時間）
        self.assertLess(sec, 3, f"{sec:.1f}秒かかった")
        print(f"\n集計の所要時間: {sec:.2f}秒, {heading}")

    def test_independence_note_shown_for_all_but_not_for_representatives(self):
        note = "回答の独立性が完全には保証されない"
        at, _ = _run_page(ag_stypes=["main", "pretest"])
        self.assertTrue(any(note in c.value for c in at.caption))
        at, _ = _run_page(ag_scope="rep_first", ag_stypes=["main", "pretest"])
        self.assertFalse(at.exception, at.exception)
        self.assertFalse(any(note in c.value for c in at.caption))

    def test_empty_database(self):
        at, _ = _run_page(n_groups=0)
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(any("条件に合う回答がありません" in w.value for w in at.warning))

    def test_all_scopes_run(self):
        for scope in ["solo", "rep_random"]:
            at, _ = _run_page(ag_scope=scope, ag_excl_conf=True)
            self.assertFalse(at.exception, f"{scope}: {at.exception}")


if __name__ == "__main__":
    unittest.main()
