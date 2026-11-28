"""Command line for crawling, building, and previewing."""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import http.server
import sys
from pathlib import Path

from huchai.build_site import build_site
from huchai.crawl import run_crawl
from huchai.errors import SourceBlocked, SourceError
from huchai.ingest import run_import
from huchai.notices.run import run_notices
from huchai.volume import write_volume_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="huchai", description="沪拆信号：上海二手房网签快照")
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="抓取昨日二手房网签，有变化才写入快照")
    crawl.add_argument("--root", type=Path, default=Path("."))
    crawl.add_argument("--dry-run", action="store_true", help="请求并打印结果，不写文件")
    crawl.add_argument("--fixture", type=Path, help="用本地 JSON 代替网络请求")
    crawl.add_argument("--now", help="抓取日，上海日期 YYYY-MM-DD；默认是今天")

    incoming = sub.add_parser("import", help="用维护者录入的套数或 JSON 更新快照，不访问源站")
    incoming.add_argument("--root", type=Path, default=Path("."))
    incoming.add_argument("--dry-run", action="store_true", help="打印将写入的快照，不写文件")
    incoming.add_argument("--now", help="写入日，上海日期 YYYY-MM-DD；默认是今天")
    incoming.add_argument("--deals", type=int, help="成交套数")
    incoming.add_argument("--date", help="成交日 YYYY-MM-DD。和 --deals 一起用，不会默认成昨天")
    incoming.add_argument("--area", type=float, help="成交面积（平方米），可省略")
    incoming.add_argument("--file", type=Path, help="JSON：单日、数组，或带 daily/days/observations 的快照")

    build = sub.add_parser("build", help="生成 dist/ 静态站点")
    build.add_argument("--root", type=Path, default=Path("."))
    build.add_argument("--out", type=Path, default=Path("dist"))

    preview = sub.add_parser("preview", help="生成并在本机预览")
    preview.add_argument("--root", type=Path, default=Path("."))
    preview.add_argument("--port", type=int, default=8765)

    notices = sub.add_parser("notices", help="抓取公开征收公告，写出不公开的 M2 样本")
    notices.add_argument("--root", type=Path, default=Path("."))
    notices.add_argument("--out", type=Path, default=Path("samples/m2"))
    notices.add_argument("--since", help="窗口起日 YYYY-MM-DD，默认今天往前 24 个月")
    notices.add_argument("--until", help="窗口止日 YYYY-MM-DD，默认今天")
    notices.add_argument("--interval", type=float, default=1.2, help="请求间隔秒数")

    volume = sub.add_parser("volume", help="从贝壳套数和 M2 样本生成小区页数据与回测")
    volume.add_argument("--root", type=Path, default=Path("."))

    args = parser.parse_args(argv)
    try:
        if args.command == "crawl":
            today = dt.date.fromisoformat(args.now) if args.now else None
            return run_crawl(args.root, dry_run=args.dry_run, fixture=args.fixture, now=today)
        if args.command == "import":
            today = dt.date.fromisoformat(args.now) if args.now else None
            return run_import(
                args.root,
                dry_run=args.dry_run,
                now=today,
                deals=args.deals,
                trade_date=args.date,
                area=args.area,
                file=args.file,
            )
        if args.command == "build":
            print(build_site(args.root, args.out))
            return 0
        if args.command == "notices":
            since = dt.date.fromisoformat(args.since) if args.since else None
            until = dt.date.fromisoformat(args.until) if args.until else None
            return run_notices(args.root, args.out, since=since, until=until, interval=args.interval)
        if args.command == "volume":
            data_path, report_path = write_volume_artifacts(args.root)
            print(data_path)
            print(report_path)
            return 0
        return _preview(args.root, args.port)
    except SourceBlocked as exc:
        print(exc, file=sys.stderr)
        return 2
    except (SourceError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _preview(root: Path, port: int) -> int:
    out = build_site(root, root / "dist")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"http://127.0.0.1:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
