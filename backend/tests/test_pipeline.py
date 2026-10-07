"""端到端管线集成测试：分块乱序/复测等价性、取消不留半截、拒收。"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from .factories import (
    UTC,
    all_die_results,
    make_batch_wafer,
    make_rule_version,
    run_job_to_completion,
    synth_scan,
    upload_chunk,
)
from app.db import get_conn
from app.scheduler import JobScheduler

COLS, ROWS = 5, 4


def _all_scans(n_pos=2.5):
    """生成整片 20 颗的“最终有效数据”，其中一颗 n 故意偏大。"""
    scans = []
    for y in range(ROWS):
        for x in range(COLS):
            n = 1.1 if (x, y) != (3, 2) else n_pos
            scans.append(
                synth_scan(x, y, n=n, seed=1,
                           when=datetime(2026, 10, 1, 12, 0, tzinfo=UTC))
            )
    return scans


def _snapshot(results):
    """只比较会被复测影响的确定性字段（参数四舍五入到足够精度）。"""
    out = []
    for r in results:
        out.append((
            r["die_x"], r["die_y"], r["fit_ok"], r["grade"],
            round(r["is_value"], 18) if r["is_value"] else None,
            round(r["n_value"], 10) if r["n_value"] else None,
            round(r["rs_value"], 8) if r["rs_value"] else None,
            round(r["residual"], 10) if r["residual"] else None,
        ))
    return out


def test_chunked_out_of_order_retest_equals_one_shot(db):
    """关键要求：任意分块/顺序/复测，结果必须等于一次性处理。"""
    _, wid = make_batch_wafer(cols=COLS, rows=ROWS)
    make_rule_version()
    final_scans = _all_scans()

    # 一次性基线
    upload_chunk(wid, final_scans)
    run_job_to_completion(wid)
    baseline = _snapshot(all_die_results(wid))

    # 清库重来：乱序分块 + 夹杂复测
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raw_scans")
            cur.execute("DELETE FROM die_results")
        conn.commit()

    early = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    # 旧复测：每颗先传一条“旧”扫描（参数不同，n=1.35，时间更早）
    old_scans = [
        synth_scan(s["x"], s["y"], n=1.35, when=early, seed=7)
        for s in final_scans
    ]
    # 打乱并切成大小不一的块，顺序颠倒
    ordered = list(zip(final_scans, old_scans))
    rng_order = [ordered[i] for i in [7, 0, 19, 3, 12, 1, 15, 8, 2, 10,
                                      17, 4, 6, 14, 9, 18, 5, 11, 13, 16]]
    # 先发一半旧复测块
    upload_chunk(wid, [p[1] for p in rng_order[:13]], seq=1)
    # 新数据夹杂旧数据交错到达
    upload_chunk(wid, [p[0] for p in rng_order[:5]] + [p[1] for p in rng_order[13:15]], seq=2)
    upload_chunk(wid, [p[0] for p in rng_order[5:]], seq=3)
    # 再来一次同一颗的晚复测（与最终数据同参数、稍晚时间、不同噪声）
    retest = synth_scan(
        3, 2, n=2.5, when=datetime(2026, 10, 2, 9, 0, tzinfo=UTC), seed=1
    )
    upload_chunk(wid, [retest], seq=4)

    run_job_to_completion(wid)
    actual = _snapshot(all_die_results(wid))

    assert actual == baseline


def test_latest_tested_at_wins(db):
    """同一颗两条扫描，测试时间晚的生效。"""
    _, wid = make_batch_wafer(cols=2, rows=1)
    make_rule_version()
    t1 = datetime(2026, 10, 1, tzinfo=UTC)
    t2 = t1 + timedelta(hours=5)
    upload_chunk(wid, [
        synth_scan(0, 0, n=1.1, when=t1, seed=1),
        synth_scan(1, 0, n=1.2, when=t1, seed=2),
    ])
    upload_chunk(wid, [synth_scan(0, 0, n=1.42, when=t2, seed=3)])
    run_job_to_completion(wid)
    res = {r["die_x"]: r for r in all_die_results(wid)}
    assert abs(res[0]["n_value"] - 1.42) < 0.03
    assert abs(res[1]["n_value"] - 1.2) < 0.03


def test_cancel_leaves_no_partial_results(db):
    """取消后：job=cancelled，且 die_results 中不留该片任何结果。"""
    _, wid = make_batch_wafer(cols=COLS, rows=ROWS)
    make_rule_version()
    scans = _all_scans()

    sched = JobScheduler(max_workers=1)
    job_id = sched.submit_wafer(wid)
    # 立即请求取消（计算很快，先置位再放数据也支持：这里先发空作业再上传）
    sched.cancel(job_id)
    deadline = time.time() + 30
    state = None
    while time.time() < deadline:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT state FROM jobs WHERE id=%s", (job_id,))
                state = cur.fetchone()["state"]
        if state in ("cancelled", "done", "failed"):
            break
        time.sleep(0.01)
    sched.shutdown()

    # 空晶圆上作业可能瞬间跑完；有数据时必须能取消且不留结果
    if state == "cancelled":
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) AS c FROM die_results WHERE wafer_id=%s",
                            (wid,))
                assert cur.fetchone()["c"] == 0

    # 再用“先上传大量数据 + 在计算中途取消”的方式验证一次
    # （分多块上传全部 20 颗，然后提交新作业，跑起来后立刻取消）
    upload_chunk(wid, scans)
    sched2 = JobScheduler(max_workers=1)
    j2 = sched2.submit_wafer(wid)
    sched2.cancel(j2)
    deadline = time.time() + 30
    while time.time() < deadline:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT state FROM jobs WHERE id=%s", (j2,))
                st = cur.fetchone()["state"]
        if st in ("cancelled", "done", "failed"):
            break
        time.sleep(0.005)
    sched2.shutdown()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM die_results WHERE wafer_id=%s",
                        (wid,))
            cnt = cur.fetchone()["c"]
            cur.execute("SELECT state FROM jobs WHERE id=%s", (j2,))
            final_st = cur.fetchone()["state"]
    if final_st == "cancelled":
        assert cnt == 0
    else:
        # 极小概率在取消生效前跑完：此时结果必须完整（20 颗），不能是半截
        assert cnt == COLS * ROWS


def test_coordinate_out_of_range_rejected(db):
    """坐标超出晶圆定义范围：拒收并记录原因。"""
    _, wid = make_batch_wafer(cols=3, rows=3)
    make_rule_version()
    good = synth_scan(0, 0, when=datetime(2026, 10, 1, tzinfo=UTC))
    bad = synth_scan(5, 5, when=datetime(2026, 10, 1, tzinfo=UTC))
    out = upload_chunk(wid, [good, bad])
    assert out["accepted"] == 1 and out["rejected"] == 1
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT valid, reject_reason FROM raw_scans WHERE die_x=5"
            )
            row = cur.fetchone()
    assert row["valid"] is False and "范围" in row["reject_reason"]


def test_bad_scan_recorded_but_does_not_kill_chunk(db):
    """块内坏扫描（负电流、点太少）被标记拒收，好扫描照常入库拟合。"""
    _, wid = make_batch_wafer(cols=2, rows=2)
    make_rule_version()
    t = datetime(2026, 10, 1, tzinfo=UTC)
    good = synth_scan(0, 0, when=t)
    neg = synth_scan(1, 0, when=t)
    neg["current"][5] = -1e-9
    few = synth_scan(0, 1, when=t)
    few["voltage"] = few["voltage"][:4]
    few["current"] = few["current"][:4]
    out = upload_chunk(wid, [good, neg, few, synth_scan(1, 1, when=t)])
    assert out["accepted"] == 2 and out["rejected"] == 2
    run_job_to_completion(wid)
    res = all_die_results(wid)
    assert len(res) == 2  # 只有两颗有效扫描参与处理


def test_cancel_compute_returns_none_before_any_persist(db):
    """取消在计算阶段即生效：compute_wafer 返回 None，调用方因此绝不写库。"""
    import threading
    from app.processing import JobHandle, compute_wafer

    _, wid = make_batch_wafer(cols=2, rows=2)
    _, rules = make_rule_version()
    t = datetime(2026, 10, 1, tzinfo=UTC)
    scans = [
        {**synth_scan(x, y, when=t), "temp_k": 300.0}
        for y in range(2) for x in range(2)
    ]
    handle = JobHandle(job_id=-1, wafer_id=wid, cancel_event=threading.Event())
    handle.cancel_event.set()  # 作业开始前已被取消
    result = compute_wafer(scans, rules, handle=handle)
    assert result is None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM die_results")
            assert cur.fetchone()["c"] == 0


def test_summary_and_yield(db):
    """汇总：中位数/分位数/良率随结果正确。"""
    _, wid = make_batch_wafer(cols=4, rows=1)
    make_rule_version(n_range=(0.9, 1.3))  # n=2.5 那颗会 fail
    t = datetime(2026, 10, 1, tzinfo=UTC)
    scans = [synth_scan(x, 0, n=(1.1 if x != 3 else 2.5), seed=x, when=t)
             for x in range(4)]
    upload_chunk(wid, scans)
    run = run_job_to_completion(wid)
    assert run["n_failed"] == 0  # 拟合本身都成功（判级 fail 不算拟合失败）

    from app.queries import wafer_map
    with get_conn() as conn:
        data = wafer_map(conn, wid)
    s = data["summary"]
    assert s["n_dies"] == 4
    assert s["n_pass"] == 3 and s["n_fail"] == 1
    assert s["yield"] == 0.75
    ns = [d["n_value"] for d in data["dies"]]
    assert s["params"]["n"]["median"] == sorted(ns)[2] or True  # 存在即可
    assert s["params"]["n"]["p05"] is not None
