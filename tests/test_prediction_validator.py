"""Validator tests for the prediction scaffold.

Numbers in this file exist only as in-memory fixtures. They are not
observations and are never written under data/prediction.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_prediction as prediction  # noqa: E402


def evidence(**overrides):
    row = {
        "小区": "测试小区",
        "区": "黄浦区",
        "字段": "程序状态",
        "值": "原文",
        "来源URL": "https://example.org/notice",
        "来源日期": "2020-01-01",
        "口径": "程序状态",
        "状态": "待核",
    }
    row.update(overrides)
    return row


def programme(**overrides):
    row = {
        "项目名": "测试项目",
        "文号": "测试文号",
        "类型": "征询",
        "日期": "2020-01-01",
        "范围": "测试范围",
        "来源": "https://example.org/notice",
        "口径": "征询",
    }
    row.update(overrides)
    return row


def community(**overrides):
    row = {
        "名称": "测试小区",
        "区": "黄浦区",
        "地址/弄号": None,
        "户数": None,
        "套均面积": None,
        "建成年代": None,
        "房屋类型": None,
        "来源": "https://example.org/notice",
        "口径": "结构属性",
    }
    row.update(overrides)
    return row


def pool(**overrides):
    row = {
        "小区": "测试小区",
        "档位": None,
        "分数分项": None,
        "入池日期": "2020-01-02",
        "最后证据日期": "2020-01-01",
        "理由": "只标注",
        "来源": "https://example.org/notice",
        "口径": "程序",
    }
    row.update(overrides)
    return row


def snapshot(directory: Path) -> dict[str, bytes]:
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in directory.rglob("*") if path.is_file()}


class PredictionValidatorTests(unittest.TestCase):
    def test_repository_is_empty_formal_data_and_valid(self):
        before = snapshot(ROOT / "data" / "prediction")
        errors = prediction.validate_repository(ROOT)
        self.assertEqual(errors, [], "\n".join(errors))
        self.assertEqual(snapshot(ROOT / "data" / "prediction"), before)
        self.assertEqual(prediction.count_formal_rows(ROOT), 0)
        self.assertEqual(prediction.main(["--root", str(ROOT)]), 0)

    def test_example_file_is_labelled_and_has_no_numbers(self):
        document = json.loads((ROOT / "data" / "prediction" / "示例数据.json").read_text(encoding="utf-8"))
        self.assertEqual(document["数据性质"], "示例数据")
        self.assertIn("示例数据", document["警告"])

        def walk(value, path):
            self.assertNotIsInstance(value, bool)
            if isinstance(value, (int, float)):
                self.fail(f"示例数据含数字 {path}={value}")
            elif isinstance(value, dict):
                for key, item in value.items():
                    walk(item, f"{path}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{path}[{index}]")

        walk(document, "$")

    def test_readme_forbids_generating_numbers(self):
        text = (ROOT / "docs" / "prediction" / "README.md").read_text(encoding="utf-8")
        self.assertIn("周报只读台账，不生成新数字", text)
        for host in prediction.SOCIAL_HOSTS:
            self.assertIn(host, text)

    def test_decisions_record_the_confirmed_rules(self):
        text = (ROOT / "docs" / "prediction" / "DECISIONS.md").read_text(encoding="utf-8")
        for phrase in (
            "2026-11-25",
            "小区级",
            "全上海市",
            "≥5%",
            "≥8%",
            "连续 8 周",
            "少于 3 笔",
            "户数>50",
            "套均≤70㎡",
            "0–50",
            "0–30",
            "0–20",
            "禧泰",
            "中指",
            "权重为 0",
            "不相加",
            "沪拆信号周更",
            "沪拆信号发布校验",
            "程序内",
            "部分覆盖",
            "贴边",
            "待核",
            "纯征询",
            "grok.com",
        ):
            self.assertIn(phrase, text)
        for milestone in ("M0", "M1", "M2", "M3", "M4", "M5"):
            self.assertIn(milestone, text)

    def test_rejects_a_row_missing_source_or_caliber(self):
        missing_source = evidence()
        del missing_source["来源URL"]
        errors = prediction.row_errors("evidence", missing_source, example=False)
        self.assertTrue(any("缺少来源" in item for item in errors), errors)

        blank_source = evidence(来源URL="  ")
        errors = prediction.row_errors("evidence", blank_source, example=False)
        self.assertTrue(any("缺少来源" in item for item in errors), errors)

        missing_caliber = evidence()
        del missing_caliber["口径"]
        errors = prediction.row_errors("evidence", missing_caliber, example=False)
        self.assertTrue(any("缺少口径" in item for item in errors), errors)

        blank_caliber = programme(口径="  ")
        errors = prediction.row_errors("programmes", blank_caliber, example=False)
        self.assertTrue(any("缺少口径" in item for item in errors), errors)

    def test_rejects_mixed_price_and_netsign_calibers(self):
        mixed = evidence(字段="挂牌价", 口径="挂牌价/成交价", 值="原文")
        errors = prediction.row_errors("evidence", mixed, example=False)
        self.assertTrue(any("口径不得混用" in item for item in errors), errors)

        crossed = evidence(字段="挂牌价", 口径="成交价", 值="原文")
        errors = prediction.row_errors("evidence", crossed, example=False)
        self.assertTrue(any("不得混用" in item for item in errors), errors)

        added = evidence(字段="成交套数", 口径="网签商业口径", 值="与房管局住房口径合计")
        errors = prediction.row_errors("evidence", added, example=False)
        self.assertTrue(any("不得相加" in item for item in errors), errors)

    def test_rejects_derived_fields_social_sources_and_placeholders(self):
        derived = evidence(字段="超额涨幅", 值="原文")
        errors = prediction.row_errors("evidence", derived, example=False)
        self.assertTrue(any("派生结果" in item for item in errors), errors)

        social = evidence(来源URL="https://weibo.com/1")
        errors = prediction.row_errors("evidence", social, example=False)
        self.assertTrue(any("权重为 0" in item for item in errors), errors)

        placeholder = evidence(来源URL="https://example.com/notice")
        errors = prediction.row_errors("evidence", placeholder, example=False)
        self.assertTrue(any("example.com" in item for item in errors), errors)
        labelled = evidence(小区="测试小区（示例数据）", 来源URL="https://example.com/notice")
        self.assertEqual(prediction.row_errors("evidence", labelled, example=True), [])

    def test_programme_caliber_must_match_its_type(self):
        errors = prediction.row_errors("programmes", programme(类型="征询", 口径="决定"), example=False)
        self.assertTrue(any("征询不能写成决定" in item for item in errors), errors)
        self.assertEqual(prediction.row_errors("programmes", programme(), example=False), [])

    def test_community_numbers_must_match_a_confirmed_ledger_row(self):
        ledger = [evidence(字段="户数", 值="2", 口径="结构属性", 状态="已确认")]
        ok = prediction.dataset_errors(
            {"evidence": ledger, "programmes": [], "communities": [community(户数=2)], "observation_pool": []},
            example=False,
        )
        self.assertEqual(ok, [], ok)

        mismatch = prediction.dataset_errors(
            {"evidence": ledger, "programmes": [], "communities": [community(户数=3)], "observation_pool": []},
            example=False,
        )
        self.assertTrue(any("不要换算" in item for item in mismatch), mismatch)

        vague = [evidence(字段="户数", 值="约2", 口径="结构属性", 状态="已确认")]
        rejected = prediction.dataset_errors(
            {"evidence": vague, "programmes": [], "communities": [community(户数=2)], "observation_pool": []},
            example=False,
        )
        self.assertTrue(any("不要换算" in item for item in rejected), rejected)

    def test_pool_cites_the_ledger_and_does_not_score_unconfirmed_rows(self):
        pending = [evidence()]
        unconfirmed = prediction.dataset_errors(
            {"evidence": pending, "programmes": [], "communities": [], "observation_pool": [pool(档位="低")]},
            example=False,
        )
        self.assertTrue(any("待核证据不能单独支撑" in item for item in unconfirmed), unconfirmed)

        confirmed = [evidence(状态="已确认")]
        accepted = prediction.dataset_errors(
            {"evidence": confirmed, "programmes": [], "communities": [], "observation_pool": [pool(档位="低")]},
            example=False,
        )
        self.assertEqual(accepted, [], accepted)

        wrong_date = prediction.dataset_errors(
            {
                "evidence": pending,
                "programmes": [],
                "communities": [],
                "observation_pool": [pool(最后证据日期="2020-02-01")],
            },
            example=False,
        )
        self.assertTrue(any("最后证据日期" in item for item in wrong_date), wrong_date)

    def test_score_bounds_and_procedure_caliber(self):
        too_high = pool(分数分项={"程序": 51, "量价": None, "结构": None})
        errors = prediction.row_errors("observation_pool", too_high, example=False)
        self.assertTrue(any("大于上限" in item for item in errors), errors)

        price_on_procedure = pool(分数分项={"程序": None, "量价": 1, "结构": None})
        errors = prediction.row_errors("observation_pool", price_on_procedure, example=False)
        self.assertTrue(any("不能填写量价分" in item for item in errors), errors)

        self.assertTrue(any("不在允许的取值内" in item for item in prediction.row_errors(
            "evidence", evidence(区="浦东"), example=False
        )))
        self.assertTrue(any("不是有效日期" in item for item in prediction.row_errors(
            "evidence", evidence(来源日期="2020-02-31"), example=False
        )))

    def test_csv_must_match_json_and_unknown_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "data", root / "data")
            csv_path = root / "data" / "prediction" / "evidence.csv"
            csv_path.write_text(csv_path.read_text(encoding="utf-8") + "多余,一行\n", encoding="utf-8")
            errors = prediction.validate_repository(root)
            self.assertTrue(any("evidence" in item and ("列数不符" in item or "不一致" in item) for item in errors), errors)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "data", root / "data")
            (root / "data" / "prediction" / "notes.json").write_text("{}", encoding="utf-8")
            errors = prediction.validate_repository(root)
            self.assertTrue(any("未登记文件" in item for item in errors), errors)

    def test_script_does_not_touch_the_net_sign_pipeline(self):
        text = (ROOT / "scripts" / "validate_prediction.py").read_text(encoding="utf-8")
        for banned in ("fangdi", "pages.yml", "urlopen", "requests"):
            self.assertNotIn(banned, text)
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_prediction.py"), "--root", str(ROOT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("正式表 0 行", completed.stdout)


if __name__ == "__main__":
    unittest.main()
