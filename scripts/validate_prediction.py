#!/usr/bin/env python3
"""Validate the community-level prediction tables.

The weekly report may read the evidence ledger and the rows that cite it.
This script does not compute prices, excess gains, tiers, or scores, and it
does not open the net-sign snapshots.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlparse


DISTRICTS = [
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
]
PRICE_CALIBERS = ["挂牌价", "评估价", "成交价"]
NETSIGN_CALIBERS = ["网签商业口径", "房管局住房口径"]
EVIDENCE_CALIBERS = PRICE_CALIBERS + NETSIGN_CALIBERS + ["结构属性", "程序状态"]
PROGRAMME_KINDS = ["征询", "冻结", "决定", "签约"]
POOL_CALIBERS = PRICE_CALIBERS + ["程序"]
STRUCTURAL_FIELDS = {"户数", "套均面积", "建成年代", "房屋类型"}
DERIVED_FIELDS = {"超额涨幅", "涨幅", "分数", "程序分", "量价分", "结构分", "档位", "总分", "综合分"}
DATE_FIELDS = {"来源日期", "日期", "入池日期", "最后证据日期"}
SCORE_BOUNDS = {"程序": 50, "量价": 30, "结构": 20}
MIXED_MARKS = ("/", "／", "+", "＋", "、", ",", "，", ";", "；", "及", "与", "和")
SOCIAL_HOSTS = (
    "weibo.com",
    "weibo.cn",
    "xiaohongshu.com",
    "xhslink.com",
    "douyin.com",
    "iesdouyin.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "t.co",
    "t.me",
    "telegram.me",
    "telegram.org",
    "bilibili.com",
    "douban.com",
    "zhihu.com",
    "tieba.baidu.com",
)
KNOWN_KEYWORDS = {
    "$schema",
    "$id",
    "$defs",
    "$ref",
    "$comment",
    "title",
    "description",
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "minLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "pattern",
    "minItems",
    "maxItems",
}
REF_ANNOTATIONS = {"$ref", "description", "title", "$comment"}
EXAMPLE_KEYS = {"数据性质", "警告", "evidence", "programmes", "communities", "observation_pool"}


class Table(NamedTuple):
    name: str
    schema_file: str
    json_file: str
    csv_file: str
    source_field: str
    identity_field: str


TABLES = (
    Table("evidence", "evidence.schema.json", "evidence.json", "evidence.csv", "来源URL", "小区"),
    Table("programmes", "programmes.schema.json", "programmes.json", "programmes.csv", "来源", "项目名"),
    Table("communities", "communities.schema.json", "communities.json", "communities.csv", "来源", "名称"),
    Table(
        "observation_pool",
        "observation-pool.schema.json",
        "observation-pool.json",
        "observation-pool.csv",
        "来源",
        "小区",
    ),
)
TABLE_BY_NAME = {table.name: table for table in TABLES}
ALLOWED_FILES = {
    "schema/README.md",
    "schema/evidence.schema.json",
    "schema/programmes.schema.json",
    "schema/communities.schema.json",
    "schema/observation-pool.schema.json",
    "evidence.json",
    "evidence.csv",
    "programmes.json",
    "programmes.csv",
    "communities.json",
    "communities.csv",
    "observation-pool.json",
    "observation-pool.csv",
    "示例数据.json",
}


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> tuple[object | None, list[str]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, [f"{path}: 无法读取 ({exc})"]
    if raw.startswith(b"\xef\xbb\xbf"):
        return None, [f"{path.name}: 不要使用 BOM"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, [f"{path.name}: 不是 UTF-8"]
    try:
        return json.loads(text), []
    except json.JSONDecodeError as exc:
        return None, [f"{path.name}: JSON 无法解析 ({exc})"]


def audit_schema(schema: object, path: str, errors: list[str]) -> None:
    if not isinstance(schema, dict):
        errors.append(f"{path}: schema 必须是对象")
        return
    for key in schema:
        if key not in KNOWN_KEYWORDS:
            errors.append(f"{path}: 不支持的 JSON Schema 关键字 {key}")
    if "$ref" in schema and any(key not in REF_ANNOTATIONS for key in schema):
        errors.append(f"{path}: $ref 不能和其它约束写在一起")
    additional = schema.get("additionalProperties", True)
    if not isinstance(additional, bool):
        errors.append(f"{path}: additionalProperties 只接受 true 或 false")
    for key, sub in schema.get("properties", {}).items():
        audit_schema(sub, f"{path}/properties/{key}", errors)
    for key, sub in schema.get("$defs", {}).items():
        audit_schema(sub, f"{path}/$defs/{key}", errors)
    if "items" in schema:
        audit_schema(schema["items"], f"{path}/items", errors)


def _row_schema(schema: dict) -> dict:
    return schema["$defs"]["row"]


def assert_schema_policy(schemas: dict[str, dict], errors: list[str]) -> None:
    try:
        evidence = _row_schema(schemas["evidence"])["properties"]
        programmes = _row_schema(schemas["programmes"])["properties"]
        communities = _row_schema(schemas["communities"])["properties"]
        pool = _row_schema(schemas["observation_pool"])["properties"]
        pool_scores = pool["分数分项"]["properties"]
    except (KeyError, TypeError) as exc:
        errors.append(f"schema 形状无法核对：{exc}")
        return

    if evidence["区"]["enum"] != DISTRICTS or communities["区"]["enum"] != DISTRICTS:
        errors.append("区枚举必须是上海市十六个区，证据台账和小区表要一致")
    if evidence["口径"]["enum"] != EVIDENCE_CALIBERS:
        errors.append("证据台账的口径枚举与既定口径不一致")
    if evidence["状态"]["enum"] != ["已确认", "待核"]:
        errors.append("证据状态只允许已确认或待核")
    if programmes["类型"]["enum"] != PROGRAMME_KINDS or programmes["口径"]["enum"] != PROGRAMME_KINDS:
        errors.append("项目类型和口径只允许征询、冻结、决定、签约")
    if communities["口径"]["enum"] != ["结构属性"]:
        errors.append("小区表的口径只允许结构属性")
    if pool["口径"]["enum"] != POOL_CALIBERS:
        errors.append("观察池的口径只允许挂牌价、评估价、成交价或程序")
    if pool["档位"]["enum"] != ["高", "中", "低", None]:
        errors.append("档位只允许高、中、低或空白")
    household = communities["户数"]
    area = communities["套均面积"]
    if household.get("minimum") != 0 or "maximum" in household:
        errors.append("户数的取值范围不要写成硬过滤阈值")
    if area.get("exclusiveMinimum") != 0 or "minimum" in area or "maximum" in area:
        errors.append("套均面积的取值范围不要写成硬过滤阈值")
    for name, limit in SCORE_BOUNDS.items():
        score = pool_scores[name]
        if score.get("minimum") != 0 or score.get("maximum") != limit:
            errors.append(f"分数分项「{name}」的上下限与决定不一致")
    for table in TABLES:
        schema = schemas[table.name]
        columns = schema["properties"]["columns"]["const"]
        row = _row_schema(schema)
        if row["required"] != columns or set(row["properties"]) != set(columns):
            errors.append(f"{table.name}: 列、必填字段和属性不一致")
        if "口径" not in columns or table.source_field not in columns:
            errors.append(f"{table.name}: 必须同时有来源和口径")


def matches_type(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def resolve_ref(root: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise KeyError(ref)
    node: object = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise KeyError(ref)
        node = node[part]
    if not isinstance(node, dict):
        raise KeyError(ref)
    return node


def validate_instance(instance: object, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    if "$ref" in schema:
        try:
            target = resolve_ref(root, schema["$ref"])
        except KeyError:
            errors.append(f"{path}: 无法解析 {schema['$ref']}")
            return
        validate_instance(instance, target, root, path, errors)
        return

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: 值不符合 const")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: 不在允许的取值内")
    if "type" in schema:
        expected = schema["type"]
        types = expected if isinstance(expected, list) else [expected]
        if not any(matches_type(instance, item) for item in types):
            errors.append(f"{path}: 类型不符合")
            return

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: 缺少字段 {key}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        if properties or additional is False:
            for key, value in instance.items():
                if key in properties:
                    validate_instance(value, properties[key], root, f"{path}.{key}", errors)
                elif additional is False:
                    errors.append(f"{path}: 不允许的字段 {key}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: 短于最小长度")
        if "pattern" in schema and re.fullmatch(schema["pattern"], instance) is None:
            errors.append(f"{path}: 格式不符合")

    if is_number(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: 小于下限")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: 大于上限")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: 小于或等于排除下限")
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: 大于或等于排除上限")

    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            validate_instance(item, schema["items"], root, f"{path}[{index}]", errors)
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: 行数不足")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: 行数超过上限")


def coerce_cell(text: str, schema: dict) -> object:
    expected = schema.get("type", "string")
    types = expected if isinstance(expected, list) else [expected]
    if text == "":
        if "null" in types:
            return None
        return ""
    if "object" in types or "array" in types:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"不是合法 JSON ({exc})") from exc
    if "integer" in types and "number" not in types:
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        return text
    if "number" in types:
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if re.fullmatch(r"-?\d+\.\d+", text):
            return float(text)
        return text
    return text


def read_csv_rows(path: Path, columns: list[str], row_schema: dict, errors: list[str]) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{path.name}: 无法读取 ({exc})")
        return []
    if text.startswith("\ufeff"):
        errors.append(f"{path.name}: 不要使用 BOM")
        text = text.lstrip("\ufeff")
    parsed = list(csv.reader(io.StringIO(text)))
    if not parsed:
        errors.append(f"{path.name}: 缺少表头")
        return []
    header, data = parsed[0], parsed[1:]
    if header != columns:
        errors.append(f"{path.name}: 表头与 schema 不一致")
        return []
    rows: list[dict] = []
    properties = row_schema["properties"]
    for line_number, cells in enumerate(data, start=2):
        if cells == [] or all(cell == "" for cell in cells):
            errors.append(f"{path.name}:{line_number}: 空行")
            continue
        if len(cells) != len(columns):
            errors.append(f"{path.name}:{line_number}: 列数不符")
            continue
        row: dict[str, object] = {}
        failed = False
        for key, cell in zip(columns, cells):
            try:
                row[key] = coerce_cell(cell, properties[key])
            except ValueError as exc:
                errors.append(f"{path.name}:{line_number}.{key}: {exc}")
                failed = True
        if not failed:
            rows.append(row)
    return rows


def walk_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)


def require_source_and_caliber(table: str, row: object, path: str, errors: list[str]) -> None:
    source_field = TABLE_BY_NAME[table].source_field
    if not isinstance(row, dict):
        errors.append(f"{path}: 缺少来源和口径")
        return
    source = row.get(source_field)
    caliber = row.get("口径")
    missing_source = not isinstance(source, str) or source.strip() == ""
    missing_caliber = not isinstance(caliber, str) or caliber.strip() == ""
    if missing_source and missing_caliber:
        errors.append(f"{path}: 缺少来源和口径")
    elif missing_source:
        errors.append(f"{path}: 缺少来源")
    elif missing_caliber:
        errors.append(f"{path}: 缺少口径")


def looks_mixed(caliber: str) -> bool:
    return any(mark in caliber for mark in MIXED_MARKS)


def host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith("." + suffix)


def source_parts(table: str, value: str) -> list[str] | None:
    if table != "observation_pool":
        return [value.strip()]
    parts = [part.strip() for part in value.split("|")]
    if not parts or any(part == "" for part in parts):
        return None
    return parts


def check_source_url(table: str, value: str, path: str, errors: list[str], *, example: bool) -> None:
    if value != value.strip():
        errors.append(f"{path}: 来源首尾不要留空格")
        return
    parts = source_parts(table, value)
    if parts is None:
        errors.append(f"{path}: 来源格式有误")
        return
    for part in parts:
        parsed = urlparse(part)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or host == "":
            errors.append(f"{path}: 来源必须是公开的 http(s) URL")
            continue
        if host_matches(host, "example.com") and not example:
            errors.append(f"{path}: 正式数据不能使用 example.com")
        for suffix in SOCIAL_HOSTS:
            if host_matches(host, suffix):
                errors.append(f"{path}: 社交媒体来源权重为 0，不能作为来源")
                break


def check_dates(row: dict, path: str, errors: list[str]) -> None:
    for key in DATE_FIELDS:
        value = row.get(key)
        if not isinstance(value, str):
            continue
        try:
            dt.date.fromisoformat(value)
        except ValueError:
            errors.append(f"{path}.{key}: 不是有效日期")


def check_identity_label(table: str, row: dict, path: str, errors: list[str], *, example: bool) -> None:
    identity = row.get(TABLE_BY_NAME[table].identity_field)
    text = identity if isinstance(identity, str) else ""
    if example:
        if "示例数据" not in text:
            errors.append(f"{path}: 示例行必须在名称中写明示例数据")
        return
    for value in walk_strings(row):
        if "示例数据" in value:
            errors.append(f"{path}: 正式表不能包含示例数据")
            return


def check_evidence_rules(row: dict, path: str, errors: list[str]) -> None:
    field = row.get("字段")
    caliber = row.get("口径")
    if isinstance(field, str) and (field in DERIVED_FIELDS or field.endswith("涨幅") or "分数" in field):
        errors.append(f"{path}: 派生结果不能写入证据台账")
    if isinstance(caliber, str) and looks_mixed(caliber):
        errors.append(f"{path}: 口径不得混用")
    if caliber in PRICE_CALIBERS and field != caliber:
        errors.append(f"{path}: 挂牌价、评估价、成交价不得混用，字段必须与口径相同")
    if field in STRUCTURAL_FIELDS and caliber != "结构属性":
        errors.append(f"{path}: 结构字段的口径必须是结构属性")
    if field == "程序状态" and caliber != "程序状态":
        errors.append(f"{path}: 程序状态的口径必须是程序状态")
    pieces = [row.get("字段"), row.get("口径"), row.get("值")]
    blob = "\n".join(piece for piece in pieces if isinstance(piece, str))
    if all(name in blob for name in NETSIGN_CALIBERS):
        errors.append(f"{path}: 含商业口径与房管局住房口径不得写在同一条，也不得相加")


def check_pool_rules(row: dict, path: str, errors: list[str]) -> None:
    scores = row.get("分数分项")
    if row.get("口径") == "程序" and isinstance(scores, dict) and scores.get("量价") is not None:
        errors.append(f"{path}: 口径为程序时不能填写量价分")


def row_errors(table: str, row: object, *, example: bool, prefix: str = "row") -> list[str]:
    """Validate one row. Missing 来源 or 口径 is always an error."""
    return check_row_with_schema(
        table,
        row,
        bundled_schemas()[table],
        example=example,
        prefix=prefix,
        check_schema=True,
    )


def _dicts(rows: object) -> list[dict]:
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def dataset_errors(tables: dict[str, list], *, example: bool) -> list[str]:
    """Cross-check projections against the ledger. `example` is accepted for callers."""
    del example
    errors: list[str] = []
    evidence = _dicts(tables.get("evidence", []))
    evidence_urls = {row.get("来源URL") for row in evidence if isinstance(row.get("来源URL"), str)}

    for index, row in enumerate(_dicts(tables.get("programmes", []))):
        if row.get("来源") not in evidence_urls:
            errors.append(f"programmes[{index}]: 项目的来源必须先写入证据台账")

    for index, row in enumerate(_dicts(tables.get("communities", []))):
        path = f"communities[{index}]"
        matched = [
            item
            for item in evidence
            if item.get("小区") == row.get("名称") and item.get("来源URL") == row.get("来源")
        ]
        if row.get("来源") and not matched:
            errors.append(f"{path}: 小区表的来源必须指向同一小区的证据台账行")
        for field, column in (("户数", "户数"), ("套均面积", "套均面积")):
            cell = row.get(column)
            if cell is None:
                continue
            confirmed = [
                item
                for item in matched
                if item.get("字段") == field and item.get("口径") == row.get("口径") and item.get("状态") == "已确认"
            ]
            if not confirmed:
                errors.append(f"{path}: {field}在证据台账里没有对应的已确认行")
                continue
            values = {item.get("值") for item in confirmed}
            if len(values) != 1:
                errors.append(f"{path}: 同一来源下有多条不一致的{field}")
                continue
            original = next(iter(values))
            if not number_matches(cell, original):
                errors.append(f"{path}: {field}与证据台账原文不一致，不要换算")

    for index, row in enumerate(_dicts(tables.get("observation_pool", []))):
        errors.extend(pool_citation_errors(row, evidence, f"observation_pool[{index}]"))
    return errors


def number_matches(cell: object, original: object) -> bool:
    if isinstance(cell, bool) or not isinstance(original, str):
        return False
    if isinstance(cell, int):
        return re.fullmatch(r"\d+", original) is not None and int(original) == cell
    if isinstance(cell, float):
        if re.fullmatch(r"\d+(\.\d+)?", original) is None:
            return False
        return Decimal(str(cell)) == Decimal(original)
    return False


def pool_citation_errors(row: dict, evidence: list[dict], path: str) -> list[str]:
    errors: list[str] = []
    source = row.get("来源")
    if not isinstance(source, str):
        return errors
    parts = source_parts("observation_pool", source)
    if parts is None:
        return errors
    cited: list[dict] = []
    missing = False
    for url in parts:
        matched = [item for item in evidence if item.get("来源URL") == url and item.get("小区") == row.get("小区")]
        if not matched:
            errors.append(f"{path}: 观察池来源必须指向同一小区的证据台账行")
            missing = True
        cited.extend(matched)
    if missing:
        return errors
    dates = [parsed for item in cited if (parsed := parse_date(item.get("来源日期"))) is not None]
    last = parse_date(row.get("最后证据日期"))
    if dates and last is not None and last != max(dates):
        errors.append(f"{path}: 最后证据日期必须等于所引台账记录中最晚的来源日期")
    scores = row.get("分数分项")
    score_present = isinstance(scores, dict) and any(scores.get(name) is not None for name in SCORE_BOUNDS)
    if (row.get("档位") is not None or score_present) and not any(item.get("状态") == "已确认" for item in cited):
        errors.append(f"{path}: 待核证据不能单独支撑档位或分数")
    return errors


def parse_date(value: object) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def bundled_schemas() -> dict[str, dict]:
    schemas, errors = load_schemas(repo_root_from_script() / "data" / "prediction" / "schema")
    if errors or any(name not in schemas for name in TABLE_BY_NAME):
        raise RuntimeError("预测模块 schema 无法加载：" + "；".join(errors))
    return schemas


def load_schemas(schema_dir: Path) -> tuple[dict[str, dict], list[str]]:
    errors: list[str] = []
    schemas: dict[str, dict] = {}
    for table in TABLES:
        loaded, load_errors = load_json(schema_dir / table.schema_file)
        errors.extend(load_errors)
        if not isinstance(loaded, dict):
            if not load_errors:
                errors.append(f"{table.schema_file}: schema 必须是对象")
            continue
        audit_schema(loaded, table.schema_file, errors)
        schemas[table.name] = loaded
    if len(schemas) == len(TABLES):
        assert_schema_policy(schemas, errors)
    return schemas, errors


def check_allowed_files(base: Path, errors: list[str]) -> None:
    if not base.is_dir():
        errors.append("缺少 data/prediction/")
        return
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if relative not in ALLOWED_FILES:
            errors.append(f"data/prediction 出现未登记文件 {relative}")


def validate_examples(document: object, errors: list[str]) -> dict[str, list]:
    if not isinstance(document, dict):
        errors.append("示例数据.json: 必须是对象")
        return {table.name: [] for table in TABLES}
    if set(document) != EXAMPLE_KEYS:
        extra = sorted(set(document) - EXAMPLE_KEYS)
        missing = sorted(EXAMPLE_KEYS - set(document))
        if extra:
            errors.append(f"示例数据.json: 含未定义字段 {extra}")
        if missing:
            errors.append(f"示例数据.json: 缺少 {missing}")
    if document.get("数据性质") != "示例数据":
        errors.append("示例数据.json: 数据性质必须是示例数据")
    warning = document.get("警告")
    if not isinstance(warning, str) or "示例数据" not in warning:
        errors.append("示例数据.json: 警告必须写明示例数据")
    tables: dict[str, list] = {}
    for table in TABLES:
        value = document.get(table.name)
        if not isinstance(value, list):
            errors.append(f"示例数据.json: {table.name} 必须是数组")
            tables[table.name] = []
        else:
            tables[table.name] = value
    return tables


def validate_repository(root: Path) -> list[str]:
    root = root.resolve()
    base = root / "data" / "prediction"
    errors: list[str] = []
    check_allowed_files(base, errors)
    schemas, schema_errors = load_schemas(base / "schema")
    errors.extend(schema_errors)
    formal: dict[str, list] = {}
    for table in TABLES:
        schema = schemas.get(table.name)
        document, load_errors = load_json(base / table.json_file)
        errors.extend(load_errors)
        rows: list = []
        if schema is not None and isinstance(document, dict):
            validate_instance(document, schema, schema, table.json_file, errors)
            loaded_rows = document.get("rows")
            rows = loaded_rows if isinstance(loaded_rows, list) else []
            columns = schema["properties"]["columns"]["const"]
            csv_rows = read_csv_rows(base / table.csv_file, columns, _row_schema(schema), errors)
            if csv_rows != rows:
                errors.append(f"{table.name}: CSV 与 JSON 的数据行不一致")
        elif schema is not None:
            errors.append(f"{table.json_file}: 正式表必须是对象")
        formal[table.name] = rows
        for index, row in enumerate(rows):
            prefix = f"{table.json_file}.rows[{index}]"
            errors.extend(
                check_row_with_schema(
                    table.name,
                    row,
                    schema,
                    example=False,
                    prefix=prefix,
                    check_schema=False,
                )
            )
    if all(name in schemas for name in TABLE_BY_NAME):
        errors.extend(dataset_errors(formal, example=False))

    example_document, load_errors = load_json(base / "示例数据.json")
    errors.extend(load_errors)
    if example_document is not None:
        examples = validate_examples(example_document, errors)
        for table in TABLES:
            schema = schemas.get(table.name)
            for index, row in enumerate(examples.get(table.name, [])):
                prefix = f"示例数据.json {table.name}[{index}]"
                errors.extend(
                    check_row_with_schema(
                        table.name,
                        row,
                        schema,
                        example=True,
                        prefix=prefix,
                        check_schema=True,
                    )
                )
        if all(name in schemas for name in TABLE_BY_NAME):
            errors.extend(dataset_errors(examples, example=True))
    return errors


def check_row_with_schema(
    table: str,
    row: object,
    schema: dict | None,
    *,
    example: bool,
    prefix: str,
    check_schema: bool = True,
) -> list[str]:
    if schema is None:
        return row_errors(table, row, example=example, prefix=prefix)
    errors: list[str] = []
    if check_schema:
        validate_instance(row, _row_schema(schema), schema, prefix, errors)
    require_source_and_caliber(table, row, prefix, errors)
    if not isinstance(row, dict):
        return errors
    check_dates(row, prefix, errors)
    check_identity_label(table, row, prefix, errors, example=example)
    source = row.get(TABLE_BY_NAME[table].source_field)
    if isinstance(source, str) and source.strip() != "":
        check_source_url(table, source, f"{prefix}.{TABLE_BY_NAME[table].source_field}", errors, example=example)
    if table == "evidence":
        check_evidence_rules(row, prefix, errors)
    elif table == "programmes" and row.get("口径") != row.get("类型"):
        errors.append(f"{prefix}: 项目的口径必须与类型相同，征询不能写成决定")
    elif table == "observation_pool":
        check_pool_rules(row, prefix, errors)
    return errors


def count_formal_rows(root: Path) -> int:
    total = 0
    base = root / "data" / "prediction"
    for table in TABLES:
        document, _errors = load_json(base / table.json_file)
        if isinstance(document, dict) and isinstance(document.get("rows"), list):
            total += len(document["rows"])
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验小区级征收预测表的结构和出处")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    errors = validate_repository(args.root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        print(f"prediction: {len(errors)} 个问题", file=sys.stderr)
        return 1
    total = count_formal_rows(args.root)
    print(f"prediction: 正式表 {total} 行，校验通过。示例数据已单独标记，未生成新数字。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
