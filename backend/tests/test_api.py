"""HTTP 接口测试（FastAPI TestClient + 真实 PG）。"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

UTC = timezone.utc


@pytest.fixture()
def client(db):
    from app.main import create_app
    from app.scheduler import JobScheduler

    app = create_app(JobScheduler(max_workers=2))
    with TestClient(app) as c:
        yield c


def _scan_dict(x, y, n=1.1, when="2026-10-01T12:00:00+00:00"):
    from .factories import synth_scan

    s = synth_scan(x, y, n=n, when=datetime(2026, 10, 1, 12, tzinfo=UTC))
    s["tested_at"] = when
    return s


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_batch_wafer_chunk_job_flow(client):
    r = client.post("/batches", json={"name": "batchA"})
    assert r.status_code == 201
    bid = r.json()["id"]

    r = client.post("/wafers", json={
        "batch_id": bid, "name": "wf-01", "die_cols": 3, "die_rows": 2,
    })
    assert r.status_code == 201
    wid = r.json()["id"]

    # 规则版本
    r = client.post("/rule-versions", json={
        "rules": [
            {"param": "is", "lower": 1e-16, "upper": 1e-9},
            {"param": "n", "lower": 0.8, "upper": 1.6},
            {"param": "rs", "lower": 0, "upper": 100},
        ],
        "note": "v1",
    })
    assert r.status_code == 201

    # 上传两块（含一颗坏扫描）
    scans = [_scan_dict(x, y) for y in range(2) for x in range(3)]
    bad = _scan_dict(0, 0)
    bad["current"][3] = -5e-9
    r = client.post("/chunks", json={"wafer_id": wid, "chunk_seq": 1,
                                     "scans": scans})
    assert r.status_code == 202
    assert r.json()["accepted"] == 6

    # 发起作业并轮询到完成
    r = client.post(f"/wafers/{wid}/jobs")
    assert r.status_code == 202
    job_id = r.json()["id"]
    for _ in range(200):
        j = client.get(f"/jobs/{job_id}").json()
        if j["state"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.03)
    assert j["state"] == "done", j

    # 晶圆图
    r = client.get(f"/wafers/{wid}/map")
    assert r.status_code == 200
    mp = r.json()
    assert len(mp["dies"]) == 6
    assert mp["summary"]["n_pass"] == 6
    assert mp["wafer"]["die_cols"] == 3

    # 单颗明细：测量点 + 拟合曲线 + 残差
    r = client.get(f"/wafers/{wid}/dies/1/1")
    assert r.status_code == 200
    det = r.json()
    assert len(det["voltage"]) == len(det["fit_voltage"]) == 40
    assert len(det["point_residual"]) == 40
    assert det["die"]["fit_ok"] is True


def test_chunk_unknown_wafer_400(client):
    r = client.post("/chunks", json={
        "wafer_id": 99999,
        "scans": [_scan_dict(0, 0)],
    })
    assert r.status_code == 400


def test_coordinate_out_of_range_rejected_at_upload(client):
    client.post("/batches", json={"name": "b2"})
    bid = client.get("/batches").json()[0]["id"]
    wid = client.post("/wafers", json={
        "batch_id": bid, "name": "w", "die_cols": 2, "die_rows": 2,
    }).json()["id"]
    r = client.post("/chunks", json={
        "wafer_id": wid,
        "scans": [_scan_dict(2, 0)],  # x=2 越界
    })
    body = r.json()
    assert r.status_code == 202
    assert body["rejected"] == 1 and body["accepted"] == 0


def test_rule_upper_below_lower_400(client):
    r = client.post("/rule-versions", json={
        "rules": [{"param": "n", "lower": 2, "upper": 1}],
    })
    assert r.status_code == 400
    assert "上限" in r.json()["detail"]


def test_job_cancel_endpoint(client):
    client.post("/batches", json={"name": "b3"})
    bid = client.get("/batches").json()[0]["id"]
    wid = client.post("/wafers", json={
        "batch_id": bid, "name": "w", "die_cols": 2, "die_rows": 2,
    }).json()["id"]
    client.post("/rule-versions", json={"rules": [
        {"param": "n", "lower": 0.5, "upper": 3.0}]})
    client.post("/chunks", json={"wafer_id": wid,
                                 "scans": [_scan_dict(x, y)
                                           for y in range(2) for x in range(2)]})
    jid = client.post(f"/wafers/{wid}/jobs").json()["id"]
    r = client.post(f"/jobs/{jid}/cancel")
    assert r.status_code == 200
    # 最终要么 cancelled 且无结果，要么已 done 且结果完整
    for _ in range(200):
        st = client.get(f"/jobs/{jid}").json()["state"]
        if st in ("cancelled", "done", "failed"):
            break
        time.sleep(0.02)
    cnt = len(client.get(f"/wafers/{wid}/map").json()["dies"])
    if st == "cancelled":
        assert cnt == 0
    else:
        assert st == "done" and cnt == 4


def test_rule_diff_endpoint(client):
    client.post("/batches", json={"name": "b4"})
    bid = client.get("/batches").json()[0]["id"]
    wid = client.post("/wafers", json={
        "batch_id": bid, "name": "w", "die_cols": 3, "die_rows": 1,
    }).json()["id"]
    v1 = client.post("/rule-versions", json={"rules": [
        {"param": "n", "lower": 0.9, "upper": 1.5}]}).json()["id"]
    scans = [_scan_dict(x, 0, n=(1.1 if x != 2 else 1.4)) for x in range(3)]
    client.post("/chunks", json={"wafer_id": wid, "scans": scans})
    jid = client.post(f"/wafers/{wid}/jobs").json()["id"]
    for _ in range(200):
        if client.get(f"/jobs/{jid}").json()["state"] == "done":
            break
        time.sleep(0.02)

    v2 = client.post("/rule-versions", json={"rules": [
        {"param": "n", "lower": 0.9, "upper": 1.2}]}).json()["id"]
    r = client.get(f"/wafers/{wid}/rule-diff/{v1}/{v2}")
    assert r.status_code == 200
    changed = r.json()["changed"]
    assert any(c["die_x"] == 2 and c["grade_to"] == "fail" for c in changed)
