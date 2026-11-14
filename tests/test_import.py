import json
import shutil
import tempfile
import unittest
from pathlib import Path

from huchai.cli import main
from huchai.ingest import IMPORT_NOTE, IMPORT_SOURCE, refresh_command
from huchai.snapshot import history_paths, load_json

ROOT = Path(__file__).resolve().parents[1]


class ImportTests(unittest.TestCase):
    def copy_repo(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="huchai-import-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        shutil.copy(ROOT / "fangdi.json", root / "fangdi.json")
        shutil.copytree(ROOT / "snapshots", root / "snapshots")
        return root

    def test_deals_flag_writes_one_day_and_preserves_archives(self):
        root = self.copy_repo()
        archives = {path.name: path.read_bytes() for path in history_paths(root)}
        code = main(
            ["import", "--root", str(root), "--deals", "697", "--date", "2026-11-13", "--now", "2026-11-14"]
        )
        self.assertEqual(code, 0)
        for name, blob in archives.items():
            self.assertEqual((root / "snapshots" / name).read_bytes(), blob)
        latest = load_json(root / "fangdi.json")
        self.assertEqual(latest, load_json(root / "snapshots" / "2026-11-14.json"))
        day = latest["daily"][-1]
        self.assertEqual(day["key"], "2026-11-13")
        self.assertEqual(day["deals"], 697)
        self.assertEqual(day["origin"], "manual")
        self.assertEqual(day["note"], IMPORT_NOTE)
        self.assertEqual(latest["ingest"], "import")
        self.assertEqual(latest["writer"], "huchai-feed")
        self.assertEqual(latest["source"], IMPORT_SOURCE)
        self.assertEqual(next(row["deals"] for row in latest["monthly"] if row["key"] == "2026-10"), 24653)
        self.assertEqual(next(row["deals"] for row in latest["daily"] if row["key"] == "2026-11-01"), 1071)
        self.assertIsNone(latest["mtd"]["deals"])

    def test_second_import_can_correct_a_manual_day(self):
        root = self.copy_repo()
        archives = {path.name: path.read_bytes() for path in history_paths(root)}
        first = main(
            ["import", "--root", str(root), "--deals", "697", "--date", "2026-11-13", "--now", "2026-11-14"]
        )
        second = main(
            ["import", "--root", str(root), "--deals", "700", "--date", "2026-11-13", "--now", "2026-11-14"]
        )
        self.assertEqual((first, second), (0, 0))
        latest = load_json(root / "fangdi.json")
        self.assertEqual(latest["daily"][-1]["deals"], 700)
        self.assertEqual(latest["daily"][-1]["origin"], "manual")
        self.assertEqual(next(row["deals"] for row in latest["monthly"] if row["key"] == "2026-10"), 24653)
        self.assertEqual((root / "snapshots" / "2026-11-09.json").read_bytes(), archives["2026-11-09.json"])

    def test_import_can_correct_a_crawled_day(self):
        root = self.copy_repo()
        fixture = ROOT / "tests" / "fixtures" / "sell_ok.json"
        self.assertEqual(
            main(["crawl", "--root", str(root), "--fixture", str(fixture), "--now", "2026-11-14"]),
            0,
        )
        self.assertEqual(load_json(root / "fangdi.json")["daily"][-1]["origin"], "fangdi")
        code = main(
            ["import", "--root", str(root), "--deals", "700", "--date", "2026-11-13", "--now", "2026-11-14"]
        )
        self.assertEqual(code, 0)
        day = load_json(root / "fangdi.json")["daily"][-1]
        self.assertEqual(day["deals"], 700)
        self.assertEqual(day["origin"], "manual")
        self.assertEqual(load_json(root / "fangdi.json")["ingest"], "import")

    def test_file_with_several_days_publishes_once(self):
        root = self.copy_repo()
        payload = root / "days.json"
        payload.write_text(
            json.dumps(
                [
                    {"deals": 710, "date": "2026-11-14"},
                    {"deals": 697, "date": "2026-11-13"},
                ]
            ),
            encoding="utf-8",
        )
        code = main(["import", "--root", str(root), "--file", str(payload), "--now", "2026-11-15"])
        self.assertEqual(code, 0)
        latest = load_json(root / "fangdi.json")
        self.assertEqual([row["key"] for row in latest["daily"][-2:]], ["2026-11-13", "2026-11-14"])
        self.assertEqual([row["deals"] for row in latest["daily"][-2:]], [697, 710])
        self.assertEqual(latest["updated"], "2026-11-15")
        self.assertTrue((root / "snapshots" / "2026-11-15.json").is_file())
        self.assertFalse((root / "snapshots" / "2026-11-14.json").is_file())
        self.assertEqual(next(row["deals"] for row in latest["monthly"] if row["key"] == "2026-10"), 24653)

    def test_snapshot_file_only_adds_new_daily_rows(self):
        root = self.copy_repo()
        document = load_json(ROOT / "fangdi.json")
        document["daily"] = list(document["daily"]) + [{"key": "2026-11-13", "deals": 697}]
        payload = root / "snap.json"
        payload.write_text(json.dumps(document), encoding="utf-8")
        before = {path.name: path.read_bytes() for path in history_paths(root)}
        code = main(["import", "--root", str(root), "--file", str(payload), "--now", "2026-11-14"])
        self.assertEqual(code, 0)
        latest = load_json(root / "fangdi.json")
        days = {row["key"]: row for row in latest["daily"]}
        self.assertEqual(days["2026-11-01"]["deals"], 1071)
        self.assertNotIn("origin", days["2026-11-01"])
        self.assertEqual(days["2026-11-13"]["deals"], 697)
        self.assertEqual(days["2026-11-13"]["origin"], "manual")
        self.assertEqual(next(row["deals"] for row in latest["monthly"] if row["key"] == "2026-10"), 24653)
        for name, blob in before.items():
            self.assertEqual((root / "snapshots" / name).read_bytes(), blob)

    def test_bad_input_and_hand_conflicts_write_nothing(self):
        root = self.copy_repo()
        before = self._bytes(root)

        missing = root / "missing.json"
        missing.write_text('{"deals": 697}\n', encoding="utf-8")
        zero = root / "zero.json"
        zero.write_text('{"deals": 0, "date": "2026-11-13"}\n', encoding="utf-8")
        mixed = root / "mixed.json"
        mixed.write_text(
            json.dumps(
                [
                    {"deals": 697, "date": "2026-11-13"},
                    {"deals": 1, "date": "2026-11-01"},
                ]
            ),
            encoding="utf-8",
        )
        cases = [
            ["import", "--root", str(root), "--file", str(missing), "--now", "2026-11-14"],
            ["import", "--root", str(root), "--file", str(zero), "--now", "2026-11-14"],
            ["import", "--root", str(root), "--file", str(mixed), "--now", "2026-11-14"],
            ["import", "--root", str(root), "--deals", "999", "--date", "2026-11-01", "--now", "2026-11-14"],
            ["import", "--root", str(root), "--deals", "697", "--now", "2026-11-14"],
            ["import", "--root", str(root), "--deals", "697", "--date", "2026-11-13", "--file", str(missing)],
            ["import", "--root", str(root), "--deals", "697", "--date", "2099-01-01", "--now", "2026-11-14"],
            ["import", "--root", str(root), "--deals", "697", "--date", "2026-11-08", "--now", "2026-11-09"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertEqual(main(argv), 1)
                self.assertEqual(self._bytes(root), before)

    def test_dry_run_writes_nothing(self):
        root = self.copy_repo()
        before = self._bytes(root)
        code = main(
            [
                "import",
                "--root",
                str(root),
                "--deals",
                "697",
                "--date",
                "2026-11-13",
                "--now",
                "2026-11-14",
                "--dry-run",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(self._bytes(root), before)

    def test_same_total_again_is_unchanged(self):
        root = self.copy_repo()
        self.assertEqual(
            main(["import", "--root", str(root), "--deals", "1071", "--date", "2026-11-01", "--now", "2026-11-14"]),
            0,
        )
        self.assertEqual((root / "fangdi.json").read_bytes(), (ROOT / "fangdi.json").read_bytes())
        self.assertFalse((root / "snapshots" / "2026-11-14.json").exists())

    def test_refresh_command_matches_the_actions_inputs(self):
        root = self.copy_repo()
        before = self._bytes(root)
        idle = root / "unused.json"
        self.assertEqual(refresh_command("", "  ", "", "", json_path=idle), ["python3", "-m", "huchai", "crawl"])
        self.assertFalse(idle.exists())

        with self.assertRaises(ValueError):
            refresh_command("697", "", "", '{"deals":1,"date":"2026-11-13"}', json_path=idle)
        with self.assertRaises(ValueError):
            refresh_command("697", "", "", "", json_path=idle)
        with self.assertRaises(ValueError):
            refresh_command("", "", "", '{"deals":1}\n{"deals":2}', json_path=idle)
        self.assertFalse(idle.exists())
        self.assertEqual(self._bytes(root), before)

        supplied = root / "action.json"
        command = refresh_command(
            "",
            "",
            "",
            '{"deals":697,"date":"2026-11-13"}',
            json_path=supplied,
        )
        self.assertEqual(command, ["python3", "-m", "huchai", "import", "--file", str(supplied)])
        self.assertEqual(json.loads(supplied.read_text(encoding="utf-8"))["deals"], 697)
        code = main(command[3:] + ["--root", str(root), "--now", "2026-11-14"])
        self.assertEqual(code, 0)
        self.assertEqual(load_json(root / "fangdi.json")["daily"][-1]["deals"], 697)

        numbered = refresh_command("710", "2026-11-14", "54928.77", "", json_path=idle)
        self.assertEqual(
            numbered,
            ["python3", "-m", "huchai", "import", "--deals", "710", "--date", "2026-11-14", "--area", "54928.77"],
        )
        code = main(numbered[3:] + ["--root", str(root), "--now", "2026-11-15"])
        self.assertEqual(code, 0)
        latest = load_json(root / "fangdi.json")
        self.assertEqual(latest["daily"][-1]["deals"], 710)
        self.assertEqual(latest["daily"][-1]["area"], 54928.77)

        workflow = (ROOT / ".github" / "workflows" / "crawl.yml").read_text(encoding="utf-8")
        self.assertIn("name: refresh", workflow)
        self.assertIn("IMPORT_JSON:", workflow)
        self.assertIn("refresh_command", workflow)
        self.assertNotIn("huchai import --deals ${{", workflow)

    def _bytes(self, root: Path) -> dict:
        paths = [root / "fangdi.json", *sorted((root / "snapshots").glob("*.json"))]
        return {str(path.relative_to(root)): path.read_bytes() for path in paths}


if __name__ == "__main__":
    unittest.main()
