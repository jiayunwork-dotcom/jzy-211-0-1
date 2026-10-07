"""二极管参数提取：饱和电流 Is、理想因子 n、串联电阻 Rs。

方法（“先按区段粗估，再整体精修”）
----------------------------------
1. 数据有效性校验（点数、单调性、负电流/非数值、温度），不合法直接拒收。
2. 剔除低于仪器底噪 ``noise_floor`` 的点——低电流段受漏电和底噪主导，
   不反映理想结的指数规律；剔除后可用点太少（< 5）或电流跨距不足
   （< 3 个 decade）判失败。
3. 粗估：低电流段（取剔除底噪后的前 35% 点）对 ``ln I ~ V`` 做最小二乘，
   斜率给 1/(n*Vt)、截距给 Is；高电流段（后 40% 点）电压相对理想指数
   的“压降” ΔV ≈ I*Rs，线性拟合斜率给 Rs 的初值（强制非负）。
4. 精修：以全部有效点的 ``log10 I`` 残差做有界非线性最小二乘
   （SciPy ``least_squares``，TRF，解析雅可比），参数化为
   ``log(Is)、log(n)、log(Rs+eps)`` 保证为正。

拟合质量用 **log10(I) 的 RMSE（单位 decade）** 衡量，超过阈值
（默认 0.10 decade，约 26% 相对偏差）标记为提取失败，只给数字没有意义。

Rs 什么时候会错（重要限制）
---------------------------
* **扫描没进入串联电阻主导区**：最高点的 I*Rs 与热电压同量级或更小，
  Rs 在数据中不可辨识，拟合会把噪声/模型失配折进 Rs，可能返回一个
  虚高的值。此时结果里 ``rs_reliable=False``。
* **漏电/并联电导**：低电流段若存在显著并联漏电（本模型没有 Gp 项），
  会被部分吸收进 Rs 与 n。底噪剔除能压掉一部分，但漏电一直延续到
  中电流区时 Rs 仍会偏大。
* **高电流段的大注入/自热**：物理上偏离单指数模型，同样会被误算成 Rs。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from .config import settings
from .diode import TEMP_MAX, TEMP_MIN, diode_current, thermal_voltage

MIN_POINTS = 5
MIN_FIT_POINTS = 5
MIN_CURRENT_DECADES = 3.0
EPS_RS = 1e-9  # log 参数化下 Rs 的软零值（Ω）


class ScanValidationError(ValueError):
    """单条扫描数据不合法（拒收原因在消息中说明）。"""


@dataclass
class ExtractionResult:
    ok: bool
    is_: float | None = None
    n: float | None = None
    rs: float | None = None
    temp_k: float | None = None
    residual: float | None = None  # log10(I) RMSE，单位 decade
    rs_reliable: bool = False
    n_points: int = 0
    n_used: int = 0
    reason: str | None = None  # 失败/拒收原因
    used_mask: list[bool] = field(default_factory=list)  # 每个点是否参与拟合

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "is": self.is_,
            "n": self.n,
            "rs": self.rs,
            "temp_k": self.temp_k,
            "residual": self.residual,
            "rs_reliable": self.rs_reliable,
            "n_points": self.n_points,
            "n_used": self.n_used,
            "reason": self.reason,
            "used_mask": self.used_mask,
        }


def validate_scan(voltage: np.ndarray, current: np.ndarray, temp_k: float) -> None:
    """校验一条扫描，不合法抛 :class:`ScanValidationError`。"""
    v = np.asarray(voltage, dtype=float)
    i = np.asarray(current, dtype=float)

    if v.ndim != 1 or i.ndim != 1 or v.size != i.size:
        raise ScanValidationError("电压与电流数组长度不一致或不是一维序列")
    if v.size < MIN_POINTS:
        raise ScanValidationError(f"扫描点少于 {MIN_POINTS} 个（实际 {v.size} 个）")
    if not (np.all(np.isfinite(v)) and np.all(np.isfinite(i))):
        raise ScanValidationError("电压或电流出现非数值（NaN/Inf）")
    if np.any(i < 0.0) or np.any(i == 0.0):
        raise ScanValidationError("出现负电流或零电流（对数域无法处理）")
    if np.any(np.diff(v) <= 0.0):
        raise ScanValidationError("电压不是严格单调递增")
    if not (TEMP_MIN <= float(temp_k) <= TEMP_MAX):
        raise ScanValidationError(
            f"测试温度 {temp_k:g} K 不在 {TEMP_MIN:g}–{TEMP_MAX:g} K 之间"
        )


def _initial_guess(
    v: np.ndarray, i: np.ndarray, vt: float
) -> tuple[float, float, float]:
    """低电流段估 n、Is；高电流段压降估 Rs。"""
    n_pts = v.size
    log_i = np.log(i)

    k_lo = max(3, int(round(n_pts * 0.35)))
    sl, ic = np.polyfit(v[:k_lo], log_i[:k_lo], 1)
    n0 = float(np.clip(1.0 / (sl * vt), 0.5, 5.0))
    is0 = float(np.exp(np.clip(ic, -80.0, 0.0)))

    # 高电流段：理想指数电流 I_exp = Is*exp(V/(n*Vt))，ΔV = V - n*Vt*ln(I/Is) ≈ I*Rs
    k_hi = max(3, int(round(n_pts * 0.40)))
    vh, ih = v[-k_hi:], i[-k_hi:]
    dv = vh - n0 * vt * np.log(ih / is0)
    rs_slope = np.polyfit(ih, dv, 1)[0]
    rs0 = float(max(rs_slope, 0.0))
    return is0, n0, rs0


def extract_parameters(
    voltage: np.ndarray | list[float],
    current: np.ndarray | list[float],
    temp_k: float,
    *,
    noise_floor: float | None = None,
    residual_threshold: float | None = None,
) -> ExtractionResult:
    """从一条正向 I–V 扫描提取 (Is, n, Rs)。

    数据不合法返回 ``ok=False`` 且 ``reason`` 说明拒收原因；
    合法但拟合质量不达标同样 ``ok=False``（提取失败）。
    """
    if noise_floor is None:
        noise_floor = settings.noise_floor
    if residual_threshold is None:
        residual_threshold = settings.fit_residual_threshold

    v = np.asarray(voltage, dtype=float)
    i = np.asarray(current, dtype=float)

    try:
        validate_scan(v, i, temp_k)
    except ScanValidationError as exc:
        return ExtractionResult(
            ok=False, temp_k=float(temp_k), n_points=int(v.size), reason=str(exc)
        )

    n_points = int(v.size)
    used = i >= noise_floor
    vu, iu = v[used], i[used]

    if vu.size < MIN_FIT_POINTS:
        return ExtractionResult(
            ok=False,
            temp_k=float(temp_k),
            n_points=n_points,
            used_mask=used.tolist(),
            reason=(
                f"剔除底噪（< {noise_floor:g} A）后仅剩 {vu.size} 个点，"
                f"少于 {MIN_FIT_POINTS} 个"
            ),
        )
    decades = np.log10(iu.max() / iu.min())
    if decades < MIN_CURRENT_DECADES:
        return ExtractionResult(
            ok=False,
            temp_k=float(temp_k),
            n_points=n_points,
            used_mask=used.tolist(),
            reason=f"有效电流跨距仅 {decades:.1f} 个 decade，不足 {MIN_CURRENT_DECADES}",
        )

    vt = thermal_voltage(temp_k)
    is0, n0, rs0 = _initial_guess(vu, iu, vt)

    # 参数 x = (ln Is, ln n, asinh(Rs)/(2) 形式不必，用 ln(Rs+EPS))
    x0 = np.array([np.log(max(is0, 1e-30)), np.log(n0), np.log(rs0 + EPS_RS)])

    def unpack(x: np.ndarray) -> tuple[float, float, float]:
        return float(np.exp(x[0])), float(np.exp(x[1])), float(np.exp(x[2]) - EPS_RS)

    def residuals(x: np.ndarray) -> np.ndarray:
        is_, n, rs = unpack(x)
        ihat = diode_current(vu, is_, n, max(rs, 0.0), temp_k)
        return np.log10(np.maximum(ihat, 1e-300)) - np.log10(iu)

    def jacobian(x: np.ndarray) -> np.ndarray:
        # 隐式方程 v = nv*ln(1+I/Is) + I*Rs；解析雅可比见模块文档
        is_, n, rs = unpack(x)
        nv = n * vt
        ihat = np.maximum(diode_current(vu, is_, n, max(rs, 0.0), temp_k), 1e-300)
        denom = nv / (is_ + ihat) + max(rs, 0.0)
        # 隐式方程 f=0：∂I/∂p = -(∂f/∂p)/(∂f/∂I)，∂f/∂I = nv/(Is+I)+Rs
        d_i_d_lnis = (nv * ihat / (is_ + ihat)) / denom
        d_i_d_lnn = (-vt * np.log1p(ihat / is_) * n) / denom
        # ∂f/∂Rs = I（故有负号）；∂Rs/∂lnRs = Rs + EPS
        d_i_d_lrs = (-ihat * (rs + EPS_RS)) / denom
        inv_ln10 = 1.0 / np.log(10.0)
        return (
            np.column_stack([d_i_d_lnis, d_i_d_lnn, d_i_d_lrs])
            * inv_ln10
            / ihat[:, None]
        )

    lower = np.array([np.log(1e-20), np.log(0.5), np.log(EPS_RS)])
    upper = np.array([np.log(1e-1), np.log(8.0), np.log(1e6 + EPS_RS)])
    try:
        sol = least_squares(
            residuals,
            x0,
            jac=jacobian,
            bounds=(lower, upper),
            method="trf",
            xtol=1e-12,
            ftol=1e-12,
            max_nfev=200,
        )
    except Exception as exc:  # 数值失败
        return ExtractionResult(
            ok=False,
            temp_k=float(temp_k),
            n_points=n_points,
            used_mask=used.tolist(),
            reason=f"非线性拟合未收敛：{exc}",
        )

    res = sol.optimality  # noqa: F841（保留便于排查）
    is_f, n_f, rs_f = unpack(sol.x)
    rs_f = max(rs_f, 0.0)
    rmse = float(np.sqrt(np.mean(sol.fun**2)))

    if not np.all(np.isfinite(sol.x)) or not np.isfinite(rmse):
        return ExtractionResult(
            ok=False,
            temp_k=float(temp_k),
            n_points=n_points,
            used_mask=used.tolist(),
            reason="拟合结果含非数值",
        )

    # Rs 可辨识性判据：数据在最高点对 Rs 的“杠杆” I_max*n*Vt（Ω·V 量级）。
    # 若最高点的欧姆压降即便取 1 Ω 也远小于一个热电压，说明扫描根本没进入
    # 串联电阻可观测的高电流区，Rs 由数据不可辨识（真值为 0 与真值很大
    # 在该数据上无法区分）。
    rs_leverage = float(iu.max() * n_f * vt)  # V per Ω
    # 1e-5 V/Ω：最高点每 1 Ω 串联电阻产生 10 µV 压降。低于此时
    # 高电流区的 I*Rs << Vt，Rs 在数据中不可辨识——真值为 0 与真值很大
    # 会给出几乎相同的拟合，返回的 Rs（常贴到 0 下界）不可信。
    # 真值为 0 的扫描电流随电压一路上升，杠杆天然很大，无需特殊处理。
    rs_reliable = rs_leverage >= 1e-5

    if rmse > residual_threshold:
        return ExtractionResult(
            ok=False,
            is_=is_f,
            n=n_f,
            rs=rs_f,
            temp_k=float(temp_k),
            residual=rmse,
            rs_reliable=rs_reliable,
            n_points=n_points,
            n_used=int(vu.size),
            used_mask=used.tolist(),
            reason=f"拟合残差 {rmse:.3f} decade 超过阈值 {residual_threshold:.3f}",
        )

    return ExtractionResult(
        ok=True,
        is_=is_f,
        n=n_f,
        rs=rs_f,
        temp_k=float(temp_k),
        residual=rmse,
        rs_reliable=rs_reliable,
        n_points=n_points,
        n_used=int(vu.size),
        used_mask=used.tolist(),
    )
