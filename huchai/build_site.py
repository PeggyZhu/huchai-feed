"""Assemble the static site into a directory GitHub Pages can publish."""

from __future__ import annotations

import shutil
from pathlib import Path

from huchai.signals import signals_document
from huchai.snapshot import dump, history_paths, index_document, load_history, load_json, validate_snapshot

SITE_FILES = ("index.html", "app.js", "styles.css")


def build_site(root: Path, out: Path) -> Path:
    root = root.resolve()
    out = out.resolve()
    if out == root or out in root.parents:
        raise ValueError(f"refusing to build into {out}")
    latest = load_json(root / "fangdi.json")
    validate_snapshot(latest)
    snapshots = load_history(root)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    site = root / "site"
    for name in SITE_FILES:
        shutil.copyfile(site / name, out / name)
    shutil.copyfile(root / "fangdi.json", out / "fangdi.json")
    # Keep the archived bytes exactly, including the latest hand snapshot.
    snapshot_dir = out / "snapshots"
    snapshot_dir.mkdir()
    for path in history_paths(root):
        shutil.copyfile(path, snapshot_dir / path.name)
    (snapshot_dir / "index.json").write_text(dump(index_document(snapshots)), encoding="utf-8")
    (out / "signals.json").write_text(dump(signals_document(snapshots)), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    _assert_relative_assets(out / "index.html")
    return out


def _assert_relative_assets(index_html: Path) -> None:
    text = index_html.read_text(encoding="utf-8")
    for token in ('src="/', "href=\"/", "src='/", "href='/"):
        if token in text:
            raise ValueError(f"{index_html} uses a root-absolute asset path ({token})")
