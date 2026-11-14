"""Describe what changed between two snapshots."""

from __future__ import annotations


def diff_snapshots(previous: dict, current: dict) -> list[dict]:
    items: list[dict] = []
    if previous.get("asOf") != current.get("asOf"):
        items.append(
            _item(
                "as_of",
                "info",
                f"截至日 {previous.get('asOf')} → {current.get('asOf')}",
                "这份快照覆盖到的数据日变了。",
            )
        )

    old_mtd = previous.get("mtd") or {}
    new_mtd = current.get("mtd") or {}
    if _mtd_view(old_mtd) != _mtd_view(new_mtd):
        same_deals = old_mtd.get("deals") == new_mtd.get("deals")
        title = (
            f"月内累计仍为 {_fmt(new_mtd.get('deals'))}，截至 {old_mtd.get('through')} → {new_mtd.get('through')}"
            if same_deals
            else f"月内累计 {_fmt(old_mtd.get('deals'))} → {_fmt(new_mtd.get('deals'))}"
        )
        items.append(
            _item(
                "mtd",
                "info" if same_deals else _tone(old_mtd.get("deals"), new_mtd.get("deals")),
                title,
                _mtd_detail(old_mtd, new_mtd),
            )
        )

    old_months = {row["key"]: row for row in previous.get("monthly") or []}
    new_months = {row["key"]: row for row in current.get("monthly") or []}
    for key in sorted(set(old_months) | set(new_months)):
        before = old_months.get(key)
        after = new_months.get(key)
        if before is None and after is not None:
            items.append(
                _item(
                    "month_new",
                    "info",
                    f"新增月份 {key}：{_fmt(after.get('deals'))}",
                    "未完月" if after.get("partial") else "完整月",
                )
            )
            continue
        if before is not None and after is None:
            items.append(_item("month_removed", "info", f"月份 {key} 从快照中消失", "这不应该发生，请核对数据。"))
            continue
        assert before is not None and after is not None
        if _month_view(before) == _month_view(after):
            continue
        detail = []
        if bool(before.get("partial")) != bool(after.get("partial")):
            detail.append("未完月改为完整月。" if before.get("partial") and not after.get("partial") else "完整月标记有变化。")
        if before.get("yoy") != after.get("yoy"):
            detail.append(f"同比 {_fmt_yoy(before.get('yoy'))} → {_fmt_yoy(after.get('yoy'))}。")
        items.append(
            _item(
                "month",
                _tone(before.get("deals"), after.get("deals")),
                f"{key} 月成交 {_fmt(before.get('deals'))} → {_fmt(after.get('deals'))}",
                "".join(detail) or "月度数字有修订。",
            )
        )

    old_days = {row["key"]: row for row in previous.get("daily") or []}
    new_days = {row["key"]: row for row in current.get("daily") or []}
    for key in sorted(set(old_days) | set(new_days)):
        before = old_days.get(key)
        after = new_days.get(key)
        if before is None and after is not None:
            items.append(
                _item(
                    "daily_new",
                    "info",
                    f"新增单日 {key}：{after['deals']} 套",
                    after.get("note") or "",
                )
            )
        elif before is not None and after is None:
            items.append(_item("daily_removed", "info", f"单日 {key} 从快照中消失", "这不应该发生，请核对数据。"))
        elif before is not None and after is not None and before.get("deals") != after.get("deals"):
            items.append(
                _item(
                    "daily",
                    _tone(before.get("deals"), after.get("deals")),
                    f"单日 {key} {before['deals']} 套 → {after['deals']} 套",
                    "同一天的网签套数有修订。",
                )
            )

    if not items and (previous.get("updated") != current.get("updated") or previous.get("source") != current.get("source")):
        items.append(
            _item(
                "meta",
                "info",
                f"快照日 {previous.get('updated')} → {current.get('updated')}",
                "成交套数没有变化，说明文字或来源注记有更新。",
            )
        )
    return items


def signals_document(snapshots: list[dict]) -> dict:
    ordered = sorted(snapshots, key=lambda item: item["updated"])
    if len(ordered) < 2:
        only = ordered[0]["updated"] if ordered else None
        return {"from": None, "to": only, "items": [], "earlier": []}
    pairs = []
    for previous, current in zip(ordered, ordered[1:]):
        pairs.append(
            {
                "from": previous["updated"],
                "to": current["updated"],
                "items": diff_snapshots(previous, current),
            }
        )
    latest = pairs[-1]
    earlier = list(reversed(pairs[:-1]))
    return {"from": latest["from"], "to": latest["to"], "items": latest["items"], "earlier": earlier}


def _mtd_view(mtd: dict) -> tuple:
    return (mtd.get("deals"), mtd.get("through"), bool(mtd.get("partial")), mtd.get("yoy"))


def _month_view(row: dict) -> tuple:
    return (row.get("deals"), bool(row.get("partial")), row.get("yoy"))


def _mtd_detail(previous: dict, current: dict) -> str:
    old_through = previous.get("through") or ""
    new_through = current.get("through") or ""
    if (
        previous.get("deals") is not None
        and current.get("deals") is None
        and old_through[:7] != new_through[:7]
    ):
        return (
            f"截至日从 {old_through} 进入 {new_through[:7]}。"
            "新的月份还没有月内累计，所以上一个月的合计不再放在「月内」这一栏。"
        )
    bits = [f"截至 {old_through or '—'} → {new_through or '—'}。"]
    if bool(previous.get("partial")) != bool(current.get("partial")):
        bits.append("未完月。" if current.get("partial") else "已视为完整区间。")
    if previous.get("yoy") != current.get("yoy"):
        bits.append(f"同比 {_fmt_yoy(previous.get('yoy'))} → {_fmt_yoy(current.get('yoy'))}。")
    note = current.get("note")
    if note:
        bits.append(str(note))
    return "".join(bits)


def _tone(previous, current) -> str:
    if isinstance(previous, (int, float)) and isinstance(current, (int, float)) and not isinstance(previous, bool):
        if current > previous:
            return "up"
        if current < previous:
            return "down"
    return "info"


def _fmt(value) -> str:
    if value is None:
        return "无累计"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value} 套"


def _fmt_yoy(value) -> str:
    if value is None:
        return "无"
    number = int(value) if isinstance(value, float) and value.is_integer() else value
    return f"{number}%"


def _item(kind: str, tone: str, title: str, detail: str) -> dict:
    return {"kind": kind, "tone": tone, "title": title, "detail": detail}
