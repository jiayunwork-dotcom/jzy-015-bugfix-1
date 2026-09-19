"""波面高程网格的维度摆放：第一维随时刻、第二维随位置。

非方形网格（位置数 ≠ 时刻数）是关键回归用例：方阵会把行列转置掩盖掉。
"""

import math

from app.config import get_settings
from app.dispersion import angular_frequency, solve_wavenumber
from app.elevation import elevation_grid

s = get_settings()


def _expected(H, k, omega, positions, times):
    amp = 0.5 * H
    return [
        [amp * math.cos(k * x - omega * t) for x in positions]
        for t in times
    ]


def test_nonsquare_grid_is_times_by_positions():
    # 复现算例：h=10, H=2, T=8，三个位置、两个时刻
    h, H, T = 10.0, 2.0, 8.0
    positions = [0.0, 5.0, 10.0]
    times = [0.0, 1.0]
    k = solve_wavenumber(h, T, settings=s)
    omega = angular_frequency(T, s)

    eta = elevation_grid(H, k, omega, positions, times)

    # 外层长度 = 时刻数，内层长度 = 位置数（2 行 3 列，不是 3 行 2 列）
    assert len(eta) == len(times) == 2
    assert all(len(row) == len(positions) == 3 for row in eta)
    assert eta == _expected(H, k, omega, positions, times)


def test_nonsquare_grid_reverse_aspect_ratio():
    # 两个位置、三个时刻：行列摆放同样不能互换
    h, H, T = 10.0, 2.0, 8.0
    positions = [2.0, 7.0]
    times = [0.0, 1.0, 3.0]
    k = solve_wavenumber(h, T, settings=s)
    omega = angular_frequency(T, s)

    eta = elevation_grid(H, k, omega, positions, times)

    assert len(eta) == 3
    assert all(len(row) == 2 for row in eta)
    assert eta == _expected(H, k, omega, positions, times)


def test_eta_element_ij_uses_time_i_and_position_j():
    positions = [0.0, 5.0, 10.0, 20.0]
    times = [0.0, 1.0]
    k = solve_wavenumber(10.0, 8.0, settings=s)
    omega = angular_frequency(8.0, s)

    eta = elevation_grid(2.0, k, omega, positions, times)

    # 逐元素：eta[i][j] 必须严格等于第 i 个时刻、第 j 个位置处的相位余弦。
    # 非对称网格下行列转置会让至少一个元素对不上（如 eta[1][3] 越界/错位）。
    for i, t in enumerate(times):
        for j, x in enumerate(positions):
            assert eta[i][j] == math.cos(k * x - omega * t)


def test_square_grid_layout_unchanged():
    positions = [0.0, 10.0]
    times = [0.0, 5.0]
    k = solve_wavenumber(10.0, 8.0, settings=s)
    omega = angular_frequency(8.0, s)

    eta = elevation_grid(2.0, k, omega, positions, times)

    assert len(eta) == 2 and all(len(row) == 2 for row in eta)
    assert eta == _expected(2.0, k, omega, positions, times)


def test_empty_grid_returns_empty_list():
    k = solve_wavenumber(10.0, 8.0, settings=s)
    omega = angular_frequency(8.0, s)
    assert elevation_grid(2.0, k, omega, [], [0.0, 1.0]) == []
    assert elevation_grid(2.0, k, omega, [0.0, 1.0], []) == []
    assert elevation_grid(2.0, k, omega, None, None) == []
