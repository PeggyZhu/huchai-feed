"""M2 notice parsing, matching, and 程序 scoring.

Figures in this file are fixtures for the rules. They are not observations
and are not written under data/prediction.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import validate_prediction as prediction  # noqa: E402
from huchai.notices.collect import collect_notices, evidence_from_notice
from huchai.notices.http import FetchError, assert_not_fangdi
from huchai.notices.parse import (
    DISTRICTS,
    analyze_notice,
    extract_addresses,
    link_lanes,
)
from huchai.notices.report import assert_private_output, build_sample, render_markdown, write_sample
from huchai.notices.run import run_notices
from huchai.notices.score import hard_filter, score_community


ROOT = Path(__file__).resolve().parents[1]

YANGPU = """
上海市杨浦区人民政府房屋征收决定
杨府房征〔2025〕1号
房屋征收范围：东至隆昌路，南至河间路，西至珠江香樟北园，北至长阳路。
具体门牌号：长阳路2310弄（全弄）、2320号-2350号（双号）；隆昌路541弄（全弄）。
"""

CONSULT = """
静安区青云路旧城区改建意愿征询结果公告
发布日期：2025-06-01
甘陵小区旧城区改建意愿征询。
具体门牌号：青云路345弄1号、2号。
愿意改建522户。约80户不另计。套均面积约55平方米。
"""

PARTIAL = """
关于东安一、二村部分房屋征收范围的批复
发布日期：2025-04-02
房屋征收范围：东安一村部分、东安二村部分。
具体门牌号：东安路10弄1号。
"""


def evidence(**overrides):
    row = {
        "小区": "珠江香樟北园",
        "区": "杨浦区",
        "公告类型": "决定",
        "假阳性": None,
        "匹配": "贴边",
        "置信度": "0.85",
        "原始地址": "西至珠江香樟北园",
        "来源URL": "https://www.shanghai.gov.cn/gwk/search/content/abc",
        "来源日期": "2025-05-19",
        "文号": "杨府房征〔2025〕1号",
        "项目名": "136街坊",
        "户数": None,
        "户数原文": None,
        "套均面积": None,
        "套均原文": None,
        "口径": "程序状态",
    }
    row.update(overrides)
    return row


class ParseTests(unittest.TestCase):
    def test_districts_match_the_ledger(self):
        self.assertEqual(list(DISTRICTS), prediction.DISTRICTS)

    def test_decision_splits_lane_door_and_boundary_name(self):
        notice = analyze_notice(
            title="上海市杨浦区人民政府房屋征收决定（136街坊）",
            text=YANGPU,
            url="https://www.shanghai.gov.cn/gwk/search/content/abc",
            published="2025-05-19 08:00:00",
            district="杨浦区人民政府",
        )
        self.assertIsNotNone(notice)
        self.assertEqual(notice["区"], "杨浦区")
        self.assertEqual(notice["公告类型"], "决定")
        self.assertEqual(notice["文号"], "杨府房征〔2025〕1号")
        self.assertEqual(notice["来源日期"], "2025-05-19")
        lanes = {(item["路"], item["弄"], item["全弄"]) for item in notice["地址"]}
        self.assertIn(("长阳路", "2310", True), lanes)
        self.assertIn(("隆昌路", "541", True), lanes)
        door = next(item for item in notice["地址"] if item["路"] == "长阳路" and item["弄"] is None)
        self.assertIn("2320号-2350号", door["原文"])
        self.assertEqual(notice["匹配"], [
            {"小区": "珠江香樟北园", "匹配": "贴边", "置信度": "0.85", "原始地址": "珠江香樟北园"},
        ])

    def test_consultation_keeps_an_exact_household_and_drops_approx(self):
        notice = analyze_notice(
            title="静安区甘陵小区旧城区改建意愿征询结果公告",
            text=CONSULT,
            url="https://www.jingan.gov.cn/notice/1",
            district="静安区",
        )
        self.assertEqual(notice["公告类型"], "征询")
        self.assertEqual(notice["户数"], 522)
        self.assertIsNone(notice["套均面积"])
        kinds = {row["小区"]: row["匹配"] for row in notice["匹配"]}
        self.assertEqual(kinds["甘陵小区"], "程序内")

    def test_partial_and_split_village_names(self):
        notice = analyze_notice(
            title="关于东安一、二村部分房屋征收范围的批复",
            text=PARTIAL,
            url="https://www.putuo.gov.cn/notice/2",
            district="普陀区",
        )
        self.assertEqual(notice["公告类型"], "征收范围")
        kinds = {row["小区"]: row["匹配"] for row in notice["匹配"]}
        self.assertEqual(kinds["东安一村"], "部分覆盖")
        self.assertEqual(kinds["东安二村"], "部分覆盖")

    def test_false_positive_is_not_a_demolition_signal(self):
        notice = analyze_notice(
            title="关于茶陵路小区旧改屋面改造项目的通知",
            text="发布日期：2025-03-01\n茶陵路小区屋面及相关设施改造。具体门牌号：茶陵路195弄2号。",
            url="https://www.xuhui.gov.cn/notice/3",
            district="徐汇区",
        )
        self.assertEqual(notice["假阳性"], "成套改造")
        rows = evidence_from_notice(notice)
        scored = score_community(rows)
        self.assertIsNone(scored["程序"])
        self.assertIsNone(scored["档位"])
        self.assertIn("假阳性", scored["档位说明"])

    def test_lane_link_uses_only_one_same_district_pair(self):
        named = analyze_notice(
            title="甘陵小区房屋征收范围确认",
            text="发布日期：2025-01-02\n甘陵小区。具体门牌号：兰溪路248弄2号。",
            url="https://www.putuo.gov.cn/a",
            district="普陀区",
        )
        bare = analyze_notice(
            title="兰溪路地块房屋征收决定",
            text="发布日期：2025-08-01\n具体门牌号：兰溪路248弄3号。",
            url="https://www.putuo.gov.cn/b",
            district="普陀区",
        )
        link_lanes([named, bare])
        self.assertEqual(bare["匹配"][0]["小区"], "甘陵小区")
        self.assertEqual(bare["匹配"][0]["置信度"], "0.60")
        self.assertEqual(bare["匹配"][0]["匹配"], "程序内")

    def test_boilerplate_prefix_is_removed_and_resettlement_names_are_not_matches(self):
        text = """
        房屋征收范围：原则同意曹杨新村（北梅园地块、兰岭园地块）列入改建范围。
        东至曹杨三村，西至曹杨公寓。
        具体门牌号：兰溪路248弄1号。
        补偿方案里的安置房源：明珠新苑，朱泾镇金南街801弄。
        """
        notice = analyze_notice(
            title="关于同意曹杨新村地块房屋征收范围的批复",
            text=text,
            url="https://www.shanghai.gov.cn/gwk/search/content/caoyang",
            published="2026-08-26",
            district="普陀区",
        )
        names = {row["小区"]: row["匹配"] for row in notice["匹配"]}
        self.assertEqual(names["曹杨新村"], "程序内")
        self.assertEqual(names["北梅园"], "程序内")
        self.assertEqual(names["兰岭园"], "程序内")
        self.assertEqual(names["曹杨三村"], "贴边")
        self.assertEqual(names["曹杨公寓"], "贴边")
        self.assertNotIn("明珠新苑", names)
        self.assertNotIn("原则同意曹杨新村", names)

    def test_short_decision_title_still_parses(self):
        notice = analyze_notice(
            title="136街坊征收决定",
            text="房屋征收范围：西至珠江香樟北园。具体门牌号：长阳路2310弄（全弄）。",
            url="https://www.shyp.gov.cn/zhengwu/notice.html",
            published="2025-05-19",
            district="杨浦区",
        )
        self.assertEqual(notice["公告类型"], "决定")
        self.assertEqual(notice["匹配"][0]["小区"], "珠江香樟北园")
        self.assertEqual(notice["匹配"][0]["匹配"], "贴边")

    def test_address_extractor_keeps_listed_doors(self):
        found = extract_addresses("具体门牌号：襄阳南路452弄129、131、133号。")
        self.assertEqual(found[0]["路"], "襄阳南路")
        self.assertEqual(found[0]["弄"], "452")
        self.assertIn("129、131、133号", found[0]["原文"])


class ScoreTests(unittest.TestCase):
    def test_hard_filter_thresholds(self):
        self.assertEqual(hard_filter(None, 60), "未知")
        self.assertEqual(hard_filter(80, None), "未知")
        self.assertEqual(hard_filter(50, 60), "未通过")
        self.assertEqual(hard_filter(51, 70), "通过")
        self.assertEqual(hard_filter(80, 70.1), "未通过")

    def test_edge_decision_is_scored_but_not_raised_to_mid_without_price(self):
        scored = score_community([evidence()])
        self.assertEqual(scored["程序"], 28)
        self.assertEqual(scored["量价"], "N/A (M3)")
        self.assertIsNone(scored["结构"])
        self.assertIsNone(scored["档位"])
        self.assertEqual(scored["硬过滤"], "未知")
        self.assertIn("未知", scored["档位说明"])

    def test_subject_decision_is_excluded(self):
        scored = score_community([evidence(小区="甘陵小区", 匹配="程序内", 公告类型="决定")])
        self.assertIsNone(scored["程序"])
        self.assertTrue(scored["排除"])
        self.assertIsNone(scored["档位"])

    def test_high_tier_needs_both_steps_and_the_hard_filter(self):
        rows = [
            evidence(小区="沿街小区", 匹配="程序内", 公告类型="两清", 户数=80, 套均面积=60, 来源日期="2025-06-01"),
            evidence(小区="沿街小区", 匹配="贴边", 公告类型="决定", 户数=None, 套均面积=None, 来源日期="2025-07-01"),
        ]
        scored = score_community(rows)
        self.assertEqual(scored["程序"], 50)
        self.assertEqual(scored["档位"], "高")
        self.assertEqual(scored["硬过滤"], "通过")
        withheld = score_community([
            evidence(小区="沿街小区", 匹配="程序内", 公告类型="两清"),
            evidence(小区="沿街小区", 匹配="贴边", 公告类型="决定"),
        ])
        self.assertEqual(withheld["程序"], 50)
        self.assertIsNone(withheld["档位"])

    def test_consultation_alone_does_not_raise_a_tier(self):
        scored = score_community([
            evidence(小区="甘陵小区", 匹配="程序内", 公告类型="征询", 户数=80, 套均面积=62.5),
        ])
        self.assertEqual(scored["程序"], 8)
        self.assertIsNone(scored["档位"])
        self.assertIn("纯征询", scored["档位说明"])

    def test_points_do_not_stack(self):
        scored = score_community([
            evidence(公告类型="决定", 匹配="贴边"),
            evidence(公告类型="决定", 匹配="贴边", 来源URL="https://www.shanghai.gov.cn/gwk/search/content/second"),
        ])
        self.assertEqual(scored["程序"], 28)
        self.assertEqual(len(scored["证据"]), 2)


class SampleTests(unittest.TestCase):
    def test_failed_fetch_is_logged_and_not_invented(self):
        class Transport:
            def post_json(self, url, payload, *, referer):
                if "shyp.gov.cn" in url:
                    raise FetchError(url, "HTTP 403")
                if payload["keyword"] != "房屋征收决定" or payload["documentPublishYear"] != "2025":
                    return {"page": {"count": 0, "list": []}}
                return {
                    "page": {
                        "count": 1,
                        "list": [
                            {
                                "id": "abc",
                                "title": "上海市杨浦区人民政府房屋征收决定（136街坊）",
                                "txt": YANGPU,
                                "publish_date": "2025-05-19 08:00:00",
                                "agency": "杨浦区人民政府",
                            }
                        ],
                    }
                }

            def get_text(self, url, *, referer=None):
                raise FetchError(url, "HTTP 404")

        notices, logs = collect_notices(
            Transport(),
            since=dt.date(2024, 11, 27),
            until=dt.date(2026, 11, 27),
            interval=0,
            sleep=lambda _seconds: None,
        )
        self.assertEqual(len(notices), 1)
        self.assertTrue(any(item.get("原因") == "HTTP 403" for item in logs))
        evidence = [row for notice in notices for row in evidence_from_notice(notice)]
        self.assertTrue(all(row["来源URL"].startswith("https://www.shanghai.gov.cn/gwk/search/content/") for row in evidence))
        self.assertNotIn("fangdi", json.dumps(evidence, ensure_ascii=False))
        sample = build_sample(notices, evidence, logs, since="2024-11-27", until="2026-11-27", generated="2026-11-27")
        text = render_markdown(sample)
        self.assertIn("N/A (M3)", text)
        self.assertIn("珠江香樟北园", text)
        self.assertIn("https://www.shanghai.gov.cn/gwk/search/content/abc", text)

    def test_sample_refuses_the_site_and_the_formal_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "site").mkdir()
            (root / "data" / "prediction").mkdir(parents=True)
            (root / "fangdi.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                assert_private_output(root, root / "data" / "prediction")
            with self.assertRaises(ValueError):
                assert_private_output(root, root / "site" / "extra")
            sample = build_sample([], [], [], since="2024-11-27", until="2026-11-27", generated="2026-11-27")
            write_sample(root, root / "samples" / "m2", sample)
            self.assertTrue((root / "samples" / "m2" / "report.md").is_file())
            self.assertEqual((root / "fangdi.json").read_text(encoding="utf-8"), "{}")
            self.assertEqual(list((root / "data" / "prediction").iterdir()), [])

    def test_cli_fixture_transport_does_not_require_network(self):
        class Transport:
            def post_json(self, url, payload, *, referer):
                return {"page": {"count": 0, "list": []}, "data": {"list": [], "totalPage": 1}}

            def get_text(self, url, *, referer=None):
                raise FetchError(url, "HTTP 404")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fangdi.json").write_text("{}", encoding="utf-8")
            code = run_notices(
                root,
                root / "samples" / "m2",
                since=dt.date(2024, 11, 27),
                until=dt.date(2026, 11, 27),
                interval=0,
                transport=Transport(),
                sleep=lambda _seconds: None,
            )
            self.assertEqual(code, 1)
            self.assertIn("公告 0", (root / "samples" / "m2" / "report.md").read_text(encoding="utf-8"))

    def test_fangdi_is_refused(self):
        with self.assertRaises(FetchError):
            assert_not_fangdi("https://www.fangdi.com.cn/old_house/old_house.html")


if __name__ == "__main__":
    unittest.main()
