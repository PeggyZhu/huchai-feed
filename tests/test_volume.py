"""Volume-only scoring from the Beike deal counts.

Locked figures below are counts from data/prediction/ke_deals_raw.csv.
They are not prices and they are not filled in by hand.
"""

from __future__ import annotations

import datetime as dt
import shutil
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from huchai.build_site import build_site
from huchai.notices.score import score_community
from huchai.volume import (
    COMPLETE,
    assign_tier,
    build_document,
    count_months,
    dump_text,
    lookback_ends,
    metric_at,
    pct,
    render_backtest,
    write_volume_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def evidence(**overrides):
    row = {
        "小区": "示例",
        "区": "普陀区",
        "公告类型": "决定",
        "假阳性": None,
        "匹配": "贴边",
        "来源URL": "https://www.shanghai.gov.cn/gwk/search/content/abc",
        "来源日期": "2026-08-26",
        "文号": None,
        "项目名": "示例",
        "户数": 80,
        "套均面积": 60,
    }
    row.update(overrides)
    return row


def scored(*rows):
    return score_community(list(rows))


class VolumeRuleTests(unittest.TestCase):
    def test_percent_display_does_not_decide_the_threshold(self):
        self.assertEqual(pct(Fraction(1, 13)), "7.7%")
        self.assertEqual(pct(Fraction(11, 5)), "220.0%")
        self.assertEqual(pct(Fraction(-7, 16)), "-43.8%")
        self.assertEqual(pct(Fraction(2, 7)), "28.6%")
        self.assertLess(Fraction(1, 13), Fraction(8, 100))
        self.assertGreaterEqual(Fraction(1, 13), Fraction(5, 100))

    def test_lookback_is_twelve_month_ends_before_the_notice(self):
        ends = lookback_ends(dt.date(2026, 8, 26))
        self.assertEqual(ends[0], (2025, 8))
        self.assertEqual(ends[-1], (2026, 7))
        self.assertEqual(len(ends), 12)
        self.assertNotIn((2025, 7), ends)

    def test_notice_day_itself_is_excluded_and_same_day_rows_both_count(self):
        dates = [dt.date(2026, 8, 26), dt.date(2026, 8, 25), dt.date(2026, 8, 25)]
        self.assertEqual(count_months(dates, before=dt.date(2026, 8, 26)), {(2026, 8): 2})

    def test_uncovered_month_is_not_zero(self):
        counts = {(2025, 1): 1, (2024, 12): 1}
        row = metric_at(counts, (2025, 1), (2025, 2))
        self.assertEqual(row["套数"], None)
        self.assertEqual(row["状态"], "未覆盖")
        self.assertEqual(row["标签"], "未覆盖")
        self.assertEqual(row["量价分"], 0)

    def test_under_eight_is_insufficient_and_scores_zero(self):
        counts = {(2026, m): 2 for m in range(1, 13)}
        counts.update({(2025, m): 2 for m in range(1, 13)})
        row = metric_at(counts, (2025, 1), (2026, 6))
        self.assertEqual(row["套数"], 6)
        self.assertEqual(row["标签"], "样本不足")
        self.assertIsNone(row["环比"])
        self.assertEqual(row["量价分"], 0)
        self.assertFalse(row["低档"])

    def test_zero_base_does_not_invent_a_rate(self):
        counts = {(2026, 1): 3, (2026, 2): 3, (2026, 3): 2, (2025, 1): 4, (2025, 2): 4, (2025, 3): 4}
        row = metric_at(counts, (2025, 1), (2026, 3))
        self.assertEqual(row["套数"], 8)
        self.assertEqual(row["前3个月"]["套数"], 0)
        self.assertEqual(row["标签"], "比较段不足")
        self.assertIsNone(row["环比"])
        self.assertEqual(row["量价分"], 0)

    def test_lower_leg_sets_points(self):
        counts = {}
        for month, value in (
            ((2025, 1), 4),
            ((2025, 2), 4),
            ((2025, 3), 4),
            ((2026, 1), 3),
            ((2026, 2), 3),
            ((2026, 3), 4),
            ((2025, 10), 3),
            ((2025, 11), 3),
            ((2025, 12), 3),
        ):
            counts[month] = value
        row = metric_at(counts, (2025, 1), (2026, 3))
        self.assertEqual(row["套数"], 10)
        self.assertEqual(row["前3个月"]["套数"], 9)
        self.assertEqual(row["上年同期"]["套数"], 12)
        self.assertEqual(row["较低增速"], pct(Fraction(10 - 12, 12)))
        self.assertEqual(row["量价分"], 0)
        self.assertFalse(row["低档"])

    def test_partial_month_is_not_scored(self):
        counts = {(2026, 9): 4, (2026, 10): 4, (2026, 11): 4}
        row = metric_at(counts, (2024, 1), (2026, 11))
        self.assertEqual(row["状态"], "含未完月")
        self.assertEqual(row["量价分"], 0)
        self.assertFalse(row["低档"])

    def test_tier_keeps_program_gates(self):
        unknown = scored(evidence(户数=None, 套均面积=None))
        fired = {"中档": True, "低档": True, "标签": "可计算"}
        tier, reason = assign_tier(unknown, fired, block_volume=False)
        self.assertEqual(tier, "未分档")
        self.assertIn("硬过滤未知", reason)

        high = scored(
            evidence(匹配="程序内", 公告类型="两清", 来源日期="2026-06-01"),
            evidence(匹配="贴边", 公告类型="决定", 户数=None, 套均面积=None, 来源日期="2026-07-01"),
        )
        self.assertEqual(assign_tier(high, {"中档": False, "低档": False, "标签": "样本不足"}, block_volume=False)[0], "高")

        edge = scored(evidence())
        edge["硬过滤"] = "通过"
        self.assertEqual(assign_tier(edge, fired, block_volume=False)[0], "中")
        self.assertEqual(assign_tier(edge, {"中档": False, "低档": False, "标签": "样本不足"}, block_volume=False)[0], "未分档")
        blocked, blocked_reason = assign_tier(edge, fired, block_volume=True)
        self.assertEqual(blocked, "未分档")
        self.assertIn("口径", blocked_reason)

        inside = scored(evidence(匹配="程序内", 公告类型="征收范围"))
        self.assertEqual(assign_tier(inside, {"中档": False, "低档": True, "标签": "可计算"}, block_volume=False)[0], "低")
        consult = scored(evidence(匹配="程序内", 公告类型="征询"))
        self.assertIn("纯征询", assign_tier(consult, fired, block_volume=False)[1])
        excluded = scored(evidence(匹配="程序内", 公告类型="决定"))
        self.assertEqual(assign_tier(excluded, fired, block_volume=False)[0], "未分档")


class CollectedDealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = build_document(ROOT)

    def community(self, name):
        return next(row for row in self.document["小区"] if row["小区"] == name)

    def month(self, name, key):
        return next(row for row in self.community(name)["月度"] if row["月"] == key)

    def window(self, name, end):
        return next(row for row in self.community(name)["回看"]["月份"] if row["止于"] == end)

    def test_csv_is_counts_only(self):
        text = (ROOT / "data" / "prediction" / "ke_deals_raw.csv").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("xiaoqu,deal_date\n"))
        self.assertEqual(self.document["原始行数"], 164)
        self.assertNotIn("价格", text)
        self.assertEqual(text.count("\n"), 165)

    def test_lanling_windows_match_the_rows(self):
        self.assertEqual(self.month("兰岭园", "2026-03")["套数"], 7)
        self.assertEqual(self.month("兰岭园", "2025-08")["套数"], 0)
        self.assertEqual(self.month("兰岭园", "2026-08")["套数"], 2)
        self.assertEqual(self.community("兰岭园")["窗口外"], [{"月": "2024-12", "套数": 1}])
        self.assertTrue(all(row["月"] >= "2025-01" for row in self.community("兰岭园")["月度"]))
        march = self.window("兰岭园", "2026-03")
        self.assertEqual(march["套数"], 14)
        self.assertEqual(march["前3个月"]["套数"], 13)
        self.assertEqual(march["上年同期"]["套数"], 6)
        self.assertEqual(march["较低增速"], "7.7%")
        self.assertEqual(march["量价分"], 15)
        self.assertTrue(march["低档"])
        self.assertFalse(march["中档"])
        january = self.window("兰岭园", "2026-01")
        self.assertEqual(january["套数"], 16)
        self.assertEqual(january["前3个月"]["套数"], 5)
        self.assertEqual(january["上年同期"]["状态"], "未覆盖")
        self.assertIsNone(january["上年同期"]["套数"])
        self.assertFalse(january["低档"])
        self.assertIn("环比过8%", january["单腿"])
        six = self.community("兰岭园")["回看"]["六个月"]
        self.assertEqual((six["套数"], six["上年套数"]), (15, 16))
        self.assertEqual(self.community("兰岭园")["回看"]["公告当月之前"], ["2026-08-14"])
        self.assertEqual(self.community("兰岭园")["回看"]["公告当月及之后"], ["2026-08-29"])
        self.assertEqual(self.community("兰岭园")["当前"]["止于"], "2026-10")
        self.assertEqual(self.community("兰岭园")["当前"]["套数"], 4)
        self.assertEqual(self.community("兰岭园")["当前"]["标签"], "样本不足")
        self.assertEqual(self.community("兰岭园")["回看"]["低档月"], ["2026-03"])
        self.assertEqual(self.community("兰岭园")["回看"]["中档月"], [])

    def test_other_notice_communities_stay_under_the_sample_floor(self):
        for name in ("北梅园", "甘泉三村", "海洲丽园", "珠江香樟北园"):
            counts = [row["套数"] for row in self.community(name)["回看"]["月份"] if isinstance(row["套数"], int)]
            self.assertLess(max(counts), 8, name)
            self.assertFalse(self.community(name)["回看"]["低档"], name)
            self.assertFalse(self.community(name)["回看"]["中档"], name)
        self.assertEqual(self.month("海洲丽园", "2025-07")["套数"], 2)
        self.assertEqual(self.month("海洲丽园", "2025-07")["位置"], "公告当月")
        self.assertEqual(self.community("海洲丽园")["回看"]["公告当月之前"], [])
        self.assertEqual(self.community("海洲丽园")["回看"]["公告当月及之后"], ["2025-07-23", "2025-07-23"])
        self.assertIn("珠江香樟园", self.community("珠江香樟北园")["口径备注"])
        self.assertEqual(self.community("北梅园")["窗口外"], [{"月": "2024-02", "套数": 1}])

    def test_missing_searches_are_not_zeros_and_names_are_not_borrowed(self):
        caoyang = self.community("曹杨新村")
        self.assertEqual(caoyang["成交状态"], "无记录")
        self.assertEqual(caoyang["采集条数"], 0)
        self.assertEqual(caoyang["月度"], [])
        ganling = self.community("甘陵小区")
        self.assertEqual(ganling["成交状态"], "待核")
        self.assertEqual(ganling["采集条数"], 0)
        self.assertGreater(self.community("甘泉三村")["采集条数"], 0)
        shihua = self.community("实华公寓")
        self.assertEqual(sum(row["套数"] for row in shihua["月度"]), 0)
        self.assertEqual(shihua["当前"]["套数"], 0)
        self.assertEqual(shihua["当前"]["标签"], "样本不足")
        self.assertEqual(len(shihua["窗口外"]), 4)

    def test_public_tiers_stay_unranked_without_inventing_prices(self):
        self.assertEqual(len(self.document["小区"]), 13)
        self.assertTrue(all(row["档位"] == "未分档" for row in self.document["小区"]))
        self.assertEqual(self.document["更新日"], "2026-11-28")
        self.assertEqual(self.document["当前窗口"], "2026-10")
        keys = set(_keys(self.document["小区"]))
        for banned in ("价格", "挂牌价", "评估价", "成交价", "超额涨幅", "单价"):
            self.assertNotIn(banned, keys)
        self.assertIn("不是投资建议", self.document["免责声明"])
        self.assertIn("7.7%", self.document["结论"][1])
        self.assertIn("15 套", self.document["结论"][2])
        self.assertIn("一致", "".join(self.document["结论"]))

    def test_committed_artifacts_match_the_generator(self):
        self.assertEqual((ROOT / "site" / "tiers" / "data.json").read_text(encoding="utf-8"), dump_text(self.document))
        self.assertEqual(
            (ROOT / "samples" / "m2" / "volume_backtest.md").read_text(encoding="utf-8"),
            render_backtest(self.document),
        )

    def test_build_publishes_tiers_without_touching_fangdi(self):
        fangdi = (ROOT / "fangdi.json").read_bytes()
        out = Path(tempfile.mkdtemp(prefix="huchai-tiers-"))
        self.addCleanup(lambda: shutil.rmtree(out, ignore_errors=True))
        build_site(ROOT, out)
        self.assertEqual((out / "fangdi.json").read_bytes(), fangdi)
        self.assertEqual((ROOT / "fangdi.json").read_bytes(), fangdi)
        html = (out / "tiers" / "index.html").read_text(encoding="utf-8")
        self.assertIn("不是投资建议", html)
        self.assertNotIn('href="/', html)
        self.assertNotIn("src=\"/", html)
        self.assertEqual((out / "tiers" / "data.json").read_text(encoding="utf-8"), dump_text(self.document))
        self.assertFalse((out / "samples").exists())
        self.assertIn('href="tiers/"', (out / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(COMPLETE, (2026, 10))


class ArtifactWriteTests(unittest.TestCase):
    def test_writer_does_not_touch_fangdi(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copytree(ROOT / "samples", root / "samples")
            (root / "site" / "tiers").mkdir(parents=True)
            fangdi = root / "fangdi.json"
            fangdi.write_text("{}\n", encoding="utf-8")
            data_path, report_path = write_volume_artifacts(root)
            self.assertEqual(fangdi.read_text(encoding="utf-8"), "{}\n")
            self.assertTrue(data_path.is_file())
            self.assertTrue(report_path.is_file())
            self.assertIn("兰岭园", report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
