"""应用配置。所有配置均可通过环境变量覆盖。"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str | None = os.environ.get("DATABASE_URL")
    db_pool_min: int = int(os.environ.get("DB_POOL_MIN", "1"))
    db_pool_max: int = int(os.environ.get("DB_POOL_MAX", "8"))
    # 残差（对数电流 RMSE，单位 decade）超过该阈值判为提取失败
    fit_residual_threshold: float = float(
        os.environ.get("FIT_RESIDUAL_THRESHOLD", "0.10")
    )
    # 电流底噪：小于该值的点视为漏电/仪器底噪，不参与拟合（A）
    noise_floor: float = float(os.environ.get("NOISE_FLOOR", "1e-12"))
    # 作业进度落库的最小时间间隔（秒）
    progress_interval: float = float(os.environ.get("PROGRESS_INTERVAL", "0.2"))


settings = Settings()
