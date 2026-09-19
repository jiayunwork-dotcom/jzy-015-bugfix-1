"""波面高程还原。

统一相位约定：η(x,t) = (H/2) · cos(k·x − ω·t)。
整套服务（单点、网格、示范算例）都用这一条，符号不得各自改写。
"""

from __future__ import annotations

import math

from app.errors import WaveValidationError


def surface_elevation(
    wave_height: float,
    k: float,
    omega: float,
    x: float,
    t: float,
) -> float:
    """单点波面高程（米）。"""
    return 0.5 * wave_height * math.cos(k * x - omega * t)


def elevation_grid(
    wave_height: float,
    k: float,
    omega: float,
    positions: list[float] | None,
    times: list[float] | None,
) -> list[list[float]]:
    """按位置/时间网格还原波面，返回二维数组。

    维度约定：eta[i][j] 对应 times[i] × positions[j]，即
    行随时间、列随位置；空网格（任一维缺失或为空）返回 []。
    """
    positions = positions or []
    times = times or []

    for name, seq in (("positions", positions), ("times", times)):
        for v in seq:
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise WaveValidationError(
                    f"{name} 中的网格坐标必须为有限数值", field=name
                )

    if not positions or not times:
        return []

    amp = 0.5 * wave_height
    return [
        [amp * math.cos(k * x - omega * t) for x in positions]
        for t in times
    ]
