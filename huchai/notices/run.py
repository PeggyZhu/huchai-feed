"""Run M2 collection and write the private sample."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from huchai.notices.collect import collect_notices, evidence_from_notice
from huchai.notices.http import UrllibNoticeTransport
from huchai.notices.report import build_sample, write_sample


def default_window(today: dt.date) -> tuple[dt.date, dt.date]:
    month = today.month
    year = today.year - 2
    return dt.date(year, month, today.day), today


def run_notices(
    root: Path,
    out: Path,
    *,
    since: dt.date | None = None,
    until: dt.date | None = None,
    interval: float = 1.2,
    transport=None,
    sleep=None,
) -> int:
    today = until or dt.date.today()
    start = since or default_window(today)[0]
    if start > today:
        raise ValueError("窗口起日晚于止日")
    if transport is None:
        transport = UrllibNoticeTransport()
    kwargs = {"since": start, "until": today, "interval": interval}
    if sleep is not None:
        kwargs["sleep"] = sleep
    notices, logs = collect_notices(transport, **kwargs)
    evidence = [row for notice in notices for row in evidence_from_notice(notice)]
    sample = build_sample(
        notices,
        evidence,
        logs,
        since=start.isoformat(),
        until=today.isoformat(),
        generated=dt.date.today().isoformat(),
    )
    sample["公告"] = [_notice_brief(notice) for notice in notices]
    sample["证据"] = evidence
    written = write_sample(root, out, sample)
    cover = sample["覆盖"]
    print(
        f"notices: 公告 {cover['公告数']}，小区 {cover['匹配到小区']}，"
        f"候选 {cover['未排除候选']}，跳过 {cover['跳过条数']}。样本在 {written}。"
    )
    print("已覆盖区：" + "、".join(cover["已覆盖区"]))
    if cover["公告数"] == 0:
        print("没有抓到可解析的公告，不把空表当成样本数据。")
        return 1
    return 0


def _notice_brief(notice: dict) -> dict:
    brief = dict(notice)
    brief["地址数"] = len(notice.get("地址") or [])
    brief["匹配数"] = len(notice.get("匹配") or [])
    return brief


def dumps_logs(logs: list[dict]) -> str:
    return json.dumps(logs, ensure_ascii=False, indent=2)
