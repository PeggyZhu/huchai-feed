"""Fold one crawled day into a snapshot without dropping history."""

from __future__ import annotations

import calendar
import copy
import datetime as dt

from huchai.client import API_URL
from huchai.parse import Observation

SOURCE = "网上房地产（fangdi.com.cn 二手房昨日网签，含商业、车位）"
DAILY_NOTE = "含商业、车位。网上房地产二手房昨日网签。"


def merge_observation(snapshot: dict, observation: Observation, *, updated: str) -> tuple[dict, bool]:
    """Return ``(document, changed)``. The input snapshot is not mutated."""

    existing = _find(snapshot["daily"], observation.date)
    if existing is not None and int(existing["deals"]) == observation.deals and snapshot["asOf"] >= observation.date:
        return snapshot, False
    if existing is not None and int(existing["deals"]) != observation.deals and existing.get("origin") != "fangdi":
        raise ValueError(
            f"refusing to overwrite hand-curated {observation.date}: "
            f"{existing['deals']} vs crawled {observation.deals}"
        )

    merged = copy.deepcopy(snapshot)
    row = _daily_row(observation)
    if existing is None:
        merged["daily"].append(row)
    else:
        for index, item in enumerate(merged["daily"]):
            if item["key"] == observation.date:
                merged["daily"][index] = row
                break
    merged["daily"].sort(key=lambda item: item["key"])

    previous_as_of = snapshot["asOf"]
    previous_mtd = copy.deepcopy(snapshot.get("mtd") or {})
    if observation.date >= merged["asOf"]:
        merged["asOf"] = observation.date
    merged["updated"] = updated
    merged["source"] = SOURCE
    merged["writer"] = "huchai-feed"
    merged["endpoint"] = API_URL
    _recompute_month(merged, observation.date[:7])
    if observation.date[:7] == previous_as_of[:7] or merged["asOf"][:7] != previous_as_of[:7]:
        _recompute_mtd(merged, previous_mtd, previous_as_of)
    return merged, True


def _daily_row(observation: Observation) -> dict:
    row = {
        "key": observation.date,
        "deals": observation.deals,
        "sourced": True,
        "origin": "fangdi",
        "note": DAILY_NOTE,
    }
    if observation.area is not None:
        row["area"] = round(observation.area, 2)
    if observation.amount_yuan is not None:
        row["amountYuan"] = round(observation.amount_yuan, 2)
    return row


def _recompute_month(snapshot: dict, month_key: str) -> None:
    rows = snapshot["monthly"]
    existing = _find(rows, month_key)
    if existing is not None and not existing.get("partial"):
        return
    days = [row for row in snapshot["daily"] if row["key"].startswith(month_key)]
    dates = [row["key"] for row in days]
    # One day is a daily print, not a month total. October's hand partials stay put
    # until a real contiguous run from the 1st exists.
    if not _contiguous_from_start(dates) or len(dates) < 2:
        return
    last = _month_end(month_key)
    covered_through = dates[-1]
    partial = covered_through < last
    updated = {
        "key": month_key,
        "deals": sum(int(row["deals"]) for row in days),
        "sourced": True,
        "note": (
            f"截至 {covered_through} 的连续日合计，含商业、车位，未到月底。"
            if partial
            else "本月各日均已收录，合计为完整月，含商业、车位。"
        ),
    }
    if partial:
        updated["partial"] = True
    if existing is not None and existing.get("yoy") is not None:
        updated["yoy"] = existing["yoy"]
    if existing is None:
        rows.append(updated)
    else:
        for index, item in enumerate(rows):
            if item["key"] == month_key:
                rows[index] = updated
                break
    rows.sort(key=lambda item: item["key"])


def _recompute_mtd(snapshot: dict, previous_mtd: dict, previous_as_of: str) -> None:
    """Refresh the month-to-date block from days we actually hold.

    A single day is not promoted to a cumulative. A hand-entered cumulative in
    the same month is left alone when the crawled days still have gaps, so a
    new peak day cannot wipe a sourced total such as October's 14174.
    """

    as_of = snapshot["asOf"]
    month_key = as_of[:7]
    days = [row for row in snapshot["daily"] if row["key"].startswith(month_key) and row["key"] <= as_of]
    days.sort(key=lambda row: row["key"])
    dates = [row["key"] for row in days]
    month_row = _find(snapshot["monthly"], month_key)
    contiguous = _contiguous_from_start(dates) and bool(dates) and dates[-1] == as_of
    if contiguous and len(dates) >= 2:
        partial = as_of < _month_end(month_key)
        snapshot["mtd"] = {
            "deals": sum(int(row["deals"]) for row in days),
            "yoy": month_row.get("yoy") if month_row and month_row.get("yoy") is not None else None,
            "through": as_of,
            "partial": partial,
            "note": (
                f"截至 {as_of} 的连续日合计，含商业、车位。"
                if partial
                else f"{month_key} 各日均已收录，含商业、车位。"
            ),
        }
        return

    crossed_month = month_key != previous_as_of[:7]
    if not crossed_month and previous_mtd.get("deals") is not None:
        snapshot["mtd"] = previous_mtd
        return

    if len(dates) > 8:
        coverage = f"已收录 {len(dates)} 天（{dates[0]} 至 {dates[-1]}）"
    elif len(dates) == 1:
        coverage = f"只收录到 {dates[0]} 一天"
    elif dates:
        coverage = "已收录 " + "、".join(dates)
    else:
        coverage = "本月还没有收录到单日"
    reason = "中间有缺日，没有完整月内累计。" if len(dates) != 1 else "一天不能当成月内累计。"
    snapshot["mtd"] = {
        "deals": None,
        "yoy": None,
        "through": as_of,
        "partial": True,
        "note": coverage + "，" + reason,
    }


def _contiguous_from_start(dates: list[str]) -> bool:
    if not dates:
        return False
    ordered = sorted(dates)
    start = dt.date.fromisoformat(ordered[0][:7] + "-01")
    parsed = [dt.date.fromisoformat(value) for value in ordered]
    if parsed[0] != start:
        return False
    return all((right - left).days == 1 for left, right in zip(parsed, parsed[1:]))


def _month_end(month_key: str) -> str:
    year, month = (int(part) for part in month_key.split("-"))
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last:02d}"


def _find(rows: list[dict], key: str) -> dict | None:
    for row in rows:
        if row.get("key") == key:
            return row
    return None
