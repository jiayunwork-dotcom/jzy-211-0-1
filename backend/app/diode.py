"""带串联电阻的单指数二极管模型。

电流方程（正向）::

    I = Is * (exp((V - I*Rs) / (n*Vt)) - 1)

等价的隐式端电压方程::

    V = n*Vt * ln(1 + I/Is) + I*Rs

热电压 ``Vt = k_B * T / q``，300 K 时约 25.852 mV。
模块只负责物理模型；参数提取见 :mod:`app.extraction`。
"""
from __future__ import annotations

import numpy as np

K_B = 1.380649e-23  # 玻尔兹曼常数 J/K
Q_E = 1.602176634e-19  # 元电荷 C

TEMP_MIN = 200.0  # K
TEMP_MAX = 500.0  # K

_EXP_CLIP = 700.0


def thermal_voltage(temp_k: float) -> float:
    """测试温度下的热电压（V）。"""
    return K_B * float(temp_k) / Q_E


def diode_current(
    voltage: float | np.ndarray,
    is_: float,
    n: float,
    rs: float,
    temp_k: float,
) -> np.ndarray:
    """给定端电压 V，求带串联电阻二极管的电流。

    用对整条电压数组向量化的牛顿法解隐式方程
    ``f(I) = n*Vt*ln(1+I/Is) + I*Rs - V = 0``，
    初值取无串联电阻解，通常十次以内收敛到机器精度。
    """
    v = np.asarray(voltage, dtype=float)
    vt = thermal_voltage(temp_k)
    nv = max(n * vt, 1e-30)

    with np.errstate(over="ignore"):
        i = is_ * np.expm1(np.clip(v / nv, -_EXP_CLIP, _EXP_CLIP))
    i = np.where(v > 0.0, np.maximum(i, 0.0), np.minimum(i, 0.0))

    if rs <= 0.0:
        return i

    # 牛顿迭代：f(I) = nv*ln(1+I/Is) + I*rs - V
    for _ in range(30):
        i_pos = np.maximum(i, 0.0)
        f = nv * np.log1p(i_pos / is_) + i_pos * rs - v
        fp = nv / (is_ + i_pos) + rs
        step = f / fp
        i_new = np.maximum(i_pos - step, 0.0)
        if np.all(np.abs(step) <= 1e-13 * np.maximum(i_new, 1e-30)):
            i = i_new
            break
        i = i_new
    return i
