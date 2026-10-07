"""规则版本切换：只改判级不改参数；版本对比正确。"""
from __future__ import annotations

from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from .factories import (
    all_die_results,
    make_batch_wafer,
    make_rule_version,
    run_job_to_completion,
    synth_scan,
    upload_chunk,
)
from app.db import get_conn
from app.queries import grade_diff, wafer_map
from app.grading import validate_rules

UTC = timezone.utc


def _setup_wafer():
    _, wid = make_batch_wafer(cols=4, rows=1)
    v1_id, _ = make_rule_version(n_range=(0.9, 1.5))  # 全部 pass
    t = datetime(2026, 10, 1, tzinfo=UTC)
    scans = [synth_scan(x, 0, n=(1.1 if x != 3 else 1.45), seed=x, when=t)
             for x in range(4)]
    upload_chunk(wid, scans)
    run_job_to_completion(wid)
    return wid, v1_id


def test_results_bound_to_rule_version(db):
    wid, v1_id = _setup_wafer()
    for r in all_die_results(wid):
        assert r["rule_version_id"] == v1_id
        assert r["grade"] == "pass"


def test_publish_new_version_regrades_only(db):
    wid, v1_id = _setup_wafer()
    before = all_die_results(wid)

    # 发布更严的 v2：n 上限 1.2 → (3,0) 的 n=1.45 变 fail
    v2_id, _ = make_rule_version(n_range=(0.9, 1.2))
    rules2 = [
        {"param": "is", "lower": 1e-16, "upper": 1e-9, "fail_is_bad": False},
        {"param": "n", "lower": 0.9, "upper": 1.2, "fail_is_bad": False},
        {"param": "rs", "lower": 0.0, "upper": 100.0, "fail_is_bad": False},
    ]
    with get_conn() as conn:
        from app.queries import regrade
        regrade(conn, wid, rules2, v2_id)
        conn.commit()

    after = all_die_results(wid)
    # 参数与残差必须逐字节级保持（同一批拟合结果）
    for a, b in zip(before, after):
        assert a["is_value"] == b["is_value"]
        assert a["n_value"] == b["n_value"]
        assert a["rs_value"] == b["rs_value"]
        assert a["residual"] == b["residual"]
        assert b["rule_version_id"] == v2_id

    grades = {(r["die_x"]): r["grade"] for r in after}
    assert grades[3] == "fail"
    assert grades[0] == "pass"


def test_grade_diff_reports_changed_dies(db):
    wid, v1_id = _setup_wafer()
    v2_id, _ = make_rule_version(n_range=(0.9, 1.2))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rules FROM rule_versions WHERE id=%s", (v1_id,))
            r1 = cur.fetchone()["rules"]
            cur.execute("SELECT rules FROM rule_versions WHERE id=%s", (v2_id,))
            r2 = cur.fetchone()["rules"]
        diff = grade_diff(conn, wid, v1_id, v2_id,
                          validate_rules(r1), validate_rules(r2))
    changed = {(c["die_x"], c["die_y"]): c for c in diff["changed"]}
    assert (3, 0) in changed
    assert changed[(3, 0)]["grade_from"] == "pass"
    assert changed[(3, 0)]["grade_to"] == "fail"
    assert diff["summary_from"]["yield"] == 1.0
    assert diff["summary_to"]["yield"] == 0.75


def test_regrade_does_not_refit(db):
    """重判级后 tested_at/job 绑定不变（没有新作业、没有新拟合）。"""
    wid, v1 = _setup_wafer()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM jobs")
            jobs_before = cur.fetchone()["c"]
    v2, _ = make_rule_version(n_range=(0.9, 1.0))
    rules = [
        {"param": "is", "lower": 1e-16, "upper": 1e-9, "fail_is_bad": True},
        {"param": "n", "lower": 0.9, "upper": 1.0, "fail_is_bad": True},
        {"param": "rs", "lower": 0.0, "upper": 100.0, "fail_is_bad": True},
    ]
    with get_conn() as conn:
        from app.queries import regrade
        regrade(conn, wid, rules, v2)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM jobs")
            assert cur.fetchone()["c"] == jobs_before
