"""程序 score and tier for one community.

The caps and the tier gates are the rules in docs/prediction/DECISIONS.md.
Point values below are only a sort key inside the 0–50 程序 cap. They do
not add a new tier threshold. This module still leaves 量价 as N/A (M3):
the M2 sample is program evidence only. Deal-count points live in
huchai.volume and are not written back into that sample. 挂牌价, 评估价 and
成交价 are not read.
"""

from __future__ import annotations


PROGRAM_CAP = 50
PRICE_CAP = 30
STRUCTURE_CAP = 20
PRICE_MARK = "N/A (M3)"

# One community takes the maximum applicable row, never a sum.
POINTS = {
    ("程序内", "征询"): 8,
    ("部分覆盖", "征询"): 5,
    ("程序内", "旧改公告"): 12,
    ("部分覆盖", "旧改公告"): 8,
    ("程序内", "城中村"): 12,
    ("部分覆盖", "城中村"): 8,
    ("程序内", "征收范围"): 16,
    ("部分覆盖", "征收范围"): 10,
    ("贴边", "冻结"): 18,
    ("贴边", "决定"): 28,
    ("程序内", "两清"): 40,
    ("部分覆盖", "两清"): 30,
    ("程序内", "准动迁挂牌"): 40,
    ("部分覆盖", "准动迁挂牌"): 30,
}
EXCLUDED_KINDS = {"冻结", "决定", "签约", "腾退"}
INSIDE = {"程序内", "部分覆盖"}


def hard_filter(households: int | None, area: float | int | None) -> str:
    """户数>50 and 套均≤70. Unknown stays 未知; nothing is filled in."""
    if households is None or area is None:
        return "未知"
    if households > 50 and area <= 70:
        return "通过"
    return "未通过"


def score_community(rows: list[dict]) -> dict:
    named = [row for row in rows if row.get("小区") and row.get("匹配") in {"程序内", "部分覆盖", "贴边"}]
    real = [row for row in named if not row.get("假阳性")]
    false_rows = [row for row in named if row.get("假阳性")]
    excluded = _excluded(real)
    high = _has_stage(real, INSIDE, {"两清", "准动迁挂牌"}) and _has_stage(real, {"贴边"}, {"决定"})
    points = _points(real, high=high and not excluded)
    households, household_raw, area, area_raw = _structure(real)
    hard = hard_filter(households, area)
    tier, reason = _tier(real, excluded=excluded, high=high, hard=hard, false_only=not real and bool(false_rows))
    evidence = sorted(real or false_rows, key=lambda row: row.get("来源日期") or "", reverse=True)
    latest = evidence[0] if evidence else (named[0] if named else None)
    return {
        "小区": latest["小区"] if latest else None,
        "区": latest.get("区") if latest else None,
        "程序": points if not excluded and real else None,
        "量价": PRICE_MARK,
        "结构": None,
        "硬过滤": hard if real else "未知",
        "户数": households,
        "户数原文": household_raw,
        "套均面积": area,
        "套均原文": area_raw,
        "档位": tier,
        "档位说明": reason,
        "排除": excluded,
        "假阳性": sorted({row["假阳性"] for row in false_rows if row.get("假阳性")}),
        "匹配": _strongest_match(real or false_rows),
        "公告类型": latest.get("公告类型") if latest else None,
        "来源日期": latest.get("来源日期") if latest else None,
        "来源URL": latest.get("来源URL") if latest else None,
        "原始地址": latest.get("原始地址") if latest else None,
        "证据": [
            {
                "来源URL": row.get("来源URL"),
                "来源日期": row.get("来源日期"),
                "公告类型": row.get("公告类型"),
                "匹配": row.get("匹配"),
                "置信度": row.get("置信度"),
                "原始地址": row.get("原始地址"),
                "文号": row.get("文号"),
                "项目名": row.get("项目名"),
                "假阳性": row.get("假阳性"),
            }
            for row in evidence
        ],
    }


def _excluded(rows: list[dict]) -> str | None:
    for row in rows:
        if row.get("匹配") in INSIDE and row.get("公告类型") in EXCLUDED_KINDS:
            return "已" + row["公告类型"]
    return None


def _has_stage(rows: list[dict], matches: set[str], kinds: set[str]) -> bool:
    return any(row.get("匹配") in matches and row.get("公告类型") in kinds for row in rows)


def _points(rows: list[dict], *, high: bool) -> int | None:
    if high:
        return PROGRAM_CAP
    best: int | None = None
    for row in rows:
        value = POINTS.get((row.get("匹配"), row.get("公告类型")))
        if value is None:
            continue
        best = value if best is None else max(best, value)
    if best is None:
        return None
    return min(PROGRAM_CAP, best)


def _structure(rows: list[dict]) -> tuple[int | None, str | None, float | int | None, str | None]:
    households = [row.get("户数") for row in rows if row.get("匹配") in INSIDE and isinstance(row.get("户数"), int)]
    areas = [row.get("套均面积") for row in rows if row.get("匹配") in INSIDE and isinstance(row.get("套均面积"), (int, float))]
    household_raw = next((row.get("户数原文") for row in rows if row.get("户数原文")), None)
    area_raw = next((row.get("套均原文") for row in rows if row.get("套均原文")), None)
    household = households[0] if len(set(households)) == 1 else None
    area = areas[0] if len(set(areas)) == 1 else None
    if len(set(households)) > 1:
        household_raw = "；".join(str(item) for item in households)
    return household, household_raw, area, area_raw


def _tier(rows: list[dict], *, excluded: str | None, high: bool, hard: str, false_only: bool) -> tuple[str | None, str]:
    if excluded:
        return None, f"排除：{excluded}。已冻结、已决定、已签约、已腾退不进入观察池。"
    if false_only:
        return None, "假阳性（收储、成套改造、市政冻结、学区或对倒），不作为征收信号。"
    if not rows:
        return None, "没有可匹配的程序证据。"
    if hard == "未知":
        return None, "硬过滤未知：户数或套均没有公开的纯数字原文，不排档，也不补数字。"
    if hard == "未通过":
        return None, "硬过滤未通过：需要户数>50且套均≤70㎡，不排档。"
    if high:
        return "高", "两清或准动迁挂牌，并且贴边地块已有征收决定。"
    if rows and all(row.get("公告类型") == "征询" for row in rows):
        return None, "纯征询不升高。"
    if _has_stage(rows, {"贴边"}, {"冻结", "决定"}) and not _has_stage(rows, INSIDE, EXCLUDED_KINDS | {"两清", "准动迁挂牌"}):
        return None, "贴边地块处于冻结或决定，本小区不在清单内；超额涨幅未计算，不升为中。量价为 N/A (M3)。"
    return None, "只有程序证据。低档需要超额涨幅≥5%，量价为 N/A (M3)，不排档。"


def _strongest_match(rows: list[dict]) -> str | None:
    order = {"程序内": 4, "部分覆盖": 3, "贴边": 2, "待核": 1}
    best = None
    rank = -1
    for row in rows:
        value = order.get(row.get("匹配"), 0)
        if value > rank:
            rank = value
            best = row.get("匹配")
    return best


def rank_communities(scored: list[dict]) -> list[dict]:
    """Candidates first, by 程序分. Excluded communities stay out of this order."""
    pool = [row for row in scored if row.get("小区") and not row.get("排除")]
    pool.sort(key=lambda row: row.get("小区") or "")
    pool.sort(key=lambda row: row.get("来源日期") or "", reverse=True)
    pool.sort(key=lambda row: row["程序"] if isinstance(row.get("程序"), int) else -1, reverse=True)
    return pool
