"""请求/响应 Pydantic 模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---- 上传 ----
class ScanIn(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    temp_k: float
    tested_at: datetime
    voltage: list[float]
    current: list[float]


class ChunkIn(BaseModel):
    wafer_id: int
    chunk_seq: int | None = None
    scans: list[ScanIn]


class ChunkOut(BaseModel):
    accepted: int
    rejected: int
    total: int


class BatchCreate(BaseModel):
    name: str


class WaferCreate(BaseModel):
    batch_id: int
    name: str
    die_cols: int = Field(gt=0)
    die_rows: int = Field(gt=0)


# ---- 规则版本 ----
class RuleItem(BaseModel):
    param: Literal["is", "n", "rs"]
    lower: float
    upper: float
    fail_is_bad: bool = False


class RuleVersionCreate(BaseModel):
    rules: list[RuleItem]
    note: str | None = None
    activate: bool = True


class RuleVersionOut(BaseModel):
    id: int
    version: int
    is_active: bool
    rules: list[dict[str, Any]]
    note: str | None
    created_at: datetime
    published_at: datetime | None


# ---- 查询 ----
class BatchOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    n_wafers: int


class WaferOut(BaseModel):
    id: int
    batch_id: int
    name: str
    die_cols: int
    die_rows: int


class DieResultOut(BaseModel):
    die_x: int
    die_y: int
    is_value: float | None
    n_value: float | None
    rs_value: float | None
    residual: float | None
    rs_reliable: bool
    fit_ok: bool
    fail_reason: str | None
    n_points: int
    n_used: int
    grade: str
    tested_at: datetime


class WaferMapOut(BaseModel):
    wafer: WaferOut
    rule_version_id: int | None
    summary: dict[str, Any]
    dies: list[DieResultOut]
    rejected: list[dict[str, Any]]


class DieDetailOut(BaseModel):
    die: DieResultOut
    voltage: list[float]
    current: list[float]
    used_mask: list[bool]
    fit_voltage: list[float]
    fit_current: list[float]
    point_residual: list[float]


class JobOut(BaseModel):
    id: int
    wafer_id: int
    state: str
    total: int
    processed: int
    n_failed: int
    error: str | None
    rule_version_id: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class GradeDiffOut(BaseModel):
    rule_from: int
    rule_to: int
    changed: list[dict[str, Any]]
    summary_from: dict[str, Any]
    summary_to: dict[str, Any]
