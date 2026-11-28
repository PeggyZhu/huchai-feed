"""Write the M2 sample outside the published site and the formal ledger."""

from __future__ import annotations

import json
from pathlib import Path

from huchai.notices.parse import DISTRICTS
from huchai.notices.score import PRICE_MARK, rank_communities, score_community


BANNED_DIRS = ("site", "dist", "snapshots", "data/prediction")


def assert_private_output(root: Path, out: Path) -> None:
    root = root.resolve()
    out = out.resolve()
    if out == root:
        raise ValueError("样本不能写在仓库根目录")
    for relative in BANNED_DIRS:
        banned = (root / relative).resolve()
        if out == banned or banned in out.parents or out in banned.parents:
            raise ValueError(f"样本不能写入公开或正式台账路径 {relative}")


def build_sample(notices: list[dict], evidence: list[dict], logs: list[dict], *, since: str, until: str, generated: str) -> dict:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in evidence:
        name = row.get("小区")
        district = row.get("区")
        if not name or not district or row.get("匹配") == "待核":
            continue
        grouped.setdefault((district, name), []).append(row)
    scored = [score_community(rows) for rows in grouped.values()]
    ranked = rank_communities(scored)
    districts = sorted({notice.get("区") for notice in notices if notice.get("区") in DISTRICTS})
    skipped = [item for item in logs if item.get("结果") == "跳过"]
    return {
        "数据性质": "M2样本",
        "说明": (
            "由已抓取的公开公告生成。不是观察池，不进入 GitHub Pages，也不写入 data/prediction 正式表。"
            "分档只使用程序证据；结构分没有公开点表，记为 null。量价为 N/A (M3)。"
            "户数或套均未知时硬过滤为未知，不排入高、中、低。"
        ),
        "生成日期": generated,
        "窗口": {"起": since, "止": until},
        "分档依据": "程序。结构仅在公开纯数字存在时记入户数和套均，不另计结构分。量价 " + PRICE_MARK + "。",
        "覆盖": {
            "已覆盖区": districts,
            "窗口内无公告的区": [name for name in DISTRICTS if name not in districts],
            "公告数": len(notices),
            "证据行数": len(evidence),
            "匹配到小区": len(scored),
            "未排除候选": len(ranked),
            "已排除": sum(1 for row in scored if row.get("排除")),
            "待核地址行": sum(1 for row in evidence if row.get("匹配") == "待核"),
            "跳过条数": len(skipped),
        },
        "候选": ranked,
        "全部小区": scored,
        "跳过": skipped,
    }


def render_markdown(sample: dict) -> str:
    cover = sample["覆盖"]
    lines = [
        "# M2 公告匹配样本",
        "",
        sample["说明"],
        "",
        f"- 生成日期：{sample['生成日期']}",
        f"- 窗口：{sample['窗口']['起']} 至 {sample['窗口']['止']}",
        f"- 分档依据：{sample['分档依据']}",
        f"- 公告 {cover['公告数']} 条，证据行 {cover['证据行数']}，匹配到小区 {cover['匹配到小区']}，未排除候选 {cover['未排除候选']}，待核地址行 {cover['待核地址行']}。",
        "",
        "## 覆盖",
        "",
        "已抓到公告的区：" + ("、".join(cover["已覆盖区"]) if cover["已覆盖区"] else "无"),
        "",
        "窗口内没有抓到项目公告的区：" + ("、".join(cover["窗口内无公告的区"]) if cover["窗口内无公告的区"] else "无"),
        "",
        "## 候选（按程序分）",
        "",
        "下表是未排除的匹配小区，程序分高的在前。贴边但公告只确认了征收范围、还没有冻结或决定的，程序分留空。档位按已确认规则：高要两清或准动迁挂牌并且贴边已有征收决定；中要贴边冻结或决定加超额涨幅；低只要超额涨幅。量价未建，中和低都不升。硬过滤未知或未通过也不排档。",
        "",
        "| 小区 | 区 | 程序 | 量价 | 结构 | 硬过滤 | 档位 | 匹配 | 公告 | 日期 | 原始地址 | 来源 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    rows = sample["候选"][:15]
    if not rows:
        lines.append("| （无） |  |  |  |  |  |  |  |  |  |  |  |")
    for row in rows:
        lines.append(
            "| {name} | {district} | {program} | {price} | {structure} | {hard} | {tier} | {match} | {kind} | {day} | {raw} | {url} |".format(
                name=_cell(row.get("小区")),
                district=_cell(row.get("区")),
                program=_cell(row.get("程序")),
                price=_cell(row.get("量价")),
                structure="未计",
                hard=_cell(row.get("硬过滤")),
                tier=_cell(row.get("档位") or "未分档"),
                match=_cell(row.get("匹配")),
                kind=_cell(row.get("公告类型")),
                day=_cell(row.get("来源日期")),
                raw=_cell(row.get("原始地址"), limit=40),
                url=_cell(row.get("来源URL")),
            )
        )
    lines.extend(
        [
            "",
            "档位说明：",
            "",
        ]
    )
    for row in rows:
        lines.append(f"- {row.get('小区')}（{row.get('区')}）：{row.get('档位说明')}")
    excluded = [row for row in sample["全部小区"] if row.get("排除")]
    excluded.sort(key=lambda row: row.get("来源日期") or "", reverse=True)
    lines.extend(["", "## 已排除", "", "这些小区已经处在冻结、决定、签约或腾退，不打程序分，也不进候选。", ""])
    if not excluded:
        lines.append("无。")
    for row in excluded[:10]:
        lines.append(
            f"- {row.get('小区')}（{row.get('区')}）{row.get('排除')}，{row.get('来源日期')}，{row.get('来源URL')}"
        )
    if len(excluded) > 10:
        lines.append(f"- 其余 {len(excluded) - 10} 个见 sample.json。")
    lines.extend(["", "## 局限", ""])
    lines.extend(
        [
            "- 只收录这次请求实际返回的正文。抓取失败、没有发布日期、或标题不是项目公告的，记在跳过里，不补一条。",
            "- 公文库正文来自公开检索接口 `/gwk/search/data`（公文库页面所用的同一接口）。来源 URL 是该接口返回的公文页 `/gwk/search/content/{id}`。杨浦栏目是先取列表再逐篇打开公告页，打不开的篇目不入库。",
            "- 没有使用付费房价库，没有混用挂牌价、评估价、成交价，没有读取 fangdi.cn。",
            "- 户数、套均只在公告写出不带「约」的纯数字时抄录。缺一项则硬过滤为未知。",
            "- 成交笔数未导入。少于 3 笔不打量价的规则要到 M3 才有数据可依，所以量价一律是 N/A (M3)。",
            "- 结构分上限是 0–20，决定没有给出点表，这里不另造结构分。",
            "- 贴边小区的区随公告所在区，没有再做区界核对。",
            "- 没有小区全址名录。公告写明「部分」才标部分覆盖；只写门牌、没有小区名的地址保持待核。路弄回指只在同一区、同一路弄只对应一个已匹配小区时发生。",
            "- 附件里的 doc、pdf 不另解析。正文页面没有门牌时，地址留空。",
            "- 正式证据台账、项目表、小区表、观察池仍是空表。观察池要到 M5 才公开。",
            "",
            f"跳过 {cover['跳过条数']} 条，明细在 sample.json 的「跳过」。",
            "",
        ]
    )
    return "\n".join(lines)


def write_sample(root: Path, out: Path, sample: dict) -> Path:
    assert_private_output(root, out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sample.json").write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_markdown(sample), encoding="utf-8")
    return out


def _cell(value: object, limit: int | None = None) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("|", "/")
    if limit is not None and len(text) > limit:
        return text[: limit - 1] + "…"
    return text
