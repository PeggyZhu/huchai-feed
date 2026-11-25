import datetime as dt
import json
import shutil
import unittest
from pathlib import Path

from huchai.build_site import build_site
from huchai.cli import main
from huchai.crawl import run_crawl
from huchai.errors import SourceBlocked
from huchai.snapshot import history_paths, index_document, load_history, load_json
from tests.corpus import ROOT, frozen_baseline

FIXTURE = ROOT / "tests" / "fixtures" / "sell_ok.json"


class CrawlTests(unittest.TestCase):
    def copy_repo(self) -> Path:
        return frozen_baseline(self)

    def test_dry_run_and_blocked_fetch_do_not_touch_files(self):
        root = self.copy_repo()
        before = self._bytes(root)
        code = main(
            ["crawl", "--root", str(root), "--fixture", str(FIXTURE), "--now", "2026-11-14", "--dry-run"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(self._bytes(root), before)

        class Blocked:
            def fetch_yesterday(self):
                raise SourceBlocked("blocked")

        with self.assertRaises(SourceBlocked):
            run_crawl(root, transport=Blocked(), now=dt.date(2026, 11, 14))
        self.assertEqual(self._bytes(root), before)

    def test_bad_payload_exits_1_without_writing(self):
        root = self.copy_repo()
        before = self._bytes(root)
        bad = root / "bad.json"
        bad.write_text('{"sellcount": 0}\n', encoding="utf-8")
        code = main(["crawl", "--root", str(root), "--fixture", str(bad), "--now", "2026-11-14"])
        self.assertEqual(code, 1)
        self.assertEqual(self._bytes(root), before)

    def test_fixture_crawl_writes_a_new_snapshot_and_preserves_archives(self):
        root = self.copy_repo()
        archives = {path.name: path.read_bytes() for path in history_paths(root)}
        code = main(["crawl", "--root", str(root), "--fixture", str(FIXTURE), "--now", "2026-11-14"])
        self.assertEqual(code, 0)
        for name, blob in archives.items():
            self.assertEqual((root / "snapshots" / name).read_bytes(), blob)
        latest = load_json(root / "fangdi.json")
        archived = load_json(root / "snapshots" / "2026-11-14.json")
        self.assertEqual(latest, archived)
        self.assertEqual(latest["daily"][-1]["deals"], 697)
        self.assertEqual(next(row["deals"] for row in latest["monthly"] if row["key"] == "2026-10"), 24653)
        index = load_json(root / "snapshots" / "index.json")
        self.assertEqual(index["snapshots"][-1]["updated"], "2026-11-14")
        self.assertEqual(index, index_document(load_history(root)))
        revised = root / "revised.json"
        revised.write_text('{"sellcount": 700, "date": "2026-11-13"}\n', encoding="utf-8")
        code = main(["crawl", "--root", str(root), "--fixture", str(revised), "--now", "2026-11-14"])
        self.assertEqual(code, 0)
        self.assertEqual(load_json(root / "fangdi.json")["daily"][-1]["deals"], 700)
        self.assertEqual((root / "snapshots" / "2026-11-09.json").read_bytes(), archives["2026-11-09.json"])

    def test_refuses_to_overwrite_a_hand_archive(self):
        root = self.copy_repo()
        archive = (root / "snapshots" / "2026-11-09.json").read_bytes()
        fangdi = (root / "fangdi.json").read_bytes()
        with self.assertRaises(ValueError):
            run_crawl(root, fixture=FIXTURE, now=dt.date(2026, 11, 9))
        self.assertEqual((root / "snapshots" / "2026-11-09.json").read_bytes(), archive)
        self.assertEqual((root / "fangdi.json").read_bytes(), fangdi)

    def _bytes(self, root: Path) -> dict:
        paths = [root / "fangdi.json", *sorted((root / "snapshots").glob("*.json"))]
        return {str(path.relative_to(root)): path.read_bytes() for path in paths}


class BuildTests(unittest.TestCase):
    def test_build_keeps_relative_paths_and_raw_json(self):
        import tempfile

        out = Path(tempfile.mkdtemp(prefix="huchai-dist-"))
        self.addCleanup(lambda: shutil.rmtree(out, ignore_errors=True))
        build_site(ROOT, out)
        html = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="styles.css"', html)
        self.assertIn('src="app.js"', html)
        self.assertNotIn('src="/', html)
        self.assertNotIn('href="/', html)
        self.assertEqual((out / "fangdi.json").read_bytes(), (ROOT / "fangdi.json").read_bytes())
        self.assertEqual(
            (out / "snapshots" / "2026-10-18.json").read_bytes(),
            (ROOT / "snapshots" / "2026-10-18.json").read_bytes(),
        )
        signals = json.loads((out / "signals.json").read_text(encoding="utf-8"))
        history = load_history(ROOT)
        self.assertEqual(signals["to"], history[-1]["updated"])
        self.assertEqual(signals["from"], history[-2]["updated"])
        self.assertTrue((out / "snapshots" / "index.json").is_file())
        index = json.loads((out / "snapshots" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index, index_document(load_history(ROOT)))


if __name__ == "__main__":
    unittest.main()
