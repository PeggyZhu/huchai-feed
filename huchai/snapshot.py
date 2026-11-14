"""Load, validate, and atomically store snapshot documents."""

from __future__ import annotations

import json
import re
from pathlib import Path

SNAP_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
REQUIRED = ("updated", "asOf", "source", "mtd", "monthly", "daily")


def dump(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def validate_snapshot(document: dict) -> None:
    missing = [key for key in REQUIRED if key not in document]
    if missing:
        raise ValueError("snapshot missing " + ", ".join(missing))
    if not isinstance(document["monthly"], list) or not document["monthly"]:
        raise ValueError("snapshot monthly series is empty")
    if not isinstance(document["daily"], list) or not document["daily"]:
        raise ValueError("snapshot daily series is empty")
    if not isinstance(document["mtd"], dict):
        raise ValueError("snapshot mtd is not an object")
    for row in document["monthly"]:
        if "key" not in row or "deals" not in row:
            raise ValueError("monthly row missing key or deals")
    for row in document["daily"]:
        if "key" not in row or not isinstance(row.get("deals"), int):
            raise ValueError("daily row needs an integer deals count")
        if row["deals"] < 1:
            raise ValueError("daily deals must be positive")


def history_paths(root: Path) -> list[Path]:
    folder = root / "snapshots"
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.glob("*.json") if SNAP_NAME.match(path.name))


def load_history(root: Path) -> list[dict]:
    snapshots = []
    for path in history_paths(root):
        document = load_json(path)
        validate_snapshot(document)
        if document.get("updated") != path.stem:
            raise ValueError(f"{path.name} updated field is {document.get('updated')}")
        snapshots.append(document)
    if not snapshots:
        raise ValueError("no dated snapshots in snapshots/")
    return snapshots


def index_document(snapshots: list[dict]) -> dict:
    return {
        "snapshots": [
            {
                "updated": item["updated"],
                "asOf": item["asOf"],
                "path": f"snapshots/{item['updated']}.json",
                "mtdDeals": (item.get("mtd") or {}).get("deals"),
                "months": [row["key"] for row in item["monthly"]],
                "days": [row["key"] for row in item["daily"]],
            }
            for item in snapshots
        ]
    }


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def assert_preserves(previous: dict, merged: dict) -> None:
    """Refuse a merge that drops history or rewrites a hand-curated figure."""

    validate_snapshot(merged)
    if merged["asOf"] < previous["asOf"]:
        raise ValueError("refusing to move asOf backwards")

    old_days = {row["key"]: row for row in previous["daily"]}
    new_days = {row["key"]: row for row in merged["daily"]}
    for key, row in old_days.items():
        if key not in new_days:
            raise ValueError(f"refusing to drop daily {key}")
        if new_days[key]["deals"] != row["deals"] and row.get("origin") != "fangdi":
            raise ValueError(f"refusing to overwrite hand-curated daily {key}")

    old_months = {row["key"]: row for row in previous["monthly"]}
    new_months = {row["key"]: row for row in merged["monthly"]}
    for key, row in old_months.items():
        if key not in new_months:
            raise ValueError(f"refusing to drop month {key}")
        frozen = not row.get("partial")
        if frozen and new_months[key].get("deals") != row.get("deals"):
            raise ValueError(f"refusing to overwrite complete month {key}")
