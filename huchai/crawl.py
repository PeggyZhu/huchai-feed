"""Crawl one observation and publish it only when the payload is complete."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from huchai.client import UrllibTransport
from huchai.merge import merge_observation
from huchai.parse import parse_observation
from huchai.snapshot import assert_preserves, dump, load_json, publish_latest, validate_snapshot

SHANGHAI = ZoneInfo("Asia/Shanghai")


def run_crawl(
    root: Path,
    *,
    dry_run: bool = False,
    fixture: Path | None = None,
    now: dt.date | None = None,
    transport=None,
) -> int:
    root = root.resolve()
    latest_path = root / "fangdi.json"
    current = load_json(latest_path)
    validate_snapshot(current)
    today = now or dt.datetime.now(SHANGHAI).date()

    if fixture is not None:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        print(f"fixture {fixture}")
    else:
        client = transport or UrllibTransport()
        payload = client.fetch_yesterday()

    observation = parse_observation(payload, today=today)
    area = "—" if observation.area is None else observation.area
    print(f"observation {observation.date} deals={observation.deals} area={area}")

    merged, changed = merge_observation(current, observation, updated=today.isoformat())
    if not changed:
        print("unchanged")
        return 0
    assert_preserves(current, merged)
    validate_snapshot(merged)
    print(f"changed asOf {current['asOf']} → {merged['asOf']}")
    if dry_run:
        print(dump(merged))
        print("dry-run: no files written")
        return 0

    publish_latest(root, merged)
    print(f"wrote fangdi.json and snapshots/{merged['updated']}.json")
    return 0
