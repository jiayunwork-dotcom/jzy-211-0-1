"""批次与晶圆、数据块上传路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn
from ..ingestion import IngestionError, insert_chunk
from ..schemas import BatchCreate, BatchOut, ChunkIn, ChunkOut, WaferCreate, WaferOut

router = APIRouter(tags=["batches"])


@router.post("/batches", response_model=BatchOut, status_code=201)
def create_batch(body: BatchCreate) -> BatchOut:
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO batches(name) VALUES (%s) RETURNING id, name, created_at",
                    (body.name,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                cur.execute(
                    "SELECT id, name, created_at FROM batches WHERE name=%s",
                    (body.name,),
                )
                row = cur.fetchone()
            conn.commit()
    return BatchOut(id=row["id"], name=row["name"],
                    created_at=row["created_at"], n_wafers=0)


@router.get("/batches", response_model=list[BatchOut])
def list_batches() -> list[BatchOut]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT b.id, b.name, b.created_at,
                       (SELECT count(*) FROM wafers w WHERE w.batch_id=b.id) AS n_wafers
                FROM batches b ORDER BY b.created_at DESC
                """
            )
            rows = cur.fetchall()
    return [BatchOut(**r) for r in rows]


@router.post("/wafers", response_model=WaferOut, status_code=201)
def create_wafer(body: WaferCreate) -> WaferOut:
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO wafers(batch_id, name, die_cols, die_rows)
                    VALUES (%s,%s,%s,%s)
                    RETURNING id, batch_id, name, die_cols, die_rows
                    """,
                    (body.batch_id, body.name, body.die_cols, body.die_rows),
                )
                row = cur.fetchone()
                conn.commit()
            except Exception as exc:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"创建晶圆失败：{exc}") from exc
    return WaferOut(**row)


@router.get("/batches/{batch_id}/wafers", response_model=list[WaferOut])
def list_wafers(batch_id: int) -> list[WaferOut]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, batch_id, name, die_cols, die_rows
                FROM wafers WHERE batch_id=%s ORDER BY name
                """,
                (batch_id,),
            )
            rows = cur.fetchall()
    return [WaferOut(**r) for r in rows]


@router.post("/chunks", response_model=ChunkOut, status_code=202)
def upload_chunk(body: ChunkIn) -> ChunkOut:
    """上传一个数据块。非法扫描计入 rejected 但不阻断整批；
    只有整块级错误（晶圆不存在等）返回 4xx。"""
    scans = [s.model_dump() for s in body.scans]
    # model_dump 已把 tested_at 转成 datetime
    with get_conn() as conn:
        try:
            result = insert_chunk(
                conn, body.wafer_id, scans, chunk_seq=body.chunk_seq
            )
            conn.commit()
        except IngestionError as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChunkOut(**result)
