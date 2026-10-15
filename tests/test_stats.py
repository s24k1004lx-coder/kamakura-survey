"""集計・検定ロジックの単体テスト

実行: python -m unittest discover tests
"""
import unittest

import numpy as np
import pandas as pd
from scipy import stats as sps

from lib import stats

# テスト用の小さな設問定義（実際の questions.yaml と同じ形）
Q = {
    "Q1": {"text": "居住地", "type": "single_choice", "options": [
        {"label": "鎌倉市内", "value": "kamakura", "tag": "resident"},
        {"label": "県外", "value": "other_pref"}]},
    "Q6": {"text": "利用経験", "type": "single_choice", "options": [
        {"label": "使っている", "value": "active"}, {"label": "使ったことはない", "value": "never"}]},
    "B1": {"text": "理由", "type": "multi_choice", "has_other": True, "options": [
        {"label": "面倒", "value": "trouble"}, {"label": "不明", "value": "unclear"}]},
    "A6": {"text": "感想", "type": "free_text"},
}


def _data():
    """
    g1: 一人客（県外, active）
    g2: 3人グループ（m1: 県外 never, m2: 鎌倉市内 never 同調フラグ, m3: 県外 active）
    g3: 一人客・プレテスト
    """
    groups = [
        dict(id="g1", created_at="2026-10-20T01:00:00+00:00", location="駅", survey_type="main",
             input_method="field", group_size=1, duration_sec=60, stumble_flags={"Q6": "迷った"}),
        dict(id="g2", created_at="2026-10-20T02:30:00+00:00", location="八幡宮", survey_type="main",
             input_method="field", group_size=3, duration_sec=200, stumble_flags={"Q6": "", "Q1": ""}),
        dict(id="g3", created_at="2026-10-19T03:00:00+00:00", location="駅", survey_type="pretest",
             input_method="transcription", group_size=1, duration_sec=999, stumble_flags={}),
    ]
    responses = [
        dict(id="r1", group_id="g1", member_number=1, conformity_flag=False, branch="A",
             response_mode="interviewer"),
        dict(id="r2", group_id="g2", member_number=1, conformity_flag=False, branch=None,
             response_mode="interviewer"),
        dict(id="r3", group_id="g2", member_number=2, conformity_flag=True, branch=None,
             response_mode="self"),
        dict(id="r4", group_id="g2", member_number=3, conformity_flag=False, branch="A",
             response_mode="interviewer"),
        dict(id="r5", group_id="g3", member_number=1, conformity_flag=False, branch="B",
             response_mode=None),
    ]
    answers = [
        dict(id="a1", response_id="r1", question_id="Q1", value="other_pref", values=None),
        dict(id="a2", response_id="r1", question_id="Q6", value="active", values=None),
        dict(id="a3", response_id="r2", question_id="Q1", value="other_pref", values=None),
        dict(id="a4", response_id="r2", question_id="Q6", value="never", values=None),
        dict(id="a5", response_id="r3", question_id="Q1", value="kamakura", values=None),
        dict(id="a6", response_id="r3", question_id="Q6", value="never", values=None),
        dict(id="a7", response_id="r4", question_id="Q1", value="other_pref", values=None),
        dict(id="a8", response_id="r4", question_id="Q6", value="active", values=None),
        dict(id="a9", response_id="r5", question_id="Q1", value="other_pref", values=None),
        dict(id="a10", response_id="r5", question_id="B1", value=None, values=["trouble", "other"]),
        dict(id="a11", response_id="r5", question_id="B1_other", value="高い", values=None),
        dict(id="a12", response_id="r1", question_id="A6", value="楽しい", values=None),
        dict(id="a13", response_id="r4", question_id="A6", value="店が少ない", values=None),
    ]
    refusals = [
        dict(id="x1", created_at="2026-10-20T01:10:00+00:00", location="駅", survey_type="main"),
        dict(id="x2", created_at="2026-10-20T01:20:00+00:00", location="駅", survey_type="main"),
        dict(id="x3", created_at="2026-10-20T05:00:00+00:00", location="八幡宮", survey_type="main"),
    ]
    classifications = [
        dict(id="c1", answer_id="a12", categories=["fun"], status="classified",
             classifier_id="classifier_1"),
    ]
    return dict(groups=groups, responses=responses, answers=answers, refusals=refusals,
                classifications=classifications, day_notes=[])


def _df():
    d = _data()
    return stats.build_respondents(d["groups"], d["responses"], d["answers"], Q)


class TestBuild(unittest.TestCase):
    def test_wide_format(self):
        df = _df()
        self.assertEqual(len(df), 5)
        r5 = df[df["response_id"] == "r5"].iloc[0]
        self.assertEqual(r5["B1"], ["trouble", "other"])
        self.assertEqual(r5["B1_other"], "高い")
        self.assertTrue(pd.isna(df[df["response_id"] == "r1"].iloc[0]["B1"]))


class TestFilter(unittest.TestCase):
    def test_survey_type(self):
        self.assertEqual(len(stats.filter_respondents(_df(), Q, survey_types=("main",)).df), 4)
        self.assertEqual(len(stats.filter_respondents(_df(), Q, survey_types=("main", "pretest")).df), 5)

    def test_exclude_residents(self):
        r = stats.filter_respondents(_df(), Q, exclude_residents=True)
        self.assertNotIn("r3", set(r.df["response_id"]))
        self.assertIn("住民", r.notes[0])

    def test_exclude_conformity(self):
        r = stats.filter_respondents(_df(), Q, exclude_conformity=True)
        self.assertEqual(sorted(r.df["response_id"]), ["r1", "r2", "r4"])

    def test_solo(self):
        r = stats.filter_respondents(_df(), Q, scope="solo")
        self.assertEqual(list(r.df["response_id"]), ["r1"])

    def test_rep_first(self):
        r = stats.filter_respondents(_df(), Q, scope="rep_first")
        self.assertEqual(sorted(r.df["response_id"]), ["r1", "r2"])

    def test_rep_first_after_member1_excluded(self):
        # メンバー1が除外されたら、残っている最小番号が代表になる
        df = _df()
        df.loc[df["response_id"] == "r2", "conformity_flag"] = True
        r = stats.filter_respondents(df, Q, scope="rep_first", exclude_conformity=True)
        self.assertEqual(sorted(r.df["response_id"]), ["r1", "r4"])

    def test_rep_random_is_reproducible(self):
        a = stats.filter_respondents(_df(), Q, scope="rep_random", seed=7).df["response_id"].tolist()
        b = stats.filter_respondents(_df(), Q, scope="rep_random", seed=7).df["response_id"].tolist()
        self.assertEqual(a, b)
        self.assertEqual(len(a), 2)
        picks = {stats.filter_respondents(_df(), Q, scope="rep_random", seed=s)
                 .df.query("group_id == 'g2'")["response_id"].iloc[0] for s in range(30)}
        self.assertGreater(len(picks), 1)  # シードを変えれば選ばれる人も変わる

    def test_group_member_detection(self):
        self.assertTrue(stats.includes_group_members(_df()))
        self.assertFalse(stats.includes_group_members(
            stats.filter_respondents(_df(), Q, scope="rep_first").df))


class TestTally(unittest.TestCase):
    def test_single(self):
        df = stats.filter_respondents(_df(), Q).df
        t, n = stats.tally(df, "Q6", Q["Q6"])
        self.assertEqual(n, 4)
        self.assertEqual(t["度数"].tolist(), [2, 2])
        self.assertEqual(t["割合(%)"].tolist(), [50.0, 50.0])

    def test_multi_counts_people_and_keeps_zero_rows(self):
        df = stats.filter_respondents(_df(), Q, survey_types=("pretest",)).df
        t, n = stats.tally(df, "B1", Q["B1"])
        self.assertEqual(n, 1)
        self.assertEqual(t["選択肢"].tolist(), ["面倒", "不明", "その他"])
        self.assertEqual(t["度数"].tolist(), [1, 0, 1])
        self.assertEqual(t["割合(%)"].tolist(), [100.0, 0.0, 100.0])

    def test_group_sizes(self):
        t = stats.group_size_distribution(stats.filter_respondents(_df(), Q).df)
        self.assertEqual(t["グループ数"].tolist(), [1, 1])
        self.assertEqual(t["回答者数"].tolist(), [1, 3])


class TestIndependence(unittest.TestCase):
    def test_chi_square_when_expected_large(self):
        t = pd.DataFrame([[30, 20], [15, 35]])
        r = stats.independence_test(t)
        self.assertTrue(r.method.startswith("カイ二乗検定"))
        expect = sps.chi2_contingency(np.array([[30, 20], [15, 35]]))
        self.assertAlmostEqual(r.p_value, expect.pvalue)
        self.assertEqual(r.dof, 1)

    def test_switches_to_fisher_2x2(self):
        t = pd.DataFrame([[8, 2], [1, 5]])
        r = stats.independence_test(t)
        self.assertEqual(r.method, "フィッシャーの正確確率検定")
        self.assertAlmostEqual(r.p_value, sps.fisher_exact([[8, 2], [1, 5]]).pvalue)
        self.assertIn("切替", r.note)

    def test_fisher_rxc_is_deterministic(self):
        t = pd.DataFrame([[3, 1, 2], [1, 4, 0], [2, 2, 5]])
        a, b = stats.independence_test(t), stats.independence_test(t)
        self.assertIn("R×C", a.method)
        self.assertEqual(a.p_value, b.p_value)

    def test_degenerate_table(self):
        r = stats.independence_test(pd.DataFrame([[5, 3], [0, 0]]))
        self.assertIsNone(r.p_value)
        self.assertIn("検定不可", r.summary())

    def test_crosstab_labels_and_order(self):
        df = stats.filter_respondents(_df(), Q).df
        t = stats.crosstab(df, "Q1", Q["Q1"], "Q6", Q["Q6"])
        self.assertEqual(list(t.index), ["鎌倉市内", "県外"])
        self.assertEqual(list(t.columns), ["使っている", "使ったことはない"])
        self.assertEqual(t.values.tolist(), [[0, 1], [2, 1]])


class TestRecords(unittest.TestCase):
    def test_duration_excludes_transcription(self):
        d = _data()
        t = stats.duration_summary(d["groups"], ("main", "pretest"))
        whole = t[t["区分"] == "全体"].iloc[0]
        self.assertEqual(whole["件数"], 2)
        self.assertEqual(whole["平均(秒)"], 130.0)
        self.assertEqual(whole["中央値(秒)"], 130.0)
        self.assertEqual(whole["最大(秒)"], 200)

    def test_stumble_ranking(self):
        t = stats.stumble_ranking(_data()["groups"], ("main",), Q)
        self.assertEqual(t["設問ID"].tolist(), ["Q6", "Q1"])
        self.assertEqual(t["件数"].tolist(), [2, 1])
        self.assertEqual(t.iloc[0]["メモ"], "迷った")

    def test_contact_by_location(self):
        d = _data()
        t = stats.contact_summary(d["refusals"], d["groups"], ("main",), "location")
        row = t.set_index("調査地点").loc["駅"]
        self.assertEqual((row["回答"], row["断り"], row["声かけ"]), (1, 2, 3))
        total = t.set_index("調査地点").loc["合計"]
        self.assertEqual((total["声かけ"], total["回答率(%)"]), (5, 40.0))

    def test_contact_by_hour_uses_jst(self):
        d = _data()
        t = stats.contact_summary(d["refusals"], d["groups"], ("main",), "hour")
        self.assertIn("10時台", t["時間帯"].tolist())  # 01:00 UTC = 10:00 JST

    def test_classification_summary(self):
        d = _data()
        df = stats.filter_respondents(_df(), Q).df
        cb = {"categories": [{"code": "fun", "label": "楽しい"}, {"code": "few", "label": "少ない"}]}
        t, counts = stats.classification_summary(df, d["answers"], d["classifications"], "A6", cb)
        self.assertEqual(t["件数"].tolist(), [1, 0])
        self.assertEqual(counts["記述あり"], 2)
        self.assertEqual(counts["未分類"], 1)


class TestRunAggregation(unittest.TestCase):
    def test_runs_end_to_end_and_is_deterministic(self):
        cfg = {"cross_tabs": [{"question_id": "Q1", "label": "居住地別"}],
               "awareness_comparison": {}}
        kw = dict(survey_types=("main",), exclude_residents=False, scope="all", seed=1,
                  exclude_conformity=False, target_qids=["Q6"])
        a = stats.run_aggregation(_data(), Q, cfg, {}, **kw)
        b = stats.run_aggregation(_data(), Q, cfg, {}, **kw)
        self.assertEqual(a["n"], 4)
        self.assertTrue(a["has_group_members"])
        self.assertEqual(len(a["cross"]), 1)
        self.assertEqual(a["sensitivity_n"], (4, 2))
        pd.testing.assert_frame_equal(a["sensitivity"], b["sensitivity"])

    def test_empty_data(self):
        empty = dict(groups=[], responses=[], answers=[], refusals=[], classifications=[],
                     day_notes=[])
        r = stats.run_aggregation(empty, Q, {"cross_tabs": [{"question_id": "Q1", "label": "x"}]},
                                  {}, survey_types=("main",), exclude_residents=True, scope="all",
                                  seed=0, exclude_conformity=False, target_qids=["Q6"])
        self.assertEqual(r["n"], 0)


if __name__ == "__main__":
    unittest.main()
