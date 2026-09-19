"""波面网格维度约定：eta[i][j] 必须对应 times[i] × positions[j]。

非方形网格（位置数 ≠ 时刻数）是关键回归点：方阵会掩盖行列颠倒。
"""

import math

import pytest

from app.config import get_settings
from app.dispersion import angular_frequency, solve_wavenumber
from app.elevation import elevation_grid

s = get_settings()


def expected_eta(wave_height, k, omega, positions, times):
    amp = 0.5 * wave_height
    return [
        [amp * math.cos(k * x - omega * t) for x in positions]
        for t in times
    ]


@pytest.mark.parametrize("positions,times", [
    ([0.0, 5.0, 10.0], [0.0, 1.0]),       # 3 位置 × 2 时刻（复现用例）
    ([0.0, 5.0, 10.0, 20.0], [0.0, 1.0]),  # 4 位置 × 2 时刻
    ([0.0, 1.0], [0.0, 1.0, 2.0, 3.0]),    # 2 位置 × 4 时刻（另一方向的非方阵）
    ([7.0], [0.0, 1.0, 2.0]),             # 单列退化网格
    ([0.0, 1.0, 2.0], [3.0]),             # 单行退化网格
])
def test_non_square_grid_shape_is_n_times_by_n_positions(positions, times):
    h, H, T = 10.0, 2.0, 8.0
    k = solve_wavenumber(h, T, settings=s)
    omega = angular_frequency(T, s)

    eta = elevation_grid(H, k, omega, positions, times)

    # 外层长度 == 时刻数，每个内层长度 == 位置数
    assert len(eta) == len(times)
    assert all(len(row) == len(positions) for row in eta)

    # 逐元素：eta[i][j] == (H/2)·cos(k·positions[j] − ω·times[i])
    assert eta == pytest.approx(expected_eta(H, k, omega, positions, times), rel=1e-12)

    # 直接按下标约定抽查，确保不是“恰好形状对、值摆错”
    for i, t in enumerate(times):
        for j, x in enumerate(positions):
            assert eta[i][j] == pytest.approx(
                0.5 * H * math.cos(k * x - omega * t), rel=1e-12
            )


def test_square_grid_behavior_unchanged():
    h, H, T = 10.0, 2.0, 8.0
    k = solve_wavenumber(h, T, settings=s)
    omega = angular_frequency(T, s)
    positions, times = [0.0, 10.0], [0.0, 5.0]

    eta = elevation_grid(H, k, omega, positions, times)

    assert len(eta) == 2 and all(len(row) == 2 for row in eta)
    assert eta == pytest.approx(expected_eta(H, k, omega, positions, times), rel=1e-12)


@pytest.mark.parametrize("positions,times", [
    ([], []),
    ([0.0], []),
    ([], [0.0]),
])
def test_empty_grid_returns_empty_list(positions, times):
    k = solve_wavenumber(10.0, 8.0, settings=s)
    omega = angular_frequency(8.0, s)
    assert elevation_grid(2.0, k, omega, positions, times) == []
