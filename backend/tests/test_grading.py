"""判级规则校验与判级逻辑测试。"""
from __future__ import annotations

import pytest

from app.grading import RuleValidationError, grade_die, grade_results, validate_rules


def test_rule_upper_below_lower_rejected():
    with pytest.raises(RuleValidationError, match="上限"):
        validate_rules([{"param": "n", "lower": 2.0, "upper": 1.0}])


def test_rule_unknown_param_rejected():
    with pytest.raises(RuleValidationError):
        validate_rules([{"param": "bogus", "lower": 0, "upper": 1}])


def test_rule_duplicate_param_rejected():
    with pytest.raises(RuleValidationError, match="重复"):
        validate_rules([
            {"param": "n", "lower": 1, "upper": 2},
            {"param": "n", "lower": 1, "upper": 3},
        ])


def test_grade_pass_fail_ungraded():
    rules = [
        {"param": "is", "lower": 1e-16, "upper": 1e-10, "fail_is_bad": False},
        {"param": "n", "lower": 0.9, "upper": 1.5, "fail_is_bad": False},
        {"param": "rs", "lower": 0.0, "upper": 20.0, "fail_is_bad": False},
    ]
    good = {"is": 1e-14, "n": 1.1, "rs": 5.0}
    assert grade_die(good, True, rules) == "pass"
    bad = {"is": 1e-14, "n": 2.0, "rs": 5.0}
    assert grade_die(bad, True, rules) == "fail"

    # 提取失败：fail_is_bad=false → ungraded；true → fail
    rules_bad = [{**r, "fail_is_bad": True} for r in rules]
    assert grade_die({"is": None, "n": None, "rs": None}, False, rules) == "ungraded"
    assert grade_die({"is": None, "n": None, "rs": None}, False, rules_bad) == "fail"


def test_grade_results_only_changes_grade():
    rules = [{"param": "n", "lower": 1.0, "upper": 1.5, "fail_is_bad": True}]
    rows = [
        {"fit_ok": True, "is_value": 1e-14, "n_value": 1.2, "rs_value": 1.0,
         "grade": "pass"},
        {"fit_ok": True, "is_value": 1e-14, "n_value": 1.8, "rs_value": 1.0,
         "grade": "pass"},
    ]
    grades = grade_results(rows, rules)
    assert grades == ["pass", "fail"]
    # 参数本身不被改动
    assert rows[1]["n_value"] == 1.8
