"""二极管模型与参数提取的单元测试（不需要数据库）。"""
from __future__ import annotations

import numpy as np
import pytest

from app.diode import diode_current, thermal_voltage
from app.extraction import (
    MIN_POINTS,
    ScanValidationError,
    extract_parameters,
    validate_scan,
)


def _synthetic(Is, n, Rs, vmax=1.0, T=300.0, seed=0,
               n_pts=60, log_noise=0.005, floor=2e-13):
    rng = np.random.default_rng(seed)
    v = np.linspace(0.05, vmax, n_pts)
    i = diode_current(v, Is, n, Rs, T)
    i = i * np.exp(rng.normal(0.0, log_noise, i.size))
    i = i + np.abs(rng.normal(0.0, floor, i.size))
    return v, i


# ---- 题目给的三个参考值 ----
def test_reference_thermal_voltage():
    assert thermal_voltage(300.0) == pytest.approx(0.025852, rel=1e-4)


def test_reference_current_n1():
    i = diode_current([0.6], 1e-14, 1.0, 0.0, 300.0)[0]
    assert i == pytest.approx(1.201e-4, rel=1e-3)


def test_reference_current_n2():
    i = diode_current([0.6], 1e-14, 2.0, 0.0, 300.0)[0]
    assert i == pytest.approx(1.096e-9, rel=1e-3)


# ---- 合成曲线参数还原（带噪声），容差：Is ±30%，n ±5%，Rs ±20% ----
@pytest.mark.parametrize("Is,n,Rs,vmax", [
    (1e-14, 1.0, 0.0, 0.72),
    (2e-13, 1.18, 3.5, 1.0),
    (5e-12, 1.8, 12.0, 1.0),
    (1e-11, 2.2, 47.0, 1.0),
])
def test_synthetic_recovery(Is, n, Rs, vmax):
    v, i = _synthetic(Is, n, Rs, vmax=vmax, seed=3)
    r = extract_parameters(v, i, 300.0)
    assert r.ok, r.reason
    assert r.is_ == pytest.approx(Is, rel=0.30)
    assert r.n == pytest.approx(n, abs=0.05)
    if Rs > 0:
        assert r.rs == pytest.approx(Rs, rel=0.20)
    else:
        assert r.rs <= 0.05
    assert r.residual is not None and r.residual < 0.10
    assert r.rs_reliable is True


# ---- 无噪声极限：三个参数精确还原 ----
@pytest.mark.parametrize("Is,n,Rs", [
    (1e-14, 1.0, 0.0), (2e-13, 1.18, 3.5),
    (5e-12, 1.8, 12.0), (1e-10, 2.5, 0.7),
])
def test_noiseless_exact(Is, n, Rs):
    v = np.linspace(0.05, 1.0 if Rs else 0.72, 80)
    i = diode_current(v, Is, n, Rs, 300.0)
    r = extract_parameters(v, i, 300.0, noise_floor=0.0)
    assert r.ok
    assert r.is_ == pytest.approx(Is, rel=1e-4)
    assert r.n == pytest.approx(n, abs=1e-3)
    assert r.rs == pytest.approx(Rs, abs=max(0.01, Rs * 1e-3))


# ---- 无串联电阻退化情形 ----
def test_zero_rs_degradation():
    v, i = _synthetic(1e-14, 1.0, 0.0, vmax=0.72, seed=1)
    r = extract_parameters(v, i, 300.0)
    assert r.ok
    assert r.rs == pytest.approx(0.0, abs=0.05)
    assert r.n == pytest.approx(1.0, abs=0.03)


# ---- 温度依赖：400 K 合成曲线 ----
def test_temperature_dependence():
    v, i = _synthetic(3e-13, 1.3, 6.0, vmax=1.0, T=400.0, seed=2)
    r = extract_parameters(v, i, 400.0)
    assert r.ok
    assert r.n == pytest.approx(1.3, abs=0.05)
    assert r.rs == pytest.approx(6.0, rel=0.25)


# ---- 提取失败判定：残差超阈值不给“好数字” ----
def test_extraction_failure_flagged():
    v = np.linspace(0.05, 1.0, 60)
    i = diode_current(v, 1e-14, 1.0, 0.0, 300.0)
    i[30:] *= np.exp(2.0)  # 后半段整体偏离单指数
    r = extract_parameters(v, i, 300.0)
    assert r.ok is False
    assert "残差" in r.reason
    assert r.residual is not None and r.residual > 0.10


# ---- 拒收：扫描点少于 5 个 ----
def test_reject_too_few_points():
    v = np.array([0.1, 0.2, 0.3, 0.4])
    i = np.array([1e-10, 2e-10, 4e-10, 8e-10])
    with pytest.raises(ScanValidationError, match="少于"):
        validate_scan(v, i, 300.0)
    r = extract_parameters(v, i, 300.0)
    assert r.ok is False and "少于" in r.reason


# ---- 拒收：电压不单调 ----
def test_reject_nonmonotonic_voltage():
    v = np.array([0.1, 0.3, 0.2, 0.4, 0.5])
    i = np.array([1e-10, 2e-10, 3e-10, 4e-10, 5e-10])
    r = extract_parameters(v, i, 300.0)
    assert r.ok is False and "单调" in r.reason


# ---- 拒收：负电流 / 非数值 ----
def test_reject_negative_current():
    v = np.linspace(0.1, 0.5, 6)
    r = extract_parameters(v, np.array([1e-9, 2e-9, -1e-9, 4e-9, 5e-9, 6e-9]), 300.0)
    assert r.ok is False and "电流" in r.reason


def test_reject_nan():
    v = np.linspace(0.1, 0.5, 6)
    i = np.array([1e-9, 2e-9, np.nan, 4e-9, 5e-9, 6e-9])
    r = extract_parameters(v, i, 300.0)
    assert r.ok is False and "非数值" in r.reason


# ---- 拒收：温度超出 200–500 K ----
@pytest.mark.parametrize("T", [199.9, 500.1, 100.0])
def test_reject_temperature(T):
    v = np.linspace(0.1, 0.5, 6)
    i = diode_current(v, 1e-12, 1.2, 0.0, max(min(T, 450.0), 250.0))
    r = extract_parameters(v, i, T)
    assert r.ok is False and "温度" in r.reason


# ---- Rs 不可辨识：扫描没进高电流区时必须显式标出来 ----
def test_rs_unidentifiable_flag():
    # Rs=50 Ω 但只扫到 0.5 V，I*Rs 远小于 Vt，Rs 不可辨识
    v, i = _synthetic(1e-12, 1.5, 50.0, vmax=0.5, seed=0, floor=0.0)
    r = extract_parameters(v, i, 300.0)
    assert r.rs_reliable is False
