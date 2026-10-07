"""集成测试共享辅助：建批次/晶圆/规则、生成扫描、跑作业。"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import numpy as np

from app.diode import diode_current
from app.db import get_conn
from app.ingestion import insert_chunk
from app.scheduler import JobScheduler

UTC = timezone.utc


def make_batch_wafer(name="w1", cols=4, rows=3):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO batches(name) VALUES ('b') RETURNING id")
            bid = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO wafers(batch_id,name,die_cols,die_rows) VALUES (%s,%s,%s,%s) RETURNING id",
                (bid, name, cols, rows),
            )
            wid = cur.fetchone()["id"]
        conn.commit()
    return bid, wid


def make_rule_version(
    n_range=(0.8, 1.6), is_range=(1e-16, 1e-9), rs_range=(0.0, 100.0),
    fail_is_bad=False, active=True,
):
    from psycopg.types.json import Jsonb

    rules = [
        {"param": "is", "lower": is_range[0], "upper": is_range[1],
         "fail_is_bad": fail_is_bad},
        {"param": "n", "lower": n_range[0], "upper": n_range[1],
         "fail_is_bad": fail_is_bad},
        {"param": "rs", "lower": rs_range[0], "upper": rs_range[1],
         "fail_is_bad": fail_is_bad},
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rule_versions(version,is_active,rules,published_at)
                SELECT coalesce(max(version),0)+1, %s, %s, now()
                FROM rule_versions
                RETURNING id, version
                """,
                (active, Jsonb(rules)),
            )
            row = cur.fetchone()
        conn.commit()
    return int(row["id"]), rules


def synth_scan(x, y, Is=1e-14, n=1.1, Rs=5.0, T=300.0, when=None,
               vmax=0.95, n_pts=40, seed=0):
    rng = np.random.default_rng(seed if seed else abs(x * 100 + y))
    v = np.linspace(0.05, vmax, n_pts)
    i = diode_current(v, Is, n, Rs, T) * np.exp(rng.normal(0, 0.004, n_pts))
    i = i + np.abs(rng.normal(0, 2e-13, n_pts))
    if when is None:
        when = datetime(2026, 10, 1, tzinfo=UTC)
    return {
        "x": x, "y": y, "temp_k": T, "tested_at": when,
        "voltage": v.tolist(), "current": i.tolist(),
    }


def upload_chunk(wafer_id, scans, seq=None):
    with get_conn() as conn:
        out = insert_chunk(conn, wafer_id, scans, chunk_seq=seq)
        conn.commit()
    return out


def run_job_to_completion(wafer_id):
    """用独立调度器同步跑完作业并返回最终 job 行。"""
    sched = JobScheduler(max_workers=1)
    try:
        job_id = sched.submit_wafer(wafer_id)
        deadline = time.time() + 60
        while True:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT state FROM jobs WHERE id=%s", (job_id,))
                    state = cur.fetchone()["state"]
            if state in ("done", "failed", "cancelled"):
                break
            if time.time() > deadline:
                raise AssertionError("作业超时")
            time.sleep(0.02)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
                job = cur.fetchone()
        assert state == "done", job.get("error")
        return job
    finally:
        sched.shutdown()


def all_die_results(wafer_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT die_x, die_y, is_value, n_value, rs_value, residual,
                       fit_ok, grade, rule_version_id
                FROM die_results ORDER BY die_y, die_x
                """
            )
            return [dict(r) for r in cur.fetchall()]
