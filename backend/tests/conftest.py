"""集成测试夹具：连接本地 PostgreSQL（DATABASE_URL 可覆盖）。

默认连接开发沙箱里的便携 PG：``host=/tmp user=postgres dbname=diodetest``。
CI 中通过 DATABASE_URL 指向 postgres:16 服务。
"""
from __future__ import annotations

import os
import time

import pytest

TEST_DB_URL = os.environ.get(
    "DATABASE_URL", "host=/tmp user=postgres dbname=diodetest"
)


@pytest.fixture(scope="session")
def database_url() -> str:
    # 等库可连（CI 里 postgres 容器可能刚起）
    import psycopg

    deadline = time.time() + 30
    while True:
        try:
            with psycopg.connect(TEST_DB_URL, connect_timeout=2) as c:
                c.execute("SELECT 1")
            break
        except Exception:
            if time.time() > deadline:
                pytest.skip(f"测试数据库不可用：{TEST_DB_URL}")
            time.sleep(1)
    return TEST_DB_URL


@pytest.fixture()
def db(database_url, monkeypatch):
    """每个函数一个干净 schema，并初始化全局连接池。"""
    from app import db as db_mod
    from app.db import get_conn

    monkeypatch.setenv("DATABASE_URL", database_url)
    if db_mod.pool is not None:
        db_mod.close_pool()
    db_mod.init_pool(database_url)

    with get_conn() as conn:
        with conn.cursor() as cur:
            for tbl in (
                "die_results", "jobs", "raw_scans", "wafers", "batches",
                "rule_versions",
            ):
                cur.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
        conn.commit()
    db_mod.init_db()
    yield db_mod
    db_mod.close_pool()
