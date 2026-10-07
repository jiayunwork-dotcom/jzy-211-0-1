"""晶圆结果查询：晶圆图、单颗明细。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn
from ..queries import die_detail, wafer_map
from ..schemas import DieDetailOut, WaferMapOut, WaferOut

router = APIRouter(tags=["wafers"])


@router.get("/wafers/{wafer_id}/map", response_model=WaferMapOut)
def get_wafer_map(wafer_id: int) -> WaferMapOut:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, batch_id, name, die_cols, die_rows FROM wafers WHERE id=%s",
                (wafer_id,),
            )
            wafer = cur.fetchone()
        if wafer is None:
            raise HTTPException(status_code=404, detail="晶圆不存在")
        data = wafer_map(conn, wafer_id)
    return WaferMapOut(
        wafer=WaferOut(**wafer),
        rule_version_id=data["rule_version_id"],
        summary=data["summary"] or {},
        dies=data["dies"],
        rejected=data["rejected"],
    )


@router.get("/wafers/{wafer_id}/dies/{x}/{y}", response_model=DieDetailOut)
def get_die_detail(wafer_id: int, x: int, y: int) -> DieDetailOut:
    with get_conn() as conn:
        detail = die_detail(conn, wafer_id, x, y)
    if detail is None:
        raise HTTPException(status_code=404, detail="该管芯无结果或不存在")
    return DieDetailOut(**detail)
