"""整片晶圆处理作业：逐颗提取 → 判级 → 汇总 → 原子落库。

增量更新 vs 整片重算的权衡
--------------------------
本系统选择 **每次作业对整片刻“最终有效数据”全部重算**，而不是每来一块
增量更新。原因：

* 复测会改变任意一颗管芯的输入，且新块乱序到达时增量结果的中间态没有
  物理意义；整片重算的结果只取决于合并后的最终数据，天然满足
  “无论分块/顺序/复测次数，结果与一次性处理完全相同”；
* 单颗拟合是纯函数、互相独立，几千颗在秒级完成，重算代价可接受；
* 落库放在单事务里（先删后插），取消时直接不提交，天然不留半截结果。

代价：上传本身不触发结果更新，需要（由调度器在空闲时或用户手动）发起
一次作业；作业耗时与整片规模成正比而不是与本块大小成正比。换来的是
确定性和简单的取消/回滚语义。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .config import settings
from .extraction import extract_parameters
from .grading import grade_die, validate_rules

ProgressCb = Callable[[int, int, "JobHandle"], None]


@dataclass
class JobHandle:
    job_id: int
    wafer_id: int
    cancel_event: threading.Event
    state: str = "running"  # running / cancelled / failed / done
    error: str | None = None


def compute_wafer(
    scans: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    *,
    progress_cb: ProgressCb | None = None,
    handle: JobHandle | None = None,
) -> dict[str, Any] | None:
    """对合并后的扫描集合做纯计算（不碰数据库）。

    返回 ``{"dies": [...], "summary": {...}}``；被取消时返回 ``None``。
    每颗结果含坐标、参数、残差、是否成功、失败原因、等级、源扫描时间。
    """
    total = len(scans)
    dies: list[dict[str, Any]] = []
    n_failed = 0

    for idx, scan in enumerate(scans):
        if handle is not None and handle.cancel_event.is_set():
            return None

        v = np.asarray(scan["voltage"], dtype=float)
        i = np.asarray(scan["current"], dtype=float)
        res = extract_parameters(v, i, float(scan["temp_k"]))

        if res.ok:
            values = {"is": res.is_, "n": res.n, "rs": res.rs}
            grade = grade_die(values, True, rules)
            die = {
                "die_x": scan["die_x"],
                "die_y": scan["die_y"],
                "is_value": res.is_,
                "n_value": res.n,
                "rs_value": res.rs,
                "residual": res.residual,
                "rs_reliable": res.rs_reliable,
                "fit_ok": True,
                "fail_reason": None,
                "n_points": res.n_points,
                "n_used": res.n_used,
                "grade": grade,
                "tested_at": scan["tested_at"],
            }
        else:
            n_failed += 1
            grade = grade_die({"is": None, "n": None, "rs": None}, False, rules)
            die = {
                "die_x": scan["die_x"],
                "die_y": scan["die_y"],
                "is_value": res.is_,
                "n_value": res.n,
                "rs_value": res.rs,
                "residual": res.residual,
                "rs_reliable": res.rs_reliable,
                "fit_ok": False,
                "fail_reason": res.reason,
                "n_points": res.n_points,
                "n_used": res.n_used,
                "grade": grade,
                "tested_at": scan["tested_at"],
            }
        dies.append(die)

        if progress_cb is not None and handle is not None:
            progress_cb(idx + 1, total, handle)

    return {"dies": dies, "summary": summarize(dies)}


def _quantile(sorted_vals: list[float], q: float) -> float | None:
    """线性插值分位数（与 numpy 默认方法一致）。"""
    if not sorted_vals:
        return None
    arr = sorted_vals  # 已排序
    pos = (len(arr) - 1) * q
    lo = int(np.floor(pos))
    hi = int(np.ceil(pos))
    if lo == hi:
        return arr[lo]
    return arr[lo] * (hi - pos) + arr[hi] * (pos - lo)


def summarize(dies: list[dict[str, Any]]) -> dict[str, Any]:
    """整片汇总：各参数中位数、p5/p95、良率。

    良率 = pass /（pass+fail）；``ungraded``（提取失败且规则规定
    失败不算不良）不计入良率分母，但单独计数。
    """
    n_total = len(dies)
    n_pass = sum(1 for d in dies if d["grade"] == "pass")
    n_fail = sum(1 for d in dies if d["grade"] == "fail")
    n_ungraded = sum(1 for d in dies if d["grade"] == "ungraded")
    n_fit_fail = sum(1 for d in dies if not d["fit_ok"])
    denom = n_pass + n_fail
    yield_ = n_pass / denom if denom else None

    params: dict[str, Any] = {}
    for p in ("is_value", "n_value", "rs_value"):
        vals = sorted(d[p] for d in dies if d["fit_ok"] and d[p] is not None)
        params[p.replace("_value", "")] = {
            "median": _quantile(vals, 0.5),
            "p05": _quantile(vals, 0.05),
            "p95": _quantile(vals, 0.95),
            "count": len(vals),
        }

    return {
        "n_dies": n_total,
        "n_fit_failed": n_fit_fail,
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_ungraded": n_ungraded,
        "yield": yield_,
        "params": params,
    }


def persist_results(
    conn,
    *,
    wafer_id: int,
    job_id: int,
    rule_version_id: int,
    computed: dict[str, Any],
) -> None:
    """单事务整片替换结果（先删后插）。调用方控制事务边界。"""
    dies = computed["dies"]
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM die_results WHERE wafer_id = %s", (wafer_id,)
        )
        cur.executemany(
            """
            INSERT INTO die_results
              (wafer_id, die_x, die_y, job_id,
               is_value, n_value, rs_value, residual, rs_reliable,
               fit_ok, fail_reason, n_points, n_used,
               grade, rule_version_id, tested_at)
            VALUES (%(wafer_id)s,%(die_x)s,%(die_y)s,%(job_id)s,
                    %(is_value)s,%(n_value)s,%(rs_value)s,%(residual)s,%(rs_reliable)s,
                    %(fit_ok)s,%(fail_reason)s,%(n_points)s,%(n_used)s,
                    %(grade)s,%(rule_version_id)s,%(tested_at)s)
            """,
            [{**d, "wafer_id": wafer_id, "job_id": job_id,
              "rule_version_id": rule_version_id} for d in dies],
        )
