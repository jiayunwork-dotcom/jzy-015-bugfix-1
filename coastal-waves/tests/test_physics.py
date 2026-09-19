"""色散与运动学物理判据（直接调模块，不经过 HTTP）。"""

import math

import pytest

from app.config import get_settings
from app.dispersion import angular_frequency, dispersion_residual, solve_wavenumber
from app.kinematics import (
    DEEP,
    INTERMEDIATE,
    SHALLOW,
    classify,
    deep_water_limits,
    group_velocity,
    phase_velocity,
    shallow_water_phase_speed,
    wavelength,
)

s = get_settings()
G = s.gravity
TOL = 1.0e-9


def test_deep_water_phase_velocity_equals_gT_over_2pi():
    h, T = 1000.0, 8.0
    k = solve_wavenumber(h, T, settings=s)
    omega = angular_frequency(T, s)
    c = phase_velocity(omega, k)
    c0, L0 = deep_water_limits(T, s)
    assert classify(k * h, s) == DEEP
    assert c == pytest.approx(G * T / (2 * math.pi), rel=TOL)
    assert c == pytest.approx(c0, rel=TOL)
    # 深水群速度 ≈ 相速度一半
    assert group_velocity(c, k * h) == pytest.approx(0.5 * c, rel=1e-9)
    # 波长 → gT²/2π
    assert wavelength(k) == pytest.approx(G * T * T / (2 * math.pi), rel=TOL)
    assert wavelength(k) == pytest.approx(L0, rel=TOL)


def test_shallow_water_phase_velocity_equals_sqrt_gh():
    h, H, T = 1.0, 0.01, 100.0
    k = solve_wavenumber(h, T, settings=s)
    omega = angular_frequency(T, s)
    c = phase_velocity(omega, k)
    assert classify(k * h, s) == SHALLOW
    # kh≈0.031，展开误差 O(kh)²≈1e-3，用宽一点的容差卡到浅水闭式
    assert c == pytest.approx(math.sqrt(G * h), rel=2e-3)
    # 浅水群速度 ≈ 相速度（因子 n→2）
    assert group_velocity(c, k * h) == pytest.approx(c, rel=2e-3)


def test_dispersion_residual_is_closed_for_intermediate():
    # 中等水深必须真正满足完整色散，残差在钉死容差内
    h, T = 10.0, 8.0
    k = solve_wavenumber(h, T, settings=s)
    omega = angular_frequency(T, s)
    kh = k * h
    assert s.shallow_water_threshold < kh < s.deep_water_threshold
    assert classify(kh, s) == INTERMEDIATE
    assert abs(dispersion_residual(k, h, omega, s)) <= s.solver_tolerance * omega ** 2


def test_intermediate_full_dispersion_and_strict_inequalities():
    """中等水深：走完整 tanh；精确相速度严格小于两个闭式极限（两者皆上界）。"""
    h, T = 10.0, 8.0
    k = solve_wavenumber(h, T, settings=s)
    omega = angular_frequency(T, s)
    c = phase_velocity(omega, k)
    c0, _ = deep_water_limits(T, s)
    cs = shallow_water_phase_speed(h, s)
    assert classify(k * h, s) == INTERMEDIATE
    assert c < c0
    assert c < cs
    # 且 c 严格大于“深水闭式若被错误套用到浅水”之外的平凡下界，数值范围合理
    assert 8.0 < c < 9.5


def test_period_doubling_deep_water_wavelength_x4_phase_x2():
    h = 2000.0
    k1 = solve_wavenumber(h, 6.0, settings=s)
    k2 = solve_wavenumber(h, 12.0, settings=s)
    omega1, omega2 = angular_frequency(6.0, s), angular_frequency(12.0, s)
    c1, c2 = phase_velocity(omega1, k1), phase_velocity(omega2, k2)
    L1, L2 = wavelength(k1), wavelength(k2)
    assert classify(k1 * h, s) == DEEP and classify(k2 * h, s) == DEEP
    assert c2 / c1 == pytest.approx(2.0, abs=1e-6)
    assert L2 / L1 == pytest.approx(4.0, abs=1e-5)


def test_deepening_past_deep_threshold_phase_velocity_saturates():
    # 已进入深水区后继续加深，相速度不再随水深上涨（k0h≥500 直接闭合，结果逐位相同）
    T = 8.0
    c_prev = None
    for h in (3000.0, 4000.0, 5000.0):
        k = solve_wavenumber(h, T, settings=s)
        c = phase_velocity(angular_frequency(T, s), k)
        assert classify(k * h, s) == DEEP
        if c_prev is not None:
            assert c == c_prev
        c_prev = c
    # 再验证刚进入深水区（h=200）与已饱和值的差异也已小到工程上可忽略
    k_shallow_side = solve_wavenumber(200.0, T, settings=s)
    c_edge = phase_velocity(angular_frequency(T, s), k_shallow_side)
    assert classify(k_shallow_side * 200.0, s) == DEEP
    assert abs(c_edge - c_prev) / c_prev < 1e-6


def test_shallow_water_depth_x4_phase_x2():
    T, H = 200.0, 0.005
    k1 = solve_wavenumber(1.0, T, settings=s)
    k2 = solve_wavenumber(4.0, T, settings=s)
    omega = angular_frequency(T, s)
    c1, c2 = phase_velocity(omega, k1), phase_velocity(omega, k2)
    assert classify(k1 * 1.0, s) == SHALLOW
    assert classify(k2 * 4.0, s) == SHALLOW
    assert c2 / c1 == pytest.approx(2.0, rel=2e-3)


def test_wave_height_doubling_changes_only_elevation():
    from app.elevation import surface_elevation

    h, T = 10.0, 8.0
    k1 = solve_wavenumber(h, T, settings=s)
    k2 = solve_wavenumber(h, T, settings=s)  # 与波高无关：同一 (h,T) 同 k
    omega = angular_frequency(T, s)
    assert k1 == k2
    c = phase_velocity(omega, k1)
    cg = group_velocity(c, k1 * h)
    for H in (1.0, 2.0):
        assert solve_wavenumber(h, T, settings=s) == k1
        assert phase_velocity(omega, solve_wavenumber(h, T, settings=s)) == c
        assert group_velocity(c, k1 * h) == cg
    # 只有高程随波高等比放大（同一 x,t）
    x, t = 3.0, 1.5
    eta1 = surface_elevation(1.0, k1, omega, x, t)
    eta2 = surface_elevation(2.0, k1, omega, x, t)
    assert eta2 == pytest.approx(2.0 * eta1, rel=1e-12)


def test_group_factor_uses_hyperbolic_sine_not_constant_half():
    # 中等水深处 n 必须严格介于 1 与 2 之间，证明带了 sinh 修正
    h, T = 10.0, 8.0
    k = solve_wavenumber(h, T, settings=s)
    kh = k * h
    c = phase_velocity(angular_frequency(T, s), k)
    cg = group_velocity(c, kh)
    n = 2 * cg / c
    assert 1.0 < n < 2.0
    assert cg > 0.5 * c  # 不是一律 c/2


def test_nonconverging_or_invalid_inputs_raise():
    from app.errors import DispersionError

    for bad in (0.0, -1.0, float("nan"), float("inf"), "8"):
        with pytest.raises(DispersionError):
            solve_wavenumber(10.0, bad, settings=s)
        with pytest.raises(DispersionError):
            solve_wavenumber(bad, 8.0, settings=s)
