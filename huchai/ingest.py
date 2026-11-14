"""Record a net-sign total the maintainer read themselves.

This path does not contact fangdi.com.cn and does not touch the anti-bot
challenge. It folds the supplied days through the same merge as a crawl,
then publishes once.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from huchai.merge import merge_observation
from huchai.parse import COUNT_KEYS, DATE_KEYS, parse_observation
from huchai.snapshot import assert_preserves, dump, load_json, publish_latest, validate_snapshot

SHANGHAI = ZoneInfo("Asia/Shanghai")
IMPORT_NOTE = "含商业、车位。由维护者录入的网上房地产二手房网签，不是本次自动抓取。"
IMPORT_SOURCE = "网上房地产（维护者录入的二手房网签，含商业、车位）"
SERIES_KEYS = ("daily", "days", "observations")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def run_import(
    root: Path,
    *,
    dry_run: bool = False,
    now: dt.date | None = None,
    deals: int | None = None,
    trade_date: str | None = None,
    area: float | None = None,
    file: Path | None = None,
) -> int:
    root = root.resolve()
    today = now or dt.datetime.now(SHANGHAI).date()
    observations = collect_observations(
        today=today,
        deals=deals,
        trade_date=trade_date,
        area=area,
        file=file,
    )
    current = load_json(root / "fangdi.json")
    validate_snapshot(current)

    merged = current
    changed_any = False
    for observation in sorted(observations, key=lambda item: item.date):
        shown = "—" if observation.area is None else observation.area
        print(f"import {observation.date} deals={observation.deals} area={shown}")
        merged, changed = merge_observation(
            merged,
            observation,
            updated=today.isoformat(),
            origin="manual",
            note=IMPORT_NOTE,
            source_name=IMPORT_SOURCE,
            ingest="import",
        )
        changed_any = changed_any or changed

    if not changed_any:
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


def collect_observations(
    *,
    today: dt.date,
    deals: int | None,
    trade_date: str | None,
    area: float | None,
    file: Path | None,
) -> list:
    has_file = file is not None
    has_deals = deals is not None
    if has_file and (has_deals or trade_date or area is not None):
        raise ValueError("`--file` 和 `--deals` / `--date` / `--area` 只能用一种")
    if has_file:
        return observations_from_payload(_read_json(file), today=today)
    if not has_deals:
        raise ValueError("请提供 --deals 和 --date，或提供 --file")
    if not trade_date:
        raise ValueError("填写成交套数时必须同时给出成交日：--date YYYY-MM-DD")
    if not _ISO_DATE.fullmatch(trade_date):
        raise ValueError(f"成交日必须是 YYYY-MM-DD，收到 {trade_date!r}")
    try:
        dt.date.fromisoformat(trade_date)
    except ValueError as exc:
        raise ValueError(f"成交日不是有效日期：{trade_date}") from exc
    payload: dict = {"deals": deals, "date": trade_date}
    if area is not None:
        payload["area"] = area
    observation = parse_observation(payload, today=today)
    if area is not None and observation.area is None:
        raise ValueError("面积不在可用范围（1000 到 5000000 平方米），没有写入")
    return [observation]


def observations_from_payload(payload: object, *, today: dt.date) -> list:
    rows = _rows(payload)
    if not rows:
        raise ValueError("没有可导入的成交日")
    found = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 条不是 JSON 对象")
        found.append(_observation_from_row(row, today=today, index=index))
    return found


def refresh_command(
    deals: str,
    trade_date: str,
    area: str,
    raw: str,
    *,
    json_path: Path,
) -> list[str]:
    """Argv for the Actions refresh job. Empty inputs crawl; supplied inputs import.

    ``raw`` is written to ``json_path`` and never placed on a shell command line.
    """

    deals = deals.strip()
    trade_date = trade_date.strip()
    area = area.strip()
    raw = raw.strip()
    if deals and raw:
        raise ValueError("成交套数和 JSON 只能填一种。")
    if raw:
        if "\n" in raw or "\r" in raw:
            raise ValueError("JSON 必须是一行。多日请写成一行数组。")
        json_path.write_text(raw, encoding="utf-8")
        return ["python3", "-m", "huchai", "import", "--file", str(json_path)]
    if deals or trade_date or area:
        if not deals or not trade_date:
            raise ValueError("填写成交套数时必须同时填写成交日 YYYY-MM-DD。")
        if not deals.isdecimal():
            raise ValueError(f"成交套数必须是整数，收到 {deals!r}")
        command = ["python3", "-m", "huchai", "import", "--deals", deals, "--date", trade_date]
        if area:
            command.extend(["--area", area])
        return command
    return ["python3", "-m", "huchai", "crawl"]


def _read_json(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"导入文件不是合法 JSON：{path.name}") from exc


def _rows(payload: object) -> list:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("导入内容必须是 JSON 对象或数组")
    folded = {str(key).lower(): value for key, value in payload.items()}
    if any(key in folded and folded[key] not in (None, "") for key in COUNT_KEYS):
        return [payload]
    for name in SERIES_KEYS:
        series = payload.get(name)
        if isinstance(series, list):
            return series
    raise ValueError("JSON 里没有成交套数，也没有 daily、days 或 observations 数组")


def _observation_from_row(row: dict, *, today: dt.date, index: int):
    normalized = dict(row)
    lowered = {str(key).lower(): key for key in normalized}
    has_date = False
    for name in DATE_KEYS:
        original = lowered.get(name)
        if original is None:
            continue
        if normalized.get(original) not in (None, ""):
            has_date = True
            break
    if not has_date:
        key_name = lowered.get("key")
        if key_name is not None and normalized.get(key_name) not in (None, ""):
            normalized["date"] = normalized[key_name]
            has_date = True
    if not has_date:
        raise ValueError(f"第 {index} 条没有成交日（date 或 key）。导入不会默认成昨天")
    try:
        return parse_observation(normalized, today=today)
    except ValueError as exc:
        raise ValueError(f"第 {index} 条无法导入：{exc}") from exc
