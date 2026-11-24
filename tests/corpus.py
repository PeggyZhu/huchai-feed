"""Frozen corpus for behavior tests.

The refresh workflow runs this suite before it imports a day. Behavior
tests that read the live ``fangdi.json`` fail after every successful
update, so the next import never starts. They use the 2026-11-09 hand
archive instead: the five files below have no ``writer`` and the publish
path refuses to replace them.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAND_ARCHIVES = (
    "2026-10-18.json",
    "2026-10-19.json",
    "2026-10-26.json",
    "2026-11-02.json",
    "2026-11-09.json",
)
BASELINE_NAME = "2026-11-09.json"


def frozen_baseline(test: unittest.TestCase) -> Path:
    root = Path(tempfile.mkdtemp(prefix="huchai-baseline-"))
    test.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
    snapshots = root / "snapshots"
    snapshots.mkdir()
    for name in HAND_ARCHIVES:
        shutil.copy(ROOT / "snapshots" / name, snapshots / name)
    shutil.copy(ROOT / "snapshots" / BASELINE_NAME, root / "fangdi.json")
    return root


def live_copy(test: unittest.TestCase) -> Path:
    root = Path(tempfile.mkdtemp(prefix="huchai-live-"))
    test.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
    shutil.copy(ROOT / "fangdi.json", root / "fangdi.json")
    shutil.copytree(ROOT / "snapshots", root / "snapshots")
    return root
