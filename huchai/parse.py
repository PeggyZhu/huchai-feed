"""Parse the public yesterday-sell payload. No challenge solving."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from huchai.errors import SourceBlocked

COUNT_KEYS = ("sellcount", "count", "deals", "cjts", "signcount", "housecount")
AREA_KEYS = ("sellarea", "area", "cjmj")
AMOUNT_KEYS = ("sellmoney", "totalprice", "cjje", "amount")
DATE_KEYS = ("date", "selldate", "tradedate", "yesterday", "signdate", "countdate")
WRAPPERS = ("data", "result", "obj", "rows")

_DATE = re.compile(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})")


@dataclass(frozen=True)
class Observation:
    date: str
    deals: int
    area: float | None = None
    amount_yuan: float | None = None


def is_challenge(status: int, body: str) -> bool:
    """True when the body is an anti-bot wall rather than a transient 5xx."""

    if status in (401, 403, 412, 418, 429):
        return True
    sample = body[:8000]
    if "$_ts" in sample:
        return True
    lowered = sample.lower()
    if status == 200 and sample.lstrip().startswith("<") and (
        "$_ts" in sample or "precondition failed" in lowered or "access denied" in lowered
    ):
        return True
    return False


def raise_if_blocked(status: int, body: str, url: str) -> None:
    if not is_challenge(status, body):
        return
    marker = "响应里带有 $_ts 挑战脚本" if "$_ts" in body else "没有返回成交 JSON"
    raise SourceBlocked(
        "网上房地产拒绝了这次抓取（反爬拦截，未拿到成交 JSON）。\n"
        "爬虫不会执行挑战脚本，也不会绕过验证。\n"
        "现有 fangdi.json 和 snapshots/ 保持原样。\n"
        "要用浏览器里看到的套数更新，请运行：\n"
        "python3 -m huchai import --deals 套数 --date YYYY-MM-DD\n"
        f"HTTP {status} {url}（{marker}）。"
    )


def parse_observation(payload: object, *, today: dt.date) -> Observation:
    document = _unwrap(payload)
    deals = _as_int(_first(document, COUNT_KEYS), what="deals")
    if deals is None or deals < 1 or deals > 20000:
        raise ValueError(f"implausible or missing deal count: {deals!r}")

    area = _as_float(_first(document, AREA_KEYS))
    if area is not None and not (1000 <= area <= 5_000_000):
        area = None

    amount = _as_float(_first(document, AMOUNT_KEYS))
    if amount is not None and not (1e8 <= amount <= 1e12):
        amount = None
    if amount is not None and area is not None:
        unit = amount / area
        if not (3000 <= unit <= 300000):
            amount = None

    raw_date = _first(document, DATE_KEYS)
    if raw_date is None or raw_date == "":
        trade_date = today - dt.timedelta(days=1)
    else:
        trade_date = _parse_date(str(raw_date))
    if trade_date > today or trade_date.year < 2000:
        raise ValueError(f"observation date {trade_date.isoformat()} is outside the usable range")
    return Observation(trade_date.isoformat(), deals, area, amount)


def _unwrap(payload: object) -> dict:
    if isinstance(payload, list):
        if len(payload) == 1 and isinstance(payload[0], dict):
            return _unwrap(payload[0])
        raise ValueError("refusing an ambiguous list payload")
    if not isinstance(payload, dict):
        raise ValueError("sell payload is not a JSON object")
    folded = {str(key).lower(): value for key, value in payload.items()}
    if any(key in folded for key in COUNT_KEYS):
        return folded
    for name in WRAPPERS:
        inner = folded.get(name)
        if isinstance(inner, dict):
            return _unwrap(inner)
        if isinstance(inner, list) and len(inner) == 1 and isinstance(inner[0], dict):
            return _unwrap(inner[0])
    return folded


def _first(document: dict, keys: tuple[str, ...]) -> object:
    for key in keys:
        if key in document and document[key] not in (None, ""):
            return document[key]
    return None


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text or text.lower() in {"null", "none", "nan", "--", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _as_int(value: object, *, what: str) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    if abs(number - round(number)) > 1e-6:
        raise ValueError(f"{what} is not a whole number: {value!r}")
    return int(round(number))


def _parse_date(value: str) -> dt.date:
    match = _DATE.search(value.strip())
    if not match:
        raise ValueError(f"unrecognized trade date: {value!r}")
    year, month, day = (int(part) for part in match.groups())
    try:
        return dt.date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"unrecognized trade date: {value!r}") from exc
