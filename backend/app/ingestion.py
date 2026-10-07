"""数据接入：分块上传的校验、入库与复测合并。

复测合并规则（对整颗管芯的全部历史扫描取“最终有效数据”）：

1. 通过结构校验（含坐标范围）的扫描优先于被拒收的扫描；
2. 同为有效时，以测试时间 ``tested_at`` 较晚者为准；
3. 测试时间相同则以较晚上传（行 id 较大）者为准。

因此无论分块多少、到达顺序如何、中间夹多少次复测，每颗管芯最终
选定的扫描都是确定的、与一次性提交相同。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from .extraction import validate_scan

# 坐标范围错误与扫描内容错误分开提示
class IngestionError(ValueError):
    """整块数据不可接受（如晶圆不存在）。"""


def _validate_payload_scan(
    scan: dict[str, Any], die_cols: int, die_rows: int
) -> tuple[bool, str | None, np.ndarray, np.ndarray, float]:
    """对一条扫描做入库前校验，返回 (valid, reason, V, I, temp)。

    校验项：点数 ≥5、电压严格单调、无负电流/非数值、温度 200–500 K、
    管芯坐标在晶圆定义范围内。不合法的扫描仍入库（valid=false），
    合并时有效扫描优先。
    """
    x = scan.get("x")
    y = scan.get("y")
    if not isinstance(x, int) or isinstance(x, bool) or not isinstance(y, int) or isinstance(y, bool):
        return False, "管芯坐标必须为整数", np.empty(0), np.empty(0), 0.0
    if not (0 <= x < die_cols and 0 <= y < die_rows):
        return (
            False,
            f"管芯坐标 ({x},{y}) 超出晶圆范围 "
            f"[0,{die_cols})×[0,{die_rows})",
            np.empty(0),
            np.empty(0),
            0.0,
        )

    temp = scan.get("temp_k")
    try:
        temp_f = float(temp)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False, "测试温度不是数值", np.empty(0), np.empty(0), 0.0

    v = np.asarray(scan.get("voltage", []), dtype=float)
    i = np.asarray(scan.get("current", []), dtype=float)
    try:
        validate_scan(v, i, temp_f)
    except Exception as exc:
        return False, str(exc), v, i, temp_f
    return True, None, v, i, temp_f


def insert_chunk(
    conn,
    wafer_id: int,
    scans: list[dict[str, Any]],
    *,
    chunk_seq: int | None = None,
) -> dict[str, int]:
    """把一个上传块写入 ``raw_scans``，返回接收计数。

    调用方负责事务（本函数不 commit）。晶圆必须已存在。
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT die_cols, die_rows FROM wafers WHERE id = %s", (wafer_id,)
        )
        wafer = cur.fetchone()
        if wafer is None:
            raise IngestionError(f"晶圆 id={wafer_id} 不存在")

        accepted = rejected = 0
        rows = []
        for scan in scans:
            tested_at = scan.get("tested_at")
            if isinstance(tested_at, str):
                try:
                    tested_at = datetime.fromisoformat(tested_at.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise IngestionError(f"tested_at 不是合法 ISO 8601 时间: {exc}") from exc
            if not isinstance(tested_at, datetime):
                raise IngestionError("每条扫描必须带 ISO 8601 的 tested_at")

            valid, reason, v, i, temp_f = _validate_payload_scan(
                scan, wafer["die_cols"], wafer["die_rows"]
            )
            rows.append(
                (
                    wafer_id,
                    int(scan["x"]),
                    int(scan["y"]),
                    tested_at,
                    temp_f if valid else float(scan.get("temp_k") or 0.0),
                    v.tolist(),
                    i.tolist(),
                    valid,
                    reason,
                    chunk_seq,
                )
            )
            if valid:
                accepted += 1
            else:
                rejected += 1

        cur.executemany(
            """
            INSERT INTO raw_scans
              (wafer_id, die_x, die_y, tested_at, temp_k,
               voltage, current, valid, reject_reason, chunk_seq)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            rows,
        )
    return {"accepted": accepted, "rejected": rejected, "total": len(rows)}


LATEST_SCAN_SQL = """
SELECT DISTINCT ON (die_x, die_y)
       id, die_x, die_y, tested_at, temp_k, voltage, current,
       valid, reject_reason
FROM raw_scans
WHERE wafer_id = %s AND valid
ORDER BY die_x, die_y, tested_at DESC, id DESC
"""

LATEST_SCAN_ANY_SQL = """
SELECT DISTINCT ON (die_x, die_y)
       id, die_x, die_y, tested_at, temp_k, voltage, current,
       valid, reject_reason
FROM raw_scans
WHERE wafer_id = %s
ORDER BY die_x, die_y, valid DESC, tested_at DESC, id DESC
"""


def fetch_latest_scans(conn, wafer_id: int) -> list[dict[str, Any]]:
    """返回每颗管芯的最终有效扫描（复测合并后）。

    只选 ``valid`` 的扫描——某颗管芯所有历史扫描都被拒收时，
    它不会出现在结果里（拒收明细可经 :func:`fetch_latest_scans_any`
    在作业记录中体现）。
    """
    with conn.cursor() as cur:
        cur.execute(LATEST_SCAN_SQL, (wafer_id,))
        return list(cur.fetchall())


def fetch_latest_scans_any(conn, wafer_id: int) -> list[dict[str, Any]]:
    """同 :func:`fetch_latest_scans`，但包含只剩拒收扫描的管芯（用于失败登记）。"""
    with conn.cursor() as cur:
        cur.execute(LATEST_SCAN_ANY_SQL, (wafer_id,))
        return list(cur.fetchall())


def fetch_scan_at(conn, wafer_id: int, x: int, y: int) -> dict[str, Any] | None:
    """单颗管芯的最终有效扫描（有效优先，其次最新一条——用于展示拒收原因）。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM (
                SELECT DISTINCT ON (die_x, die_y)
                       id, die_x, die_y, tested_at, temp_k, voltage, current,
                       valid, reject_reason
                FROM raw_scans
                WHERE wafer_id = %s AND die_x = %s AND die_y = %s
                ORDER BY die_x, die_y, valid DESC, tested_at DESC, id DESC
            ) s
            """,
            (wafer_id, x, y),
        )
        return cur.fetchone()
