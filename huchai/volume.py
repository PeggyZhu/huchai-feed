"""Volume-only 量价 score from public deal counts.

The 2026-11-28 decision in docs/prediction/DECISIONS.md replaces price
excess with a count of deals. This module does not read prices, does not
edit fangdi.json, and does not fill the formal prediction tables.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from fractions import Fraction
from pathlib import Path

from huchai.notices.score import EXCLUDED_KINDS, INSIDE


COLLECTED_ON = dt.date(2026, 11, 28)
COMPLETE = (2026, 10)
PARTIAL = (2026, 11)
MIN_COUNT = 8
LOW = Fraction(5, 100)
MID = Fraction(8, 100)
POINTS_LOW = 15
POINTS_MID = 30
LOOKBACK_MONTHS = 12
HIGH_KINDS = {"两清", "准动迁挂牌"}
BACKTEST = ("兰岭园", "北梅园", "甘泉三村", "海洲丽园", "珠江香樟北园")
ALSO_COLLECTED = ("实华公寓", "曹杨新村", "甘陵小区")

RULES = (
    "按自然月计成交套数。同一天有多行就按多套计，页面没有成交编号，不能再去重。",
    "每个月末看刚结束的 3 个月，同时对比上年同一 3 个月，以及紧挨着的前 3 个月。",
    "当前这 3 个月不足 8 套，标「样本不足」，量价分记 0，不计算增速。8 是当前窗口的门槛，不是比较段的门槛。",
    "比较段的每个月都要落在检索窗口里，并且套数大于 0，这一腿才有增速。没采集到的月份不当成 0，比较段为 0 也不做除法。",
    "两腿都有增速时取较低的一腿。达到 5% 记 15 分，达到 8% 记 30 分，不到 5% 记 0 分。比较用精确分数，表上的百分数只供阅读。",
    "回看公告日之前的 12 个月，逐个月末判断。同比要用到再往前一年的 3 个月，那 3 个月可以早于这 12 个月，只要落在检索窗口里。公告当日和之后的成交不进入回看。",
    "页面上的档位用最近一个完整月（2026-10）为止的窗口。2026-11 只收到采集日 2026-11-28 之前的记录，是未完月，不参与打分。",
    "程序、结构、硬过滤、排除和纯征询不升高，仍按 2026-11-25。硬过滤未知就不排档。口径待核的套数可以展示，不据此升档。",
    "不使用挂牌价、评估价或成交价，也不再相对全市计算超额涨幅。",
)

DISCLAIMER = (
    "不是投资建议。本页不预测哪一处一定会征收，也不提示买卖。"
    "套数来自贝壳公开成交页，程序来自政府公开公告。没有价格。"
)

DEAL_SOURCE = (
    "贝壳找房上海站 sh.ke.com 公开成交记录，2026-11-28 用浏览器手工采集。"
    "只记录套数和页面上的日期，没有价格。"
)


def _coverage(start: tuple[int, int], extra: str = "", caliber: str = "") -> dict:
    text = f"贝壳检索窗口从 {start[0]:04d}-{start[1]:02d} 起。窗口之前的成交只单列所在月，不把相邻月份记成 0。"
    if extra:
        text = text + extra
    return {"状态": "已采集", "起": start, "说明": text, "口径": caliber}


COVERAGE = {
    "兰岭园": _coverage((2025, 1)),
    "北梅园": _coverage((2025, 1), "结果里另有 2024 年的成交，只单列那一个月。"),
    "海洲丽园": _coverage((2024, 1)),
    "珠江香樟北园": _coverage(
        (2024, 1),
        caliber="贝壳成交标题是珠江香樟园，不是珠江香樟北园，口径待核。套数仍按该搜索结果计数，不据此升档。",
    ),
    "甘泉三村": _coverage((2024, 1)),
    "实华公寓": _coverage((2024, 1), "采集者注明 2024-01 以来没有成交，最近一条在窗口外。"),
    "曹杨新村": {
        "状态": "无记录",
        "起": None,
        "说明": "贝壳搜索没有返回成交记录。这不是 0 套。",
        "口径": "",
    },
    "甘陵小区": {
        "状态": "待核",
        "起": None,
        "说明": "搜索只返回其他小区，名称没有核上。不把甘泉三村的套数算到甘陵小区。",
        "口径": "待核",
    },
}
UNCOLLECTED = {
    "状态": "未采集",
    "起": None,
    "说明": "这次贝壳检索没有覆盖这个小区。",
    "口径": "",
}


def month_key(month: tuple[int, int]) -> str:
    return f"{month[0]:04d}-{month[1]:02d}"


def add_months(month: tuple[int, int], delta: int) -> tuple[int, int]:
    index = month[0] * 12 + (month[1] - 1) + delta
    return index // 12, index % 12 + 1


def month_end(month: tuple[int, int]) -> dt.date:
    year, mon = month
    if mon == 12:
        return dt.date(year, 12, 31)
    return dt.date(year, mon + 1, 1) - dt.timedelta(days=1)


def shift_months(day: dt.date, delta: int) -> dt.date:
    month = add_months((day.year, day.month), delta)
    last = month_end(month).day
    return dt.date(month[0], month[1], min(day.day, last))


def iter_months(start: tuple[int, int], end: tuple[int, int]):
    month = start
    while month <= end:
        yield month
        month = add_months(month, 1)


def parse_deal_date(text: str) -> dt.date:
    raw = text.strip()
    if "." in raw:
        year, mon, day = raw.split(".")
        return dt.date(int(year), int(mon), int(day))
    return dt.date.fromisoformat(raw)


def pct(rate: Fraction) -> str:
    """Percent to one decimal, halves away from zero. Display only."""
    tenths = rate * 1000
    sign = -1 if tenths < 0 else 1
    quotient, remainder = divmod(abs(tenths.numerator), tenths.denominator)
    if remainder * 2 >= tenths.denominator:
        quotient += 1
    whole, frac = divmod(quotient, 10)
    prefix = "-" if sign < 0 and quotient else ""
    return f"{prefix}{whole}.{frac}%"


def load_deals(path: Path) -> dict[str, list[dt.date]]:
    grouped: dict[str, list[dt.date]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["xiaoqu", "deal_date"]:
            raise ValueError(f"{path} 表头必须是 xiaoqu,deal_date")
        for line in reader:
            name = (line.get("xiaoqu") or "").strip()
            raw = (line.get("deal_date") or "").strip()
            if not name or not raw:
                raise ValueError(f"{path} 有空行")
            grouped.setdefault(name, []).append(parse_deal_date(raw))
    return grouped


def count_months(dates: list[dt.date], *, before: dt.date | None = None) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = {}
    for day in dates:
        if before is not None and not day < before:
            continue
        key = (day.year, day.month)
        counts[key] = counts.get(key, 0) + 1
    return counts


def lookback_ends(notice: dt.date, months: int = LOOKBACK_MONTHS) -> list[tuple[int, int]]:
    earliest = shift_months(notice, -months)
    cursor = add_months((notice.year, notice.month), -1)
    found: list[tuple[int, int]] = []
    for _ in range(months + 2):
        if month_end(cursor) < earliest:
            break
        if month_end(cursor) < notice:
            found.append(cursor)
        cursor = add_months(cursor, -1)
    found.reverse()
    return found


def _block(counts: dict[tuple[int, int], int], start: tuple[int, int] | None, end: tuple[int, int]) -> dict:
    months = [add_months(end, -2), add_months(end, -1), end]
    payload = {
        "止于": month_key(end),
        "月份": [month_key(month) for month in months],
        "套数": None,
        "状态": "未覆盖",
    }
    if start is None or any(month < start for month in months):
        return payload
    total = sum(counts.get(month, 0) for month in months)
    if any(month > COMPLETE for month in months):
        payload["套数"] = total
        payload["状态"] = "含未完月"
        return payload
    payload["套数"] = total
    payload["状态"] = "可算"
    return payload


def _leg(block: dict, current: int) -> tuple[Fraction | None, str | None]:
    if block["状态"] != "可算":
        return None, block["状态"]
    base = block["套数"]
    if base == 0:
        return None, "基期为0"
    return Fraction(current - base, base), None


def metric_at(counts: dict[tuple[int, int], int], start: tuple[int, int] | None, end: tuple[int, int]) -> dict:
    current = _block(counts, start, end)
    prior = _block(counts, start, add_months(end, -3))
    yoy = _block(counts, start, add_months(end, -12))
    seq_rate = yoy_rate = None
    seq_gap = yoy_gap = None
    label = current["状态"]
    points = 0
    low = mid = False
    if current["状态"] == "可算" and current["套数"] < MIN_COUNT:
        label = "样本不足"
    elif current["状态"] == "可算":
        seq_rate, seq_gap = _leg(prior, current["套数"])
        yoy_rate, yoy_gap = _leg(yoy, current["套数"])
        if seq_rate is None or yoy_rate is None:
            label = "比较段不足"
        else:
            label = "可计算"
            lesser = min(seq_rate, yoy_rate)
            if lesser >= MID:
                points = POINTS_MID
                low = mid = True
            elif lesser >= LOW:
                points = POINTS_LOW
                low = True
    single = _single(seq_rate, yoy_rate)
    return {
        "止于": current["止于"],
        "月份": current["月份"],
        "套数": current["套数"],
        "状态": current["状态"],
        "前3个月": prior,
        "上年同期": yoy,
        "环比": pct(seq_rate) if seq_rate is not None else None,
        "同比": pct(yoy_rate) if yoy_rate is not None else None,
        "环比缺口": seq_gap,
        "同比缺口": yoy_gap,
        "较低增速": pct(min(seq_rate, yoy_rate)) if seq_rate is not None and yoy_rate is not None else None,
        "标签": label,
        "量价分": points,
        "低档": low,
        "中档": mid,
        "单腿": single,
    }


def _single(seq_rate: Fraction | None, yoy_rate: Fraction | None) -> str:
    bits = []
    for name, rate in (("环比", seq_rate), ("同比", yoy_rate)):
        if rate is None:
            continue
        if rate >= MID:
            bits.append(f"{name}过8%")
        elif rate >= LOW:
            bits.append(f"{name}过5%")
    return "、".join(bits)


def _high(rows: list[dict]) -> bool:
    inside = any(row.get("匹配") in INSIDE and row.get("公告类型") in HIGH_KINDS for row in rows)
    edge = any(row.get("匹配") == "贴边" and row.get("公告类型") == "决定" for row in rows)
    return inside and edge


def _edge(rows: list[dict]) -> bool:
    edge = any(row.get("匹配") == "贴边" and row.get("公告类型") in {"冻结", "决定"} for row in rows)
    inside = any(
        row.get("匹配") in INSIDE and row.get("公告类型") in EXCLUDED_KINDS | HIGH_KINDS for row in rows
    )
    return edge and not inside


def _real_rows(scored: dict) -> list[dict]:
    return [row for row in scored.get("证据") or [] if not row.get("假阳性")]


def assign_tier(scored: dict, current: dict | None, *, block_volume: bool) -> tuple[str, str]:
    """Public tier from the current window. Lookback does not change it."""
    if scored.get("排除"):
        return "未分档", f"排除：{scored['排除']}。已冻结、已决定、已签约、已腾退不排档。"
    rows = _real_rows(scored)
    if not rows and scored.get("假阳性"):
        return "未分档", "假阳性（收储、成套改造、市政冻结、学区或对倒），不作为征收信号。"
    if not rows:
        return "未分档", "没有可匹配的程序证据。"
    if scored.get("硬过滤") == "未知":
        return "未分档", "硬过滤未知：户数或套均没有公开的纯数字，不排档。公告前的量能线不改变这一档。"
    if scored.get("硬过滤") != "通过":
        return "未分档", "硬过滤未通过：需要户数>50且套均≤70㎡，不排档。"
    if _high(rows):
        return "高", "两清或准动迁挂牌，并且贴边地块已有征收决定。"
    if all(row.get("公告类型") == "征询" for row in rows):
        return "未分档", "纯征询不升高。"
    edge = _edge(rows)
    if block_volume:
        if edge:
            return "未分档", "贴边地块处于冻结或决定。成交口径待核或套数不能用，不据此升为中。"
        return "未分档", "成交口径待核，或没有可用的套数，不据此升档。"
    fired_mid = bool(current and current.get("中档"))
    fired_low = bool(current and current.get("低档"))
    label = (current or {}).get("标签") or "没有套数"
    if edge and fired_mid:
        return "中", "贴边地块处于冻结或决定，本小区不在清单内，较低增速达到 8%。"
    if edge:
        return "未分档", f"贴边地块处于冻结或决定，本小区不在清单内。当前为{label}，较低增速没有达到 8%，不升为中。"
    if fired_low:
        return "低", "只有套数增速，较低增速达到 5%。"
    return "未分档", f"当前为{label}，较低增速没有达到 5%，不排入低档。"


def _sum_span(counts, start_coverage, first, last) -> int | None:
    total = 0
    for month in iter_months(first, last):
        if start_coverage is None or month < start_coverage or month > COMPLETE:
            return None
        total += counts.get(month, 0)
    return total


def _six_months(counts, start, notice: dt.date) -> dict:
    end = add_months((notice.year, notice.month), -1)
    first = add_months(end, -5)
    prev_end = add_months(end, -12)
    prev_first = add_months(first, -12)
    return {
        "起": month_key(first),
        "止": month_key(end),
        "套数": _sum_span(counts, start, first, end),
        "上年起": month_key(prev_first),
        "上年止": month_key(prev_end),
        "上年套数": _sum_span(counts, start, prev_first, prev_end),
    }


def _place(month: tuple[int, int], notice: dt.date | None) -> str:
    if month > COMPLETE:
        return "未完月"
    if notice is None:
        return "已采集"
    notice_month = (notice.year, notice.month)
    if month == notice_month:
        return "公告当月"
    if month > notice_month:
        return "公告后"
    return "公告前"


def _series(counts, start, notice: dt.date | None) -> list[dict]:
    rows = []
    for month in iter_months(start, PARTIAL):
        rows.append({"月": month_key(month), "套数": counts.get(month, 0), "位置": _place(month, notice)})
    return rows


def _outside(counts, start) -> list[dict]:
    rows = []
    for month in sorted(key for key in counts if key < start):
        rows.append({"月": month_key(month), "套数": counts[month]})
    return rows


def _lookback_summary(months: list[dict], outside: list[dict]) -> dict:
    low_months = [row["止于"] for row in months if row["低档"]]
    mid_months = [row["止于"] for row in months if row["中档"]]
    only_low = [name for name in low_months if name not in mid_months]
    single = [row for row in months if row["单腿"] and not row["低档"]]
    bits = []
    if mid_months:
        bits.append(f"较低增速在 {'、'.join(mid_months)} 达到 8%。")
    if only_low:
        bits.append(f"较低增速在 {'、'.join(only_low)} 达到 5%，没有达到 8%。")
    if not low_months:
        reached = [row for row in months if row["状态"] == "可算" and isinstance(row["套数"], int) and row["套数"] >= MIN_COUNT]
        if not reached:
            bits.append("公告前 12 个月内，滚动 3 个月套数都不到 8，样本不足，没有触发量能线。")
        else:
            bits.append("有窗口达到 8 套，但两腿不齐，或较低增速没有到 5%，没有触发量能线。")
    if single:
        names = "、".join(row["止于"] for row in single)
        bits.append(f"另有 {len(single)} 个窗口只有一腿过线（{names}），取较低一腿后不触发。")
    if outside:
        shown = "；".join(
            f"{row['止于']} 滚动 {row['套数']} 套（{row['标签']}"
            + (f"，{row['单腿']}" if row["单腿"] else "")
            + "）"
            for row in outside
        )
        bits.append(f"12 个月窗口之前还有达到 8 套的月份：{shown}。这些不计入上面的是否触发。")
    return {
        "低档": bool(low_months),
        "中档": bool(mid_months),
        "低档月": low_months,
        "中档月": mid_months,
        "说明": "".join(bits),
    }


def _slim(row: dict) -> dict:
    return {
        "公告类型": row.get("公告类型"),
        "匹配": row.get("匹配"),
        "来源日期": row.get("来源日期"),
        "来源URL": row.get("来源URL"),
        "项目名": row.get("项目名"),
        "文号": row.get("文号"),
    }


def _hot_outside(counts, start, notice, ends) -> list[dict]:
    if start is None or not ends:
        return []
    hot = []
    cursor = add_months(start, 2)
    while cursor < ends[0]:
        if month_end(cursor) < notice:
            row = metric_at(counts, start, cursor)
            if isinstance(row["套数"], int) and row["套数"] >= MIN_COUNT:
                hot.append(row)
        cursor = add_months(cursor, 1)
    return hot


def _split_notice_month(dates: list[dt.date], notice: dt.date) -> tuple[list[str], list[str]]:
    before, after = [], []
    for day in dates:
        if (day.year, day.month) != (notice.year, notice.month):
            continue
        (before if day < notice else after).append(day.isoformat())
    return before, after


def build_community(scored: dict, deals: dict[str, list[dt.date]]) -> dict:
    name = scored.get("小区") or ""
    coverage = COVERAGE.get(name, UNCOLLECTED)
    dates = deals.get(name, [])
    if dates and coverage["状态"] != "已采集":
        raise ValueError(f"{name} 不应同时出现在原始成交里和「{coverage['状态']}」")
    notice = dt.date.fromisoformat(scored["来源日期"]) if scored.get("来源日期") else None
    start = coverage["起"]
    future = [day for day in dates if (day.year, day.month) > PARTIAL]
    if future:
        raise ValueError(f"{name} 有采集日之后的成交 {future[0].isoformat()}")
    all_counts = count_months(dates)
    current = metric_at(all_counts, start, COMPLETE) if start else None
    block_volume = coverage["状态"] != "已采集" or bool(coverage["口径"])
    tier, reason = assign_tier(scored, current, block_volume=block_volume)
    evidence = [_slim(row) for row in scored.get("证据") or []]
    primary = next((row for row in evidence if row.get("来源日期") == scored.get("来源日期")), evidence[0] if evidence else {})
    community = {
        "小区": name,
        "区": scored.get("区"),
        "档位": tier,
        "档位说明": reason,
        "程序": scored.get("程序") if isinstance(scored.get("程序"), int) else None,
        "结构": None,
        "硬过滤": scored.get("硬过滤"),
        "匹配": scored.get("匹配"),
        "公告类型": scored.get("公告类型"),
        "公告日期": scored.get("来源日期"),
        "来源URL": scored.get("来源URL"),
        "项目名": primary.get("项目名"),
        "文号": primary.get("文号"),
        "证据": evidence,
        "成交状态": coverage["状态"],
        "采集说明": coverage["说明"],
        "口径备注": coverage["口径"],
        "采集条数": len(dates),
        "窗口起": month_key(start) if start else None,
        "月度": _series(all_counts, start, notice) if start else [],
        "窗口外": _outside(all_counts, start) if start else [],
        "当前": current,
        "回看": None,
    }
    if start and notice is not None:
        pre = count_months(dates, before=notice)
        ends = lookback_ends(notice)
        months = [metric_at(pre, start, end) for end in ends]
        outside = _hot_outside(pre, start, notice, ends)
        summary = _lookback_summary(months, outside)
        before, after = _split_notice_month(dates, notice)
        community["回看"] = {
            "起": month_key(ends[0]) if ends else None,
            "止": month_key(ends[-1]) if ends else None,
            **summary,
            "月份": months,
            "窗外": outside,
            "六个月": _six_months(pre, start, notice),
            "公告当月之前": before,
            "公告当月及之后": after,
        }
    return community


def _finished(row: dict) -> list[int]:
    return [item["套数"] for item in row["月度"] if item["位置"] != "未完月"]


def _flag_phrase(row: dict) -> str:
    if row["中档"]:
        return "过了 8%"
    if row["低档"]:
        return "过了 5%，没有过 8%"
    return "按规则不触发"


def _conclusion(rows: list[dict]) -> list[str]:
    named = {row["小区"]: row for row in rows}
    missing = [name for name in BACKTEST if name not in named]
    if missing:
        raise ValueError("样本候选里缺少 " + "、".join(missing))
    five = [named[name] for name in BACKTEST]
    lan = named["兰岭园"]
    fired = [row["小区"] for row in five if row["回看"]["低档"]]
    mid = [row["小区"] for row in five if row["回看"]["中档"]]
    if fired == ["兰岭园"] and not mid:
        first = "按近 3 个月至少 8 套、同比和环比都要能算、再取较低增速的规则，这五处里只有兰岭园在公告前到过 5% 的量能线，没有一处的较低增速到过 8%。"
    elif not fired and not mid:
        first = "按近 3 个月至少 8 套、同比和环比都要能算、再取较低增速的规则，这五处在公告前 12 个月内都没有到过 5% 或 8% 的量能线。"
    else:
        fired_text = "、".join(fired) if fired else "没有"
        mid_text = "、".join(mid) if mid else "没有"
        first = f"按同一套规则，较低增速到过 5% 的是{fired_text}，到过 8% 的是{mid_text}。"

    by_end = {row["止于"]: row for row in lan["回看"]["月份"]}
    march = by_end.get("2026-03")
    january = by_end.get("2026-01")
    if march is None or march["前3个月"]["状态"] != "可算" or march["上年同期"]["状态"] != "可算":
        march_text = "2026-03 这个窗口的两段比较没有齐。"
    else:
        march_text = (
            f"2026 年 1 月至 3 月成交 {march['套数']} 套，前 3 个月 {march['前3个月']['套数']} 套，"
            f"上年同期 {march['上年同期']['套数']} 套，较低增速 {march['较低增速']}，量价分 {march['量价分']}，{_flag_phrase(march)}。"
        )
    jan_text = "2026-01 这个月末不在回看里。"
    heard_jan = ""
    if january is not None and january["前3个月"]["状态"] == "可算":
        notice = dt.date.fromisoformat(lan["公告日期"])
        days = (notice - month_end((2026, 1))).days
        yoy = january["上年同期"]
        yoy_text = "上年同期未覆盖" if yoy["状态"] != "可算" else f"上年同期 {yoy['套数']} 套"
        ratio = f"环比 {january['环比']}" if january["环比"] else "环比没有算出"
        jan_text = (
            f"2025 年 11 月至 2026 年 1 月成交 {january['套数']} 套，前 3 个月 {january['前3个月']['套数']} 套，{ratio}，"
            f"{yoy_text}，{_flag_phrase(january)}，窗口月末距公告日 {days} 天。"
        )
        if january["套数"] == 16 and january["前3个月"]["套数"] == 5:
            heard_jan = "事先听到的「16 套对前 3 个月 5 套」与这个窗口一致。"
        else:
            heard_jan = "事先听到的「16 套对前 3 个月 5 套」与这个窗口不一致。"
    second = f"兰岭园公告日是 {lan['公告日期']}。{march_text}{jan_text}{heard_jan}"

    six = lan["回看"]["六个月"]
    six_text = (
        f"公告前 6 个完整月（{six['起']} 至 {six['止']}）是 {six['套数']} 套，"
        f"上年同期（{six['上年起']} 至 {six['上年止']}）是 {six['上年套数']} 套。"
    )
    if six["套数"] == 15 and six["上年套数"] == 16:
        six_text += "事先听到的「15 对 16」与这个计数一致。"
    elif six["套数"] is not None and six["上年套数"] is not None:
        six_text += "事先听到的「15 对 16」与这个计数不一致。"
    peaks = []
    peak_values = []
    for name in BACKTEST[1:]:
        counts = [item["套数"] for item in named[name]["回看"]["月份"] if isinstance(item["套数"], int)]
        peak = max(counts) if counts else 0
        peak_values.append(peak)
        peaks.append(f"{name} {peak} 套")
    under = "，都不到 8 套" if peak_values and all(value < MIN_COUNT for value in peak_values) else ""
    finished = _finished(lan)
    small = sum(1 for value in finished if value <= 2)
    magnitude = (
        f"兰岭园 {len(finished)} 个已结束的覆盖月里，单月最多 {max(finished)} 套，"
        f"其中 {small} 个月不超过 2 套，并不是每个月都只有 1 到 2 套。"
    )
    third = (
        six_text
        + f"其余四处在公告前 12 个月的滚动峰值是 {'、'.join(peaks)}{under}。"
        + magnitude
        + named["珠江香樟北园"]["口径备注"]
    )

    current = lan["当前"]
    unknown = all(row["硬过滤"] == "未知" for row in five)
    filter_text = "这五处的户数或套均都没有公开纯数字，硬过滤是未知，公开档位全部是未分档。" if unknown else "公开档位见各小区的硬过滤和程序。"
    tail = "页面档位用的是这个当前窗口。"
    if lan["回看"]["低档"]:
        tail = "页面档位用的是这个当前窗口，不用公告前到过的 5% 线去改今天的档。"
    fourth = (
        filter_text
        + f"当前窗口止于 {current['止于']}，兰岭园近 3 个月 {current['套数']} 套，{current['标签']}。"
        + tail
    )
    return [first, second, third, fourth]


def build_document(root: Path) -> dict:
    root = root.resolve()
    deals = load_deals(root / "data" / "prediction" / "ke_deals_raw.csv")
    sample = json.loads((root / "samples" / "m2" / "sample.json").read_text(encoding="utf-8"))
    communities = [build_community(row, deals) for row in sample.get("候选") or []]
    present = {row["小区"] for row in communities}
    for name in (*BACKTEST, *ALSO_COLLECTED):
        if name not in present:
            raise ValueError(f"样本候选里没有 {name}")
    excluded = []
    for row in sample.get("全部小区") or []:
        if not row.get("排除"):
            continue
        excluded.append(
            {
                "小区": row.get("小区"),
                "区": row.get("区"),
                "排除": row.get("排除"),
                "来源日期": row.get("来源日期"),
                "来源URL": row.get("来源URL"),
            }
        )
    return {
        "更新日": COLLECTED_ON.isoformat(),
        "标题": "沪拆信号 · 小区",
        "免责声明": DISCLAIMER,
        "当前窗口": month_key(COMPLETE),
        "未完月": month_key(PARTIAL),
        "采集日": COLLECTED_ON.isoformat(),
        "原始行数": sum(len(days) for days in deals.values()),
        "规则": list(RULES),
        "来源": [
            {"名称": "成交套数", "说明": DEAL_SOURCE},
            {
                "名称": "程序公告",
                "说明": "上海市人民政府公文库公开检索，以及杨浦区房屋征收栏目里已经打开的公告页。链接用样本中的来源 URL。",
            },
        ],
        "生成说明": "由 huchai.volume 从 data/prediction/ke_deals_raw.csv 和 samples/m2/sample.json 生成，不要手改数字。",
        "结论": _conclusion(communities),
        "小区": communities,
        "已排除": excluded,
    }


def dump_text(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def _cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "/").replace("\n", " ")


def _count_cell(block: dict) -> str:
    if block.get("状态") != "可算":
        return _cell(block.get("状态"))
    return _cell(block.get("套数"))


def _span(months: list[str]) -> str:
    if not months:
        return ""
    return f"{months[0]}至{months[-1]}"


def _metric_table(months: list[dict]) -> list[str]:
    lines = [
        "| 止于 | 近3个月 | 套数 | 前3个月 | 上年同期 | 环比 | 同比 | 较低增速 | 标签 | 量价分 | 5%线 | 8%线 | 单腿 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in months:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(row["止于"]),
                    _cell(_span(row["月份"])),
                    _count_cell(row),
                    _count_cell(row["前3个月"]),
                    _count_cell(row["上年同期"]),
                    _cell(row["环比"]),
                    _cell(row["同比"]),
                    _cell(row["较低增速"]),
                    _cell(row["标签"]),
                    _cell(row["量价分"]),
                    "是" if row["低档"] else "否",
                    "是" if row["中档"] else "否",
                    _cell(row["单腿"] or "无"),
                ]
            )
            + " |"
        )
    return lines


def _month_table(rows: list[dict]) -> list[str]:
    lines = ["| 月 | 套数 | 位置 |", "| --- | --- | --- |"]
    for row in rows:
        lines.append(f"| {_cell(row['月'])} | {_cell(row['套数'])} | {_cell(row['位置'])} |")
    return lines


def _outside_table(rows: list[dict]) -> list[str]:
    if not rows:
        return ["窗口之前没有单列的成交。"]
    lines = ["窗口之前只单列有成交的月份，相邻月份未覆盖，不记为 0。", "", "| 月 | 套数 |", "| --- | --- |"]
    for row in rows:
        lines.append(f"| {_cell(row['月'])} | {_cell(row['套数'])} |")
    return lines


def _notice_month_sentence(row: dict) -> str:
    look = row["回看"]
    before = "、".join(look["公告当月之前"]) or "无"
    after = "、".join(look["公告当月及之后"]) or "无"
    return f"公告当月在公告日之前的日期：{before}。公告当日及之后：{after}。这些不进入回看窗口。"


def _community_section(row: dict) -> list[str]:
    program = "未计" if row["程序"] is None else str(row["程序"])
    lines = [
        f"## {row['小区']}（{row['区']}）",
        "",
        f"- 公告日：{row['公告日期']}。这是样本里该小区最晚一条证据的日期。",
        f"- 程序 {program}，匹配 {row['匹配']}，公告 {row['公告类型']}，硬过滤 {row['硬过滤']}，档位 {row['档位']}。",
        f"- 档位说明：{row['档位说明']}",
        f"- 来源：{row['来源URL']}",
        f"- 项目：{row['项目名'] or '无'}。文号：{row['文号'] or '无'}。",
        f"- 成交：{row['采集说明']}采集 {row['采集条数']} 条。",
    ]
    if row["口径备注"]:
        lines.append(f"- 口径：{row['口径备注']}")
    lines.extend(["", "### 月度套数", ""])
    lines.extend(_month_table(row["月度"]))
    lines.extend(["", "### 窗口外", ""])
    lines.extend(_outside_table(row["窗口外"]))
    look = row["回看"]
    lines.extend(["", "### 公告前 12 个月", "", look["说明"], "", _notice_month_sentence(row), ""])
    six = look["六个月"]
    lines.append(
        f"公告前 6 个完整月（{six['起']} 至 {six['止']}）{six['套数']} 套；"
        f"上年同期（{six['上年起']} 至 {six['上年止']}）{six['上年套数']} 套。这不是打分用的 3 个月指标。"
    )
    lines.extend(["", "5% 线在 8% 线成立时也记「是」，因为 8% 已经超过 5%。触发与否看精确分数，不看四舍五入后的百分数。", ""])
    lines.extend(_metric_table(look["月份"]))
    if look["窗外"]:
        lines.extend(["", "### 回看窗之前达到 8 套的窗口", ""])
        lines.extend(_metric_table(look["窗外"]))
    lines.append("")
    return lines


def _short_collected(row: dict) -> list[str]:
    lines = [f"### {row['小区']}", "", row["采集说明"], ""]
    if row["口径备注"]:
        lines.append(row["口径备注"])
        lines.append("")
    if row["回看"] is None:
        lines.append(f"成交状态：{row['成交状态']}。没有月度序列。采集 {row['采集条数']} 条。")
        lines.append("")
        return lines
    counts = [item["套数"] for item in row["回看"]["月份"] if isinstance(item["套数"], int)]
    peak = max(counts) if counts else 0
    current = row["当前"]
    lines.append(
        f"采集 {row['采集条数']} 条。公告日 {row['公告日期']}。"
        f"公告前 12 个月滚动套数最多 {peak} 套，量能线{'有触发' if row['回看']['低档'] or row['回看']['中档'] else '没有触发'}。"
        f"当前窗口止于 {current['止于']}，近 3 个月 {current['套数']} 套，{current['标签']}。"
    )
    if row["窗口外"]:
        shown = "、".join(f"{item['月']} {item['套数']} 套" for item in row["窗口外"])
        lines.append(f"窗口外：{shown}。")
    lines.append("")
    return lines


def render_backtest(document: dict) -> str:
    named = {row["小区"]: row for row in document["小区"]}
    lines = [
        "# 套数回测",
        "",
        f"生成日：{document['更新日']}。下面的数字由 `huchai.volume` 从 `data/prediction/ke_deals_raw.csv`（{document['原始行数']} 行）和 `samples/m2/sample.json` 算出，没有另填套数，也没有价格。",
        "",
        "## 结论",
        "",
    ]
    for paragraph in document["结论"]:
        lines.append(paragraph)
        lines.append("")
    lines.extend(["## 规则", ""])
    for rule in document["规则"]:
        lines.append(f"- {rule}")
    lines.extend(["", "## 五处回看", ""])
    for name in BACKTEST:
        lines.extend(_community_section(named[name]))
    lines.extend(["## 同一批采集里的其他名字", ""])
    for name in ALSO_COLLECTED:
        lines.extend(_short_collected(named[name]))
    untouched = [row["小区"] for row in document["小区"] if row["小区"] not in BACKTEST and row["小区"] not in ALSO_COLLECTED]
    lines.extend(["## 候选里这次没有检索的小区", ""])
    lines.append("、".join(untouched) if untouched else "无。")
    lines.append("")
    if document["已排除"]:
        lines.extend(["已排除、没有放进候选的小区："])
        lines.append("")
        for row in document["已排除"]:
            lines.append(f"- {row['小区']}（{row['区']}）{row['排除']}，{row['来源日期']}，{row['来源URL']}")
        lines.append("")
    lines.append(document["免责声明"])
    lines.append("")
    return "\n".join(lines)


def write_volume_artifacts(root: Path) -> tuple[Path, Path]:
    root = root.resolve()
    document = build_document(root)
    data = root / "site" / "tiers" / "data.json"
    report = root / "samples" / "m2" / "volume_backtest.md"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(dump_text(document), encoding="utf-8")
    report.write_text(render_backtest(document), encoding="utf-8")
    return data, report
