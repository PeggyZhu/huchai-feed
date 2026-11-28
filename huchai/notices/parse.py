"""Parse a fetched expropriation notice into addresses and name matches.

Match labels are only the four M2 results: 程序内, 部分覆盖, 贴边, 待核.
Numbers are copied only when the source writes a pure count. A figure
qualified by 约 is left unset.
"""

from __future__ import annotations

import datetime as dt
import re
from html import unescape


DISTRICTS = (
    "黄浦区",
    "徐汇区",
    "长宁区",
    "静安区",
    "普陀区",
    "虹口区",
    "杨浦区",
    "闵行区",
    "宝山区",
    "嘉定区",
    "浦东新区",
    "金山区",
    "松江区",
    "青浦区",
    "奉贤区",
    "崇明区",
)

# Fixed confidence labels. They record which rule fired, not a model score.
CONFIDENCE = {
    "程序内-标题": "0.90",
    "程序内-正文": "0.80",
    "部分覆盖": "0.70",
    "贴边": "0.85",
    "路弄回指": "0.60",
}

_POLICY_TITLE = (
    "补偿标准",
    "评估管理",
    "管理办法",
    "实施意见",
    "操作规程",
    "代表建议",
    "废止",
    "告知承诺",
    "价格干预",
    "行政审批",
    "专家库",
    "加装电梯",
    "相关标准",
)
_FALSE_POSITIVE = (
    ("成套改造", "成套改造"),
    ("屋面", "成套改造"),
    ("修缮", "成套改造"),
    ("学区", "学区"),
    ("对倒", "对倒"),
)
_NAME_SUFFIX = r"(?:小区|新村|花苑|花园|公寓|别墅|家园|新苑|佳苑|雅苑|豪苑|丽苑)"
_NAME_RE = re.compile(rf"[\u4e00-\u9fff]{{2,12}}{_NAME_SUFFIX}|[\u4e00-\u9fff]{{2,12}}园")
_SPLIT_VILLAGE_RE = re.compile(r"([\u4e00-\u9fff]{2,6})([一二三四五六七八])、([一二三四五六七八])村")
_VILLAGE_RE = re.compile(r"(?<!城中)([\u4e00-\u9fff]{2,6}[一二三四五六七八]村)")
_BOUNDARY_RE = re.compile(r"[东南西北]至([^，。；;\n]{1,40})")
_ROAD_RE = r"[\u4e00-\u9fff]{2,12}(?:公路|大道|大街|路|街)"
_TOKEN_RE = re.compile(
    rf"(?P<road>{_ROAD_RE})"
    rf"|(?P<lane>\d+)\s*弄"
    rf"|(?P<doors>\d+\s*号\s*-\s*\d+|\d+\s*-\s*\d+|\d+(?:、\d+)*)\s*号"
    rf"|(?P<all>全弄)"
)
_DOC_RE = re.compile(r"[\u4e00-\u9fffA-Za-z]{1,12}[\[〔]\s*20\d{2}\s*[\]〕]\s*\d+\s*号")
_DATE_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_ISO_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
_HOUSEHOLD_RE = re.compile(r"(约|近|逾|余|大约|超过|不少于|以上)?\s*(\d+)\s*户")
_AREA_RE = re.compile(r"(套均|户均)(?:建筑)?面积(?:为|约|：|:)?\s*(\d+(?:\.\d+)?)\s*(?:㎡|平方米)")


def html_to_text(raw: str) -> str:
    text = unescape(raw)
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    text = re.sub(r"(?<=\d)[ \t]+(?=\d)", "", text)
    text = text.replace("—", "-").replace("–", "-").replace("－", "-").replace("～", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def classify_title(title: str) -> str | None:
    """Return a notice kind, or None when the title is not a project notice."""
    compact = re.sub(r"\s+", "", title)
    compact = compact.replace("【此件为准】", "")
    if any(piece in compact for piece in _POLICY_TITLE):
        return None
    if "房屋征收决定" in compact or ("征收决定" in compact and "相关标准" not in compact):
        return "决定"
    if "不得实施相关行为" in compact or ("暂停办理" in compact and "房屋征收" in compact):
        return "冻结"
    if "征询" in compact or "征求意见" in compact:
        return "征询"
    if "补偿方案" in compact and "房屋征收" in compact:
        return "征询"
    if "房屋征收范围" in compact:
        return "征收范围"
    if "两清" in compact:
        return "两清"
    if "准动迁" in compact:
        return "准动迁挂牌"
    if "签约" in compact and "房屋征收" in compact:
        return "签约"
    if "腾退" in compact and ("房屋" in compact or "征收" in compact):
        return "腾退"
    if "城中村" in compact and any(piece in compact for piece in ("征收", "改造", "征询")):
        return "城中村"
    if any(piece in compact for piece in ("旧改", "旧区改造", "旧城区改建")):
        return "旧改公告"
    return None


def false_positive_label(title: str, text: str, kind: str) -> str | None:
    blob = title + "\n" + text
    compact = re.sub(r"\s+", "", blob)
    expropriation = any(
        piece in compact for piece in ("房屋征收决定", "房屋征收范围", "意愿征询", "不得实施相关行为", "征收补偿方案")
    )
    if "收储" in compact and not expropriation:
        return "收储"
    if any(piece in compact for piece in ("市政冻结", "暂停办理不动产", "暂停不动产登记")) and "房屋征收" not in compact:
        return "市政冻结"
    if expropriation or kind in {"决定", "冻结", "征询", "征收范围", "签约", "腾退"}:
        return None
    for needle, label in _FALSE_POSITIVE:
        if needle in compact:
            return label
    return None


def find_district(*parts: str | None) -> str | None:
    blobs = [part for part in parts if part]
    for blob in blobs:
        for name in sorted(DISTRICTS, key=len, reverse=True):
            if name in blob:
                return name
    return None


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    match = _ISO_RE.search(value)
    if match:
        return _validated(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    match = _DATE_RE.search(value)
    if match:
        return _validated(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def _validated(year: int, month: int, day: int) -> str | None:
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def notice_date(text: str, explicit: str | None = None) -> str | None:
    parsed = parse_date(explicit)
    if parsed:
        return parsed
    labeled = re.search(r"发布日期[:：\s]*([0-9]{4}[^0-9]{0,3}[0-9]{1,2}[^0-9]{0,3}[0-9]{1,2})", text)
    if labeled:
        parsed = parse_date(labeled.group(1))
        if parsed:
            return parsed
    found = [parsed for match in _DATE_RE.finditer(text) if (parsed := _validated(int(match.group(1)), int(match.group(2)), int(match.group(3))))]
    if not found:
        return None
    return found[-1]


def document_number(text: str) -> str | None:
    match = _DOC_RE.search(text)
    if not match:
        return None
    raw = re.sub(r"\s+", "", match.group(0))
    raw = raw.replace("[", "〔").replace("]", "〕")
    return raw


def project_name(title: str) -> str:
    compact = title.replace("【此件为准】", "").strip()
    bracket = re.search(r"[（(]([^）)]+)[）)]\s*$", compact)
    if bracket and "批复" not in bracket.group(1) and len(bracket.group(1)) <= 40:
        return bracket.group(1).strip()
    name = re.sub(r"^上海市", "", compact)
    name = re.sub(r"^[\u4e00-\u9fff]{2,6}(?:人民政府办公室|人民政府)", "", name)
    name = re.sub(r"关于(?:同意)?(?:作出|公布|确认|印发)?", "", name)
    name = re.sub(r"(房屋征收决定|的批复).*$", "", name)
    name = name.strip("《》 ")
    return name[:80] or compact[:80]


def address_window(text: str) -> str:
    """Scope and door-list text. Resettlement catalogues are not part of the scope."""
    chunks: list[str] = []
    for marker in ("房屋征收范围", "改建范围", "四至范围", "具体门牌"):
        start = 0
        while len(chunks) < 4:
            index = text.find(marker, start)
            if index < 0:
                break
            chunks.append(text[index : index + 1800])
            start = index + len(marker)
    if "见附件" in text:
        origin = text.find("附件")
        lane = text.find("弄", origin if origin >= 0 else 0)
        if lane >= 0:
            block = text[max(0, lane - 180) : lane + 1600]
            if "安置" not in block and "房源" not in block:
                chunks.append(block)
    if not chunks:
        chunks.append(text[:1500])
    window = "\n".join(chunks)
    cut = re.search(r"安置房|房源情况|选房", window)
    if cut:
        window = window[: cut.start()]
    return window


def scope_text(text: str) -> str:
    window = re.sub(r"\s+", " ", address_window(text)).strip()
    return window[:500]


def extract_addresses(text: str) -> list[dict]:
    region = address_window(text)
    found: list[dict] = []
    seen: set[tuple] = set()
    for sentence in re.split(r"[。；;\n]", region):
        if any(word in sentence for word in ("安置", "房源", "选房")):
            continue
        road = None
        lane = None
        current: dict | None = None
        for match in _TOKEN_RE.finditer(sentence):
            if match.group("road"):
                road = match.group("road")
                lane = None
                current = None
                continue
            if not road:
                continue
            if match.group("lane"):
                lane = match.group("lane")
                current = _address(road, lane, [], False)
                _push(found, seen, current)
                continue
            if match.group("all") and current is not None and current["弄"]:
                current["全弄"] = True
                current["原文"] = _address_text(current)
                # 全弄 closes the lane. A following 号 belongs to the road, not the lane.
                current = None
                lane = None
                continue
            doors = match.group("doors")
            if not doors:
                continue
            if current is None or current["路"] != road or current["弄"] != lane:
                current = _address(road, lane, [doors + "号"], False)
                _push(found, seen, current)
            elif doors + "号" not in current["号"]:
                current["号"].append(doors + "号")
                current["原文"] = _address_text(current)
    return found


def _address(road: str, lane: str | None, doors: list[str], whole: bool) -> dict:
    item = {"路": road, "弄": lane, "号": doors, "全弄": whole, "原文": ""}
    item["原文"] = _address_text(item)
    return item


def _address_text(item: dict) -> str:
    text = item["路"]
    if item["弄"]:
        text += f"{item['弄']}弄"
    if item["全弄"]:
        text += "（全弄）"
    if item["号"]:
        text += "、".join(item["号"]) if not item["弄"] else "".join(item["号"])
    return text


def _push(found: list[dict], seen: set[tuple], item: dict) -> None:
    key = (item["路"], item["弄"], tuple(item["号"]), item["全弄"])
    if key in seen:
        return
    seen.add(key)
    found.append(item)


def extract_names(title: str, text: str) -> list[str]:
    blob = f"{title}\n{text}"
    names: list[str] = []
    for match in _SPLIT_VILLAGE_RE.finditer(blob):
        names.append(match.group(1) + match.group(2) + "村")
        names.append(match.group(1) + match.group(3) + "村")
    for match in _VILLAGE_RE.finditer(blob):
        names.append(match.group(1))
    for match in _NAME_RE.finditer(blob):
        names.append(match.group(0))
    cleaned = []
    for name in names:
        kept = _clean_name(name)
        if kept and kept not in cleaned:
            cleaned.append(kept)
    return _drop_nested(cleaned)


def _clean_name(name: str) -> str | None:
    stops = (
        "原则同意",
        "申请确认",
        "加快推进",
        "关于同意",
        "同意",
        "申请",
        "确认",
        "推进",
        "加快",
        "关于",
        "作出",
        "公布",
        "位于",
        "包括",
        "以及",
        "涉及",
        "街道",
        "社区",
        "东至",
        "南至",
        "西至",
        "北至",
        "镇",
        *DISTRICTS,
        "上海市",
    )
    cut = 0
    for stop in stops:
        index = name.rfind(stop)
        if index >= 0:
            cut = max(cut, index + len(stop))
    name = name[cut:]
    pieces = re.split(r"[和与及]", name)
    if pieces and len(pieces[-1]) >= 3:
        name = pieces[-1]
    if len(name) < 3 or name.startswith(("居民", "该", "本", "有关", "相关", "上述")):
        return None
    if any(
        piece in name
        for piece in ("公园", "工业园", "校园", "园区", "幼儿园", "征收", "补偿", "政府", "房屋", "国有", "至", "同意", "申请", "原则", "加快", "推进", "成套", "工房", "安置", "批复")
    ):
        return None
    if not re.search(rf"(?:{_NAME_SUFFIX}|园|[一二三四五六七八]村)$", name):
        return None
    return name


def _drop_nested(names: list[str]) -> list[str]:
    kept = []
    for name in sorted(names, key=len, reverse=True):
        if any(name != other and name in other for other in kept):
            continue
        kept.append(name)
    return kept


def match_names(title: str, text: str, names: list[str]) -> list[dict]:
    boundaries = [(match.start(1), match.end(1), match.group(1)) for match in _BOUNDARY_RE.finditer(text)]
    masked = text
    for start, end, _chunk in boundaries:
        masked = masked[:start] + (" " * (end - start)) + masked[end:]
    rows = []
    for name in names:
        in_title = name in title
        in_boundary = any(name in chunk for _start, _end, chunk in boundaries)
        outside = name in masked
        if in_boundary and not in_title and not outside:
            kind = "贴边"
            confidence = CONFIDENCE["贴边"]
            raw = name
        elif _is_partial(name, title, text):
            kind = "部分覆盖"
            confidence = CONFIDENCE["部分覆盖"]
            raw = _around(name, text)
        else:
            kind = "程序内"
            confidence = CONFIDENCE["程序内-标题"] if in_title else CONFIDENCE["程序内-正文"]
            raw = _around(name, text)
        rows.append({"小区": name, "匹配": kind, "置信度": confidence, "原始地址": raw})
    return rows


def _around(name: str, text: str) -> str:
    flat = re.sub(r"\s+", "", text)
    index = flat.find(name)
    if index < 0:
        return name
    start = max(0, index - 24)
    end = min(len(flat), index + len(name) + 36)
    return flat[start:end]


def _is_partial(name: str, title: str, text: str) -> bool:
    if "部分" in title and name in title:
        return True
    return re.search(re.escape(name) + r".{0,8}部分|部分.{0,8}" + re.escape(name), title + "\n" + text) is not None


def structural_figures(text: str) -> dict:
    """Copy an explicit household count or 套均. Leave both unset on 约 or conflict."""
    households = []
    for match in _HOUSEHOLD_RE.finditer(text):
        if match.group(1):
            continue
        start = match.start(2)
        window = text[max(0, start - 6) : start]
        if any(flag in window for flag in ("约", "近", "逾", "余")):
            continue
        households.append((int(match.group(2)), match.group(0).strip()))
    areas = []
    for match in _AREA_RE.finditer(text):
        prefix = text[max(0, match.start() - 2) : match.start()]
        if "约" in match.group(0) or "约" in prefix:
            continue
        areas.append((float(match.group(2)) if "." in match.group(2) else int(match.group(2)), match.group(0).strip()))
    household_value, household_raw = _unique(households)
    area_value, area_raw = _unique(areas)
    return {
        "户数": household_value,
        "户数原文": household_raw,
        "套均面积": area_value,
        "套均原文": area_raw,
    }


def _unique(pairs: list[tuple]) -> tuple[object, str | None]:
    if not pairs:
        return None, None
    values = {item[0] for item in pairs}
    raw = "；".join(item[1] for item in pairs)
    if len(values) != 1:
        return None, raw
    return next(iter(values)), raw


def analyze_notice(
    *,
    title: str,
    text: str,
    url: str,
    published: str | None = None,
    district: str | None = None,
    fetched_via: str | None = None,
) -> dict | None:
    kind = classify_title(title)
    if kind is None:
        return None
    body = html_to_text(text)
    if kind == "决定" and "房屋" not in title + body[:2500] and "门牌" not in body:
        return None
    if kind in {"城中村", "旧改公告"} and not any(
        piece in (title + body) for piece in ("房屋征收", "门牌", "征收范围", "征询")
    ):
        return None
    day = notice_date(body, published)
    if day is None:
        return None
    found_district = find_district(district, title, body[:800])
    label = false_positive_label(title, body, kind)
    if label == "市政冻结":
        kind = "冻结"
    names = extract_names(title, address_window(body))
    matches = match_names(title, address_window(body), names)
    figures = structural_figures(body) if not label else {
        "户数": None,
        "户数原文": None,
        "套均面积": None,
        "套均原文": None,
    }
    return {
        "标题": re.sub(r"\s+", "", title.replace("【此件为准】", "")).strip(),
        "项目名": project_name(title),
        "区": found_district,
        "公告类型": kind,
        "假阳性": label,
        "文号": document_number(body) or document_number(title),
        "来源URL": url,
        "来源日期": day,
        "抓取自": fetched_via or url,
        "范围原文": scope_text(body)[:500],
        "地址": extract_addresses(body),
        "匹配": matches,
        **figures,
    }


def link_lanes(notices: list[dict]) -> None:
    """Attach a 小区 to an address-only notice when one same-district notice already paired that 路弄."""
    index: dict[tuple[str, str, str], set[str]] = {}
    for notice in notices:
        district = notice.get("区")
        if not district:
            continue
        subjects = [row["小区"] for row in notice["匹配"] if row["匹配"] in {"程序内", "部分覆盖"}]
        if len(subjects) != 1:
            continue
        for address in notice["地址"]:
            if address.get("弄"):
                index.setdefault((district, address["路"], address["弄"]), set()).add(subjects[0])
    for notice in notices:
        district = notice.get("区")
        if not district or notice["匹配"]:
            continue
        linked: list[dict] = []
        for address in notice["地址"]:
            if not address.get("弄"):
                continue
            names = index.get((district, address["路"], address["弄"]), set())
            if len(names) != 1:
                continue
            name = next(iter(names))
            if any(row["小区"] == name for row in linked):
                continue
            kind = "部分覆盖" if _is_partial(name, notice["标题"], notice.get("范围原文") or "") else "程序内"
            linked.append(
                {
                    "小区": name,
                    "匹配": kind,
                    "置信度": CONFIDENCE["路弄回指"],
                    "原始地址": address["原文"],
                }
            )
        notice["匹配"].extend(linked)
