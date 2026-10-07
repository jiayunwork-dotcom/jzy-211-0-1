"""处理作业路由：发起、查询进度、取消。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn
from ..scheduler import scheduler
from ..schemas import JobOut

router = APIRouter(tags=["jobs"])


def _get_job(conn, job_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="作业不存在")
    return row


@router.post("/wafers/{wafer_id}/jobs", response_model=JobOut, status_code=202)
def start_job(wafer_id: int) -> JobOut:
    """对整片晶圆发起（或复用正在进行的）后台处理作业。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM wafers WHERE id=%s", (wafer_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="晶圆不存在")
        conn.commit()
    try:
        job_id = scheduler.submit_wafer(wafer_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with get_conn() as conn:
        row = _get_job(conn, job_id)
    return JobOut(**row)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int) -> JobOut:
    with get_conn() as conn:
        row = _get_job(conn, job_id)
    return JobOut(**row)


@router.get("/wafers/{wafer_id}/jobs", response_model=list[JobOut])
def list_jobs(wafer_id: int) -> list[JobOut]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM jobs WHERE wafer_id=%s ORDER BY id DESC",
                (wafer_id,),
            )
            rows = cur.fetchall()
    return [JobOut(**r) for r in rows]


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int) -> JobOut:
    ok = scheduler.cancel(job_id)
    with get_conn() as conn:
        row = _get_job(conn, job_id)
    if not ok and row["state"] not in ("cancelled", "done", "failed"):
        raise HTTPException(status_code=409, detail="作业不在可取消状态")
    return JobOut(**row)
