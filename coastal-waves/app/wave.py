"""海况计算编排：校验 → 色散求根 → 共用同一 k 导出全部运动学量 → 高程网格。

各物理步骤分别位于 dispersion / kinematics / elevation 模块，
这里只负责把它们串成一个确定性、无共享可变状态的纯计算结果。
"""

from __future__ import annotations

import math
from typing import Any

from app.config import Settings, get_settings
from app.dispersion import angular_frequency, solve_wavenumber
from app.elevation import elevation_grid, surface_elevation
from app.kinematics import (
    REGIME_LABELS,
    classify,
    deep_water_limits,
    group_velocity,
    phase_velocity,
    shallow_water_phase_speed,
    wavelength,
)
from app.validation import validate_grid, validate_sea_state


def compute_sea_state(
    payload: Any,
    *,
    settings: Settings | None = None,
) -> dict:
    """对一条已解析的 JSON 海况完成全部核算。任何不合法都抛出 app.errors.*。"""
    s = settings or get_settings()
    h, H, T = validate_sea_state(payload, s)
    positions, times = validate_grid(payload if isinstance(payload, dict) else {})

    # —— 地基：完整色散求出的唯一波数 ——
    k = solve_wavenumber(h, T, settings=s)
    omega = angular_frequency(T, s)
    kh = k * h

    # —— 以下全部共用这同一个 k，不再另解 ——
    L = wavelength(k)
    c = phase_velocity(omega, k)
    n = 1.0 + (2.0 * kh) / (
        math.sinh(2.0 * kh) if 2.0 * kh > 1.0e-12 else 2.0 * kh
    )
    cg = group_velocity(c, kh)
    regime = classify(kh, s)

    c0, L0 = deep_water_limits(T, s)
    cs = shallow_water_phase_speed(h, s)

    result: dict = {
        "input": {"water_depth": h, "wave_height": H, "period": T},
        "dispersion": {
            "angular_frequency": omega,
            "wavenumber": k,
            "kh": kh,
            "regime": regime,
            "regime_label": REGIME_LABELS[regime],
        },
        "kinematics": {
            "wavelength": L,
            "phase_velocity": c,
            "group_velocity": cg,
            "group_factor": n,
        },
        "limits": {
            "deep_water_phase_velocity": c0,
            "deep_water_wavelength": L0,
            "shallow_water_phase_velocity": cs,
        },
        "linear_applicability": {
            "height_to_depth_ratio": H / h,
            "limit": s.linear_limit,
            "valid": H / h <= s.linear_limit,
        },
        "phase_convention": "eta(x,t) = (H/2) * cos(k*x - omega*t)",
    }

    eta0 = surface_elevation(H, k, omega, 0.0, 0.0)
    result["surface_elevation"] = {"at_origin_t0": eta0}

    if positions is not None and times is not None:
        result["surface_elevation_grid"] = {
            "positions": positions,
            "times": times,
            "shape": [len(times), len(positions)],
            "eta": elevation_grid(H, k, omega, positions, times),
        }

    return result
