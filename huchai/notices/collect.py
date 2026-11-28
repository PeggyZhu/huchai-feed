"""Fetch public notices and turn them into evidence rows.

A row is written only after a request returns a body. Failures are logged
and skipped. No address, date, or count is filled in from memory.
"""

from __future__ import annotations

import datetime as dt
import time
from urllib.parse import urlparse

from huchai.notices.http import FetchError
from huchai.notices.parse import analyze_notice, link_lanes


GAZETTE_SEARCH = "https://www.shanghai.gov.cn/gwk/search/data"
GAZETTE_PAGE = "https://www.shanghai.gov.cn/gwk/search/index"
GAZETTE_CONTENT = "https://www.shanghai.gov.cn/gwk/search/content/{id}"
YANGPU_SEARCH = "https://www.shyp.gov.cn/front/api/data/search"
YANGPU_REFERER = "https://www.shyp.gov.cn/zhengwu/zwgk-fwzsyjqgz/"
YANGPU_CHANNEL = "2191"

GAZETTE_QUERIES = (
    "房屋征收决定",
    "房屋征收补偿方案",
    "房屋征收范围",
    "城中村",
)
PAGE_SIZE = 4


def in_window(day: str, since: dt.date, until: dt.date) -> bool:
    try:
        parsed = dt.date.fromisoformat(day)
    except ValueError:
        return False
    return since <= parsed <= until


def evidence_from_notice(notice: dict) -> list[dict]:
    base = {
        "区": notice.get("区"),
        "公告类型": notice.get("公告类型"),
        "假阳性": notice.get("假阳性"),
        "文号": notice.get("文号"),
        "项目名": notice.get("项目名"),
        "来源URL": notice.get("来源URL"),
        "来源日期": notice.get("来源日期"),
        "抓取自": notice.get("抓取自"),
        "标题": notice.get("标题"),
        "状态": "已确认",
        "口径": "程序状态",
    }
    rows = []
    matches = notice.get("匹配") or []
    subjects = [match for match in matches if match.get("匹配") in {"程序内", "部分覆盖"}]
    for match in matches:
        subject = match.get("匹配") in {"程序内", "部分覆盖"}
        rows.append(
            {
                **base,
                "小区": match.get("小区"),
                "匹配": match.get("匹配"),
                "置信度": match.get("置信度"),
                "原始地址": match.get("原始地址") or notice.get("范围原文"),
                "户数": notice.get("户数") if subject else None,
                "户数原文": notice.get("户数原文") if subject else None,
                "套均面积": notice.get("套均面积") if subject else None,
                "套均原文": notice.get("套均原文") if subject else None,
            }
        )
    if subjects:
        return rows
    addresses = notice.get("地址") or []
    if not addresses and notice.get("范围原文"):
        addresses = [{"原文": notice["范围原文"]}]
    for address in addresses:
        raw = address.get("原文")
        if not raw:
            continue
        rows.append(
            {
                **base,
                "小区": None,
                "匹配": "待核",
                "置信度": None,
                "原始地址": raw,
                "户数": None,
                "户数原文": None,
                "套均面积": None,
                "套均原文": None,
            }
        )
    return rows


def dedupe_notices(notices: list[dict]) -> list[dict]:
    kept: list[dict] = []
    seen: dict[str, dict] = {}
    for notice in notices:
        key = _dedupe_key(notice)
        previous = seen.get(key)
        if previous is None:
            seen[key] = notice
            kept.append(notice)
            continue
        extra = notice.get("来源URL")
        if extra and extra != previous.get("来源URL"):
            others = previous.setdefault("另见URL", [])
            if extra not in others:
                others.append(extra)
        if len(notice.get("范围原文") or "") > len(previous.get("范围原文") or ""):
            others = previous.get("另见URL", [])
            if previous.get("来源URL") and previous["来源URL"] not in others:
                others.append(previous["来源URL"])
            notice["另见URL"] = others
            kept[kept.index(previous)] = notice
            seen[key] = notice
    return kept


def _dedupe_key(notice: dict) -> str:
    number = notice.get("文号")
    if number:
        return "文号:" + number
    return "|".join(
        [
            notice.get("区") or "",
            notice.get("来源日期") or "",
            notice.get("标题") or "",
        ]
    )


def collect_notices(transport, *, since: dt.date, until: dt.date, interval: float = 1.2, sleep=time.sleep) -> tuple[list[dict], list[dict]]:
    logs: list[dict] = []
    notices: list[dict] = []
    notices.extend(_gazette(transport, since=since, until=until, interval=interval, sleep=sleep, logs=logs))
    notices.extend(_yangpu(transport, since=since, until=until, interval=interval, sleep=sleep, logs=logs))
    notices = [notice for notice in notices if notice.get("来源日期") and in_window(notice["来源日期"], since, until)]
    notices = dedupe_notices(notices)
    link_lanes(notices)
    return notices, logs


def _pause(interval: float, sleep) -> None:
    if interval > 0:
        sleep(interval)


def _gazette(transport, *, since: dt.date, until: dt.date, interval: float, sleep, logs: list[dict]) -> list[dict]:
    found: list[dict] = []
    seen_ids: set[str] = set()
    years = range(since.year, until.year + 1)
    for keyword in GAZETTE_QUERIES:
        for year in years:
            page = 1
            total = None
            while page <= 40:
                payload = {
                    "pageNo": page,
                    "pageSize": PAGE_SIZE,
                    "keyword": keyword,
                    "unitType": "",
                    "publishDate": "",
                    "indexNo": "",
                    "documentAgency": "",
                    "documentPublishYear": str(year),
                    "documentNum": "",
                    "theme": "",
                }
                try:
                    loaded = transport.post_json(GAZETTE_SEARCH, payload, referer=GAZETTE_PAGE)
                except FetchError as exc:
                    logs.append({"来源": GAZETTE_SEARCH, "关键词": keyword, "年份": year, "页": page, "结果": "跳过", "原因": exc.reason})
                    if total is None:
                        break
                    page += 1
                    if (page - 1) * PAGE_SIZE >= total:
                        break
                    _pause(interval, sleep)
                    continue
                page_body = loaded.get("page") if isinstance(loaded, dict) else None
                rows = page_body.get("list") if isinstance(page_body, dict) else None
                if not isinstance(rows, list) or not rows:
                    logs.append({"来源": GAZETTE_SEARCH, "关键词": keyword, "年份": year, "页": page, "结果": "空页"})
                    break
                kept_on_page = 0
                for item in rows:
                    if not isinstance(item, dict):
                        continue
                    notice_id = item.get("id")
                    if not isinstance(notice_id, str) or notice_id in seen_ids:
                        continue
                    seen_ids.add(notice_id)
                    title = item.get("title") or ""
                    text = item.get("txt") or ""
                    if not isinstance(title, str) or not isinstance(text, str) or not text.strip():
                        logs.append({"来源": GAZETTE_CONTENT.format(id=notice_id), "结果": "跳过", "原因": "检索结果没有正文"})
                        continue
                    url = GAZETTE_CONTENT.format(id=notice_id)
                    notice = analyze_notice(
                        title=title,
                        text=text,
                        url=url,
                        published=item.get("publish_date") if isinstance(item.get("publish_date"), str) else None,
                        district=item.get("agency") if isinstance(item.get("agency"), str) else None,
                        fetched_via=GAZETTE_SEARCH,
                    )
                    if notice is None:
                        logs.append({"来源": url, "结果": "跳过", "原因": "不是项目公告或没有发布日期", "标题": title[:80]})
                        continue
                    if not in_window(notice["来源日期"], since, until):
                        continue
                    found.append(notice)
                    kept_on_page += 1
                count = page_body.get("count") if isinstance(page_body, dict) else None
                if isinstance(count, int):
                    total = count
                logs.append(
                    {
                        "来源": GAZETTE_SEARCH,
                        "关键词": keyword,
                        "年份": year,
                        "页": page,
                        "结果": "已抓取",
                        "本页保留": kept_on_page,
                        "接口总数": count,
                    }
                )
                if not isinstance(count, int) or page * PAGE_SIZE >= count:
                    break
                page += 1
                _pause(interval, sleep)
            _pause(interval, sleep)
    return found


def _yangpu(transport, *, since: dt.date, until: dt.date, interval: float, sleep, logs: list[dict]) -> list[dict]:
    found: list[dict] = []
    page = 1
    while page <= 40:
        payload = {
            "channelList": [YANGPU_CHANNEL],
            "pageSize": 15,
            "pageNo": page,
            "orderFields": ["display_date", "id"],
            "orderTypes": ["desc", "desc"],
        }
        try:
            loaded = transport.post_json(YANGPU_SEARCH, payload, referer=YANGPU_REFERER)
        except FetchError as exc:
            logs.append({"来源": YANGPU_SEARCH, "页": page, "结果": "跳过", "原因": exc.reason})
            break
        data = loaded.get("data") if isinstance(loaded, dict) else None
        rows = data.get("list") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows:
            logs.append({"来源": YANGPU_SEARCH, "页": page, "结果": "空页"})
            break
        oldest: dt.date | None = None
        for item in rows:
            if not isinstance(item, dict):
                continue
            day = _millis_date(item.get("display_date"))
            if day is None:
                logs.append({"来源": item.get("url"), "结果": "跳过", "原因": "列表没有发布日期", "标题": item.get("title")})
                continue
            oldest = day if oldest is None or day < oldest else oldest
            if not (since <= day <= until):
                continue
            url = item.get("url")
            title = item.get("title") or ""
            if not isinstance(url, str) or urlparse(url).scheme not in {"http", "https"}:
                logs.append({"来源": YANGPU_SEARCH, "结果": "跳过", "原因": "列表没有公告 URL", "标题": title})
                continue
            _pause(interval, sleep)
            try:
                html = transport.get_text(url, referer=YANGPU_REFERER)
            except FetchError as exc:
                logs.append({"来源": url, "结果": "跳过", "原因": exc.reason, "标题": title})
                continue
            notice = analyze_notice(
                title=title if isinstance(title, str) else "",
                text=html,
                url=url,
                published=day.isoformat(),
                district="杨浦区",
                fetched_via=url,
            )
            if notice is None:
                logs.append({"来源": url, "结果": "跳过", "原因": "不是项目公告或没有发布日期", "标题": title})
                continue
            found.append(notice)
        total_page = data.get("totalPage") if isinstance(data, dict) else None
        logs.append({"来源": YANGPU_SEARCH, "页": page, "结果": "已抓取", "本页保留": None})
        if oldest is not None and oldest < since:
            break
        if not isinstance(total_page, int) or page >= total_page:
            break
        page += 1
        _pause(interval, sleep)
    return found


def _millis_date(value: object) -> dt.date | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        shanghai = dt.timezone(dt.timedelta(hours=8))
        return dt.datetime.fromtimestamp(value / 1000, shanghai).date()
    except (OverflowError, OSError, ValueError):
        return None
