"""PostgreSQL 访问层（psycopg3 连接池 + 建表）。"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

pool: ConnectionPool | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS batches (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wafers (
    id          BIGSERIAL PRIMARY KEY,
    batch_id    BIGINT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    die_cols    INTEGER NOT NULL,
    die_rows    INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (batch_id, name),
    CHECK (die_cols > 0 AND die_rows > 0)
);

-- 原始扫描（分块上传，含复测；不过期，是“最终有效数据”的唯一事实来源）
CREATE TABLE IF NOT EXISTS raw_scans (
    id           BIGSERIAL PRIMARY KEY,
    wafer_id     BIGINT NOT NULL REFERENCES wafers(id) ON DELETE CASCADE,
    die_x        INTEGER NOT NULL,
    die_y        INTEGER NOT NULL,
    tested_at    TIMESTAMPTZ NOT NULL,
    temp_k       DOUBLE PRECISION NOT NULL,
    voltage      DOUBLE PRECISION[] NOT NULL,
    current      DOUBLE PRECISION[] NOT NULL,
    valid        BOOLEAN NOT NULL,
    reject_reason TEXT,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    chunk_seq    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_raw_wafer ON raw_scans(wafer_id);
-- 复测合并用的“每颗取最新一条”索引
CREATE INDEX IF NOT EXISTS idx_raw_merge
    ON raw_scans(wafer_id, die_x, die_y, tested_at DESC, id DESC);

-- 判级规则版本
CREATE TABLE IF NOT EXISTS rule_versions (
    id           BIGSERIAL PRIMARY KEY,
    version      INTEGER NOT NULL UNIQUE,
    is_active    BOOLEAN NOT NULL DEFAULT FALSE,
    -- 每项: {param: 'is'|'n'|'rs', lower, upper, fail_is_bad: bool}
    rules        JSONB NOT NULL,
    note         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ
);

-- 整片处理作业
CREATE TABLE IF NOT EXISTS jobs (
    id          BIGSERIAL PRIMARY KEY,
    wafer_id    BIGINT NOT NULL REFERENCES wafers(id) ON DELETE CASCADE,
    state       TEXT NOT NULL DEFAULT 'pending',  -- pending/running/cancelled/done/failed
    total       INTEGER NOT NULL DEFAULT 0,
    processed   INTEGER NOT NULL DEFAULT 0,
    n_failed    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    rule_version_id BIGINT REFERENCES rule_versions(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_jobs_wafer ON jobs(wafer_id, id DESC);

-- 每颗管芯的提取结果（作业整片重算后原子替换）
CREATE TABLE IF NOT EXISTS die_results (
    id           BIGSERIAL PRIMARY KEY,
    wafer_id     BIGINT NOT NULL REFERENCES wafers(id) ON DELETE CASCADE,
    die_x        INTEGER NOT NULL,
    die_y        INTEGER NOT NULL,
    job_id       BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    is_value     DOUBLE PRECISION,
    n_value      DOUBLE PRECISION,
    rs_value     DOUBLE PRECISION,
    residual     DOUBLE PRECISION,
    rs_reliable  BOOLEAN NOT NULL DEFAULT FALSE,
    fit_ok       BOOLEAN NOT NULL,
    fail_reason  TEXT,
    n_points     INTEGER NOT NULL DEFAULT 0,
    n_used       INTEGER NOT NULL DEFAULT 0,
    grade        TEXT NOT NULL DEFAULT 'ungraded',  -- pass/fail/ungraded
    rule_version_id BIGINT REFERENCES rule_versions(id),
    tested_at    TIMESTAMPTZ NOT NULL,
    UNIQUE (wafer_id, die_x, die_y)
);
CREATE INDEX IF NOT EXISTS idx_die_wafer ON die_results(wafer_id);
"""


def init_pool(database_url: str | None = None) -> ConnectionPool:
    """初始化全局连接池。"""
    global pool
    url = database_url or settings.database_url
    if not url:
        raise RuntimeError("DATABASE_URL 未配置")
    pool = ConnectionPool(
        url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        kwargs={"row_factory": dict_row, "autocommit": False},
        open=True,
    )
    return pool


def close_pool() -> None:
    global pool
    if pool is not None:
        pool.close()
        pool = None


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    if pool is None:
        init_pool()
    assert pool is not None
    with pool.connection() as conn:
        yield conn


def init_db() -> None:
    """建表（幂等）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()


if __name__ == "__main__":  # 手工初始化: python -m app.db
    url = os.environ.get("DATABASE_URL")
    init_pool(url)
    init_db()
    print("schema initialized")
