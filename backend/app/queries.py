"""只读查询：晶圆图数据、单颗明细、规则版本重判级与对比。"""
from __future__ import annotations

from typing import Any

import numpy as np

from .diode import diode_current
from .grading import grade_results
from .ingestion import LATEST_SCAN_ANY_SQL, fetch_scan_at
from .processing import summarize


def _load_die_rows(conn, wafer_id: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT die_x, die_y, is_value, n_value, rs_value, residual,
                   rs_reliable, fit_ok, fail_reason, n_points, n_used,
                   grade, tested_at, rule_version_id
            FROM die_results WHERE wafer_id = %s
            ORDER BY die_y, die_x
            """,
            (wafer_id,),
        )
        return list(cur.fetchall())


def wafer_map(conn, wafer_id: int) -> dict[str, Any]:
    """整片结果 + 汇总 + 只剩拒收扫描的管芯列表。"""
    dies = _load_die_rows(conn, wafer_id)
    summary = summarize(dies) if dies else None
    rule_version_id = dies[0]["rule_version_id"] if dies else None

    # 只有拒收扫描、因此没有结果的管芯
    with conn.cursor() as cur:
        cur.execute(
            LATEST_SCAN_ANY_SQL,
            (wafer_id,),
        )
        latest_any = {
            (r["die_x"], r["die_y"]): r for r in cur.fetchall()
        }
    result_keys = {(d["die_x"], d["die_y"]) for d in dies}
    rejected = [
        {"die_x": r["die_x"], "die_y": r["die_y"],
         "reason": r["reject_reason"]}
        for (x, y), r in latest_any.items()
        if (x, y) not in result_keys and not r["valid"]
    ]
    return {
        "dies": dies,
        "summary": summary,
        "rule_version_id": rule_version_id,
        "rejected": sorted(rejected, key=lambda r: (r["die_y"], r["die_x"])),
    }


def die_detail(conn, wafer_id: int, x: int, y: int) -> dict[str, Any] | None:
    """单颗：测量点、拟合曲线、逐点残差。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM die_results WHERE wafer_id=%s AND die_x=%s AND die_y=%s",
            (wafer_id, x, y),
        )
        die = cur.fetchone()
        if die is None:
            return None

    scan = fetch_scan_at(conn, wafer_id, x, y)
    if scan is None:
        return None

    v = np.asarray(scan["voltage"], dtype=float)
    i = np.asarray(scan["current"], dtype=float)

    used_mask: list[bool] = []
    fit_v: list[float] = []
    fit_i: list[float] = []
    point_residual: list[float] = []
    if die["fit_ok"]:
        ihat_full = diode_current(
            v, die["is_value"], die["n_value"], die["rs_value"] or 0.0,
            scan["temp_k"],
        )
        # 与提取时一致：底噪剔除掩码
        from .config import settings

        used_mask = (i >= settings.noise_floor).tolist()
        fit_v = v.tolist()
        fit_i = ihat_full.tolist()
        with np.errstate(divide="ignore"):
            point_residual = (
                np.log10(np.maximum(ihat_full, 1e-300)) - np.log10(np.maximum(i, 1e-300))
            ).tolist()
    else:
        fit_v, fit_i, point_residual = [], [], []

    die.pop("id", None)
    die.pop("job_id", None)
    die.pop("wafer_id", None)
    die.pop("rule_version_id", None)
    return {
        "die": die,
        "voltage": v.tolist(),
        "current": i.tolist(),
        "used_mask": used_mask,
        "fit_voltage": fit_v,
        "fit_current": fit_i,
        "point_residual": point_residual,
        "temp_k": scan["temp_k"],
        "tested_at": scan["tested_at"],
        "reject_reason": scan["reject_reason"],
    }


def regrade(conn, wafer_id: int, rules: list[dict[str, Any]],
            new_rule_version_id: int) -> dict[str, Any]:
    """对已有结果按新规则重判级（只改 grade 与规则绑定，不重新拟合）。"""
    dies = _load_die_rows(conn, wafer_id)
    new_grades = grade_results(dies, rules)
    with conn.cursor() as cur:
        cur.executemany(
            """
            UPDATE die_results
               SET grade = %s, rule_version_id = %s
             WHERE wafer_id = %s AND die_x = %s AND die_y = %s
            """,
            [
                (g, new_rule_version_id, wafer_id, d["die_x"], d["die_y"])
                for d, g in zip(dies, new_grades)
            ],
        )
    for d, g in zip(dies, new_grades):
        d["grade"] = g
        d["rule_version_id"] = new_rule_version_id
    return summarize(dies) if dies else {}


def grade_diff(conn, wafer_id: int, version_from_id: int,
               version_to_id: int, rules_from: list[dict[str, Any]],
               rules_to: list[dict[str, Any]]) -> dict[str, Any]:
    """新旧规则版本下等级变化对比（参数不动）。"""
    dies = _load_die_rows(conn, wafer_id)
    g_from = grade_results(dies, rules_from)
    g_to = grade_results(dies, rules_to)
    changed = []
    for d, a, b in zip(dies, g_from, g_to):
        if a != b:
            changed.append(
                {"die_x": d["die_x"], "die_y": d["die_y"],
                 "grade_from": a, "grade_to": b}
            )
    dies_from = [{**d, "grade": a} for d, a in zip(dies, g_from)]
    dies_to = [{**d, "grade": b} for d, b in zip(dies, g_to)]
    return {
        "changed": changed,
        "summary_from": summarize(dies_from),
        "summary_to": summarize(dies_to),
    }
