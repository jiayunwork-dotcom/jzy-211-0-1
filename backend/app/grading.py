"""判级规则与规则版本。

一个规则版本包含每个参数（``is``/``n``/``rs``）的上下限，以及
“提取失败算不算不良”的开关。判级只依赖参数与规则，不重新拟合，
因此发布新版本后可以对已有结果做纯重判级。

等级：

* ``pass``：全部参数在各自 [lower, upper] 内；
* ``fail``：某参数越界，或提取失败且 ``fail_is_bad=true``；
* ``ungraded``：提取失败且该版本规定失败不算不良（不计入良率分母）。
"""
from __future__ import annotations

from typing import Any, Literal

ParamName = Literal["is", "n", "rs"]
PARAMS: tuple[str, ...] = ("is", "n", "rs")


class RuleValidationError(ValueError):
    """规则定义非法。"""


def validate_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """校验并规范化规则列表。

    每条规则形如 ``{"param": "is", "lower": 1e-16, "upper": 1e-9,
    "fail_is_bad": false}``。参数至多出现一次，``lower <= upper``。
    """
    if not isinstance(rules, list) or not rules:
        raise RuleValidationError("规则至少要包含一条参数判级项")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in rules:
        if not isinstance(item, dict):
            raise RuleValidationError("规则项必须是对象")
        param = item.get("param")
        if param not in PARAMS:
            raise RuleValidationError(f"未知参数 {param!r}，可选 {PARAMS}")
        if param in seen:
            raise RuleValidationError(f"参数 {param} 的规则重复")
        seen.add(param)
        try:
            lower = float(item["lower"])
            upper = float(item["upper"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuleValidationError(f"参数 {param} 的上下限必须是数值") from exc
        if not (lower == lower and upper == upper):
            raise RuleValidationError(f"参数 {param} 的上下限不能是 NaN")
        if lower > upper:
            raise RuleValidationError(
                f"参数 {param} 的上限 {upper:g} 小于下限 {lower:g}"
            )
        fail_is_bad = bool(item.get("fail_is_bad", False))
        normalized.append(
            {
                "param": param,
                "lower": lower,
                "upper": upper,
                "fail_is_bad": fail_is_bad,
            }
        )
    return normalized


def grade_die(
    values: dict[str, float | None],
    fit_ok: bool,
    rules: list[dict[str, Any]],
) -> str:
    """按规则判级，返回 ``pass`` / ``fail`` / ``ungraded``。"""
    if not fit_ok:
        return "fail" if any(r["fail_is_bad"] for r in rules) else "ungraded"

    for r in rules:
        v = values.get(r["param"])
        if v is None:
            # 参数缺失（理论上 fit_ok 时不会发生）按未判级处理
            return "ungraded"
        if v < r["lower"] or v > r["upper"]:
            return "fail"
    return "pass"


def grade_results(
    results: list[dict[str, Any]], rules: list[dict[str, Any]]
) -> list[str]:
    """批量重判级，顺序与输入一致。仅改等级，不碰参数。"""
    out: list[str] = []
    for row in results:
        out.append(
            grade_die(
                {"is": row.get("is_value"), "n": row.get("n_value"),
                 "rs": row.get("rs_value")},
                bool(row.get("fit_ok")),
                rules,
            )
        )
    return out
