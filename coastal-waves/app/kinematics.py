"""运动学量：全部基于色散模块解出的同一个波数 k 导出。

禁止在本模块另解一套波数。相速度 c = ω/k；群速度

    cg = (c/2) · n,   n = 1 + 2kh / sinh(2kh)

深水 n→1（cg→c/2），浅水 n→2（cg→c）。双曲正弦修正绝不能丢。
"""

from __future__ import annotations

import math

from app.config import Settings

DEEP = "deep"
SHALLOW = "shallow"
INTERMEDIATE = "intermediate"

REGIME_LABELS = {
    DEEP: "深水",
    SHALLOW: "浅水",
    INTERMEDIATE: "中等水深",
}


def classify(kh: float, settings: Settings) -> str:
    """按相对水深 kh 分区：>π 深水，<π/10 浅水，其间中等水深。"""
    if kh > settings.deep_water_threshold:
        return DEEP
    if kh < settings.shallow_water_threshold:
        return SHALLOW
    return INTERMEDIATE


def wavelength(k: float) -> float:
    """波长 L = 2π/k。"""
    return 2.0 * math.pi / k


def phase_velocity(omega: float, k: float) -> float:
    """相速度 c = ω/k（与色散共用同一个 k）。"""
    return omega / k


def group_factor(kh: float) -> float:
    """n = 1 + 2kh / sinh(2kh)。

    深水 sinh(2kh)≫2kh ⇒ n→1；浅水 sinh(2kh)→2kh ⇒ n→2。
    小自变量时用 sinh(x)≈x，避免舍入损失。
    """
    x = 2.0 * kh
    ratio = x / math.sinh(x) if x > 1.0e-12 else 1.0
    return 1.0 + ratio


def group_velocity(c: float, kh: float) -> float:
    """群速度 cg = c/2 · (1 + 2kh/sinh(2kh))。"""
    return 0.5 * c * group_factor(kh)


def deep_water_limits(period: float, settings: Settings) -> tuple[float, float]:
    """深水闭式自检基准：c0 = gT/2π，L0 = gT²/2π。"""
    c0 = settings.gravity * period / (2.0 * math.pi)
    l0 = settings.gravity * period * period / (2.0 * math.pi)
    return c0, l0


def shallow_water_phase_speed(water_depth: float, settings: Settings) -> float:
    """浅水闭式自检基准：cs = √(gh)。"""
    return math.sqrt(settings.gravity * water_depth)
