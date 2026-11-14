import datetime as dt
import json
import unittest
from pathlib import Path

from huchai.parse import Observation, parse_observation
from huchai.merge import merge_observation
from huchai.signals import signals_document
from huchai.snapshot import index_document, load_history, load_json

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 11, 14)


class HistoryTests(unittest.TestCase):
    def test_latest_file_is_the_newest_archive(self):
        latest = (ROOT / "fangdi.json").read_bytes()
        archived = (ROOT / "snapshots" / "2026-11-09.json").read_bytes()
        self.assertEqual(latest, archived)

    def test_archives_keep_the_hand_curated_anchors(self):
        latest = load_json(ROOT / "fangdi.json")
        months = {row["key"]: row for row in latest["monthly"]}
        days = {row["key"]: row["deals"] for row in latest["daily"]}
        self.assertEqual(months["2026-09"]["deals"], 23581)
        self.assertEqual(months["2026-09"]["yoy"], 15.7)
        self.assertEqual(months["2026-10"]["deals"], 24653)
        self.assertNotIn("partial", months["2026-10"])
        self.assertEqual(days["2026-10-11"], 1615)
        self.assertEqual(days["2026-10-17"], 1631)
        self.assertEqual(days["2026-10-31"], 1505)
        self.assertEqual(days["2026-11-01"], 1071)
        self.assertIsNone(latest["mtd"]["deals"])
        self.assertEqual(
            load_json(ROOT / "snapshots" / "index.json"),
            index_document(load_history(ROOT)),
        )
        for path in (ROOT / "snapshots").glob("????-??-??.json"):
            self.assertNotIn("writer", json.loads(path.read_text(encoding="utf-8")))

    def test_october_partial_total_is_still_in_that_snapshot(self):
        snap = load_json(ROOT / "snapshots" / "2026-10-26.json")
        self.assertEqual(snap["mtd"]["deals"], 14174)
        october = next(row for row in snap["monthly"] if row["key"] == "2026-10")
        self.assertTrue(october["partial"])
        self.assertEqual(october["deals"], 14174)


class MergeTests(unittest.TestCase):
    def test_new_day_keeps_frozen_months_and_does_not_invent_a_cumulative(self):
        current = load_json(ROOT / "fangdi.json")
        observed = parse_observation({"sellcount": 697, "sellarea": 54928.77}, today=TODAY)
        merged, changed = merge_observation(current, observed, updated="2026-11-14")
        self.assertTrue(changed)
        self.assertEqual(merged["updated"], "2026-11-14")
        self.assertEqual(merged["asOf"], "2026-11-13")
        self.assertEqual(merged["writer"], "huchai-feed")
        self.assertEqual(merged["ingest"], "crawl")
        self.assertEqual(merged["monthly"], current["monthly"])
        self.assertEqual([row["deals"] for row in current["daily"]], [1615, 1631, 1505, 1071])
        self.assertEqual(merged["daily"][-1]["deals"], 697)
        self.assertEqual(merged["daily"][-1]["origin"], "fangdi")
        self.assertEqual(merged["daily"][-1]["area"], 54928.77)
        self.assertIsNone(merged["mtd"]["deals"])
        self.assertEqual(merged["mtd"]["through"], "2026-11-13")
        self.assertIn("2026-11-01", merged["mtd"]["note"])
        self.assertIn("2026-11-13", merged["mtd"]["note"])

    def test_same_day_again_is_a_no_op(self):
        current = load_json(ROOT / "fangdi.json")
        observed = Observation("2026-11-01", 1071)
        merged, changed = merge_observation(current, observed, updated="2026-11-14")
        self.assertFalse(changed)
        self.assertEqual(merged, current)

    def test_refuses_to_replace_a_hand_curated_day(self):
        current = load_json(ROOT / "fangdi.json")
        with self.assertRaises(ValueError):
            merge_observation(current, Observation("2026-11-01", 999), updated="2026-11-14")

    def test_sparse_day_does_not_wipe_a_hand_cumulative(self):
        current = load_json(ROOT / "snapshots" / "2026-10-26.json")
        merged, changed = merge_observation(current, Observation("2026-10-21", 780), updated="2026-10-27")
        self.assertTrue(changed)
        self.assertEqual(merged["asOf"], "2026-10-21")
        self.assertEqual(merged["mtd"]["deals"], 14174)
        self.assertEqual(merged["mtd"]["through"], "2026-10-20")
        october = next(row for row in merged["monthly"] if row["key"] == "2026-10")
        self.assertEqual(october["deals"], 14174)
        september = next(row for row in merged["monthly"] if row["key"] == "2026-09")
        self.assertEqual(september["deals"], 23581)

    def test_crossing_into_a_new_month_does_not_keep_last_months_total(self):
        current = load_json(ROOT / "snapshots" / "2026-11-02.json")
        merged, _changed = merge_observation(current, Observation("2026-11-01", 1071), updated="2026-11-02")
        self.assertEqual(merged["mtd"]["deals"], None)
        self.assertEqual(merged["mtd"]["through"], "2026-11-01")
        october = next(row for row in merged["monthly"] if row["key"] == "2026-10")
        self.assertEqual(october["deals"], 24653)
        self.assertNotIn("2026-11", {row["key"] for row in merged["monthly"]})


class SignalTests(unittest.TestCase):
    def test_latest_signal_is_the_november_open(self):
        document = signals_document(load_history(ROOT))
        self.assertEqual(document["from"], "2026-11-02")
        self.assertEqual(document["to"], "2026-11-09")
        self.assertEqual(
            [item["title"] for item in document["items"]],
            [
                "截至日 2026-10-31 → 2026-11-01",
                "月内累计 24653 套 → 无累计",
                "新增单日 2026-11-01：1071 套",
            ],
        )
        self.assertIn("进入 2026-11", document["items"][1]["detail"])
        self.assertEqual(document["items"][1]["tone"], "info")

    def test_note_only_snapshot_is_not_called_a_volume_move(self):
        document = signals_document(load_history(ROOT))
        oldest = document["earlier"][-1]
        self.assertEqual((oldest["from"], oldest["to"]), ("2026-10-18", "2026-10-19"))
        self.assertEqual([item["kind"] for item in oldest["items"]], ["meta"])

    def test_october_close_is_an_up_move(self):
        document = signals_document(load_history(ROOT))
        pair = next(item for item in document["earlier"] if item["to"] == "2026-11-02")
        titles = [item["title"] for item in pair["items"]]
        self.assertIn("2026-10 月成交 14174 套 → 24653 套", titles)
        month = next(item for item in pair["items"] if item["kind"] == "month")
        self.assertEqual(month["tone"], "up")
        self.assertIn("未完月改为完整月", month["detail"])
        self.assertIn("37.9% → 33%", month["detail"])


if __name__ == "__main__":
    unittest.main()
