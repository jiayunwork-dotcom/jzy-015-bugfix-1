"""色散求根（整套计算的地基）。

方程：ω² = g · k · tanh(kh)，其中 ω = 2π/T。

求法：先用 Eckart(1952) 显式近似给出高质量初值，再用带保护的
Newton（配合二分兜底）在钉死容差内求根。任何输入都先做有限性与正性检查，
迭代无法闭合时抛出 DispersionError，绝不返回未收敛的数。

注意：这里一律解完整色散方程。中等水深不允许偷换成深水闭式 k = ω²/g，
闭式只在 kinematics 里作为“深水/浅水极限估计”用于自检与比对。
"""

from __future__ import annotations

import math

from app.config import Settings, get_settings
from app.errors import DispersionError


def angular_frequency(period: float, settings: Settings | None = None) -> float:
    """角频率 ω = 2π / T。"""
    return 2.0 * math.pi / period


def _deep_wavenumber(omega: float, settings: Settings) -> float:
    """深水极限波数 k0 = ω²/g（只用于初值/自检，不替代完整求根）。"""
    return omega * omega / settings.gravity


def dispersion_residual(k: float, h: float, omega: float, settings: Settings) -> float:
    """F(k) = g k tanh(kh) - ω²，根即 F(k)=0。"""
    return settings.gravity * k * math.tanh(k * h) - omega * omega


def _eckart_initial(omega: float, h: float, settings: Settings) -> float:
    """Eckart 显式近似：对深水和浅水都是高质量初值。

        k ≈ (ω²/g) / sqrt(tanh( (ω²/g) · h ))

    深水极限 tanh→1 ⇒ k≈ω²/g；浅水极限 tanh(x)≈x ⇒ k≈ω/sqrt(gh)。
    """
    k0 = _deep_wavenumber(omega, settings)
    arg = k0 * h
    # arg 恒正；极小值时直接走深水侧近似避免无意义的舍入
    tanh_arg = math.tanh(arg) if arg > 1.0e-300 else arg
    return k0 / math.sqrt(tanh_arg)


def solve_wavenumber(
    water_depth: float,
    period: float,
    *,
    settings: Settings | None = None,
) -> float:
    """由完整色散方程迭代求波数 k（1/m）。

    对无法在容差/迭代上限内闭合的情况抛出 DispersionError。
    """
    s = settings or get_settings()

    # —— 输入防线（服务层还会再校验，这里保证模块自身健壮）——
    for name, value in (("water_depth", water_depth), ("period", period)):
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise DispersionError(f"{name} 必须为有限数值", field=name)
        if value <= 0.0:
            raise DispersionError(f"{name} 必须为正数", field=name)

    omega = angular_frequency(period, s)
    omega2 = omega * omega

    # 深水极限（kh 极大，tanh 饱和为 1）直接闭合
    k0 = omega2 / s.gravity
    if k0 * water_depth > 500.0:
        return k0

    # —— 找括号 [lo, hi]：F(lo)<0<F(hi)。F 关于 k 严格单调增，根唯一。——
    lo, hi = 0.0, max(k0, 1.0e-6)
    f_lo = -omega2
    f_hi = dispersion_residual(hi, water_depth, omega, s)
    while f_hi < 0.0:
        hi *= 2.0
        f_hi = dispersion_residual(hi, water_depth, omega, s)
        if not math.isfinite(f_hi) or hi > 1.0e12:
            # 理论上到不了这里（单调且趋于无穷），当作无法闭合处理
            raise DispersionError("色散方程无法确定有界根区间", field="water_depth")

    # —— 以 Eckart 近似为初值，落入括号内 ——
    k = min(max(_eckart_initial(omega, water_depth, s), lo), hi)

    tol = s.solver_tolerance
    for _ in range(s.solver_max_iterations):
        f = dispersion_residual(k, water_depth, omega, s)

        # 收敛：残差相对 ω² 足够小，且括号相对宽度足够小
        if abs(f) <= tol * omega2 and (hi - lo) <= tol * max(k, 1.0e-300):
            return k

        # Newton 步（必须是双曲正切 tanh，不是普通正切 tan）
        kh = k * water_depth
        t = math.tanh(kh)
        # 导数 d/dk [g k tanh(kh)] = g (tanh(kh) + kh·sech²(kh))
        sech2 = 1.0 - t * t
        dk = s.gravity * (t + kh * sech2)
        k_newton = k if dk <= 0.0 else k - f / dk

        # 保护：Newton 点落在括号内且确实缩窄括号才采用，否则二分
        if lo < k_newton < hi:
            k = k_newton
        else:
            k = 0.5 * (lo + hi)

        f_new = dispersion_residual(k, water_depth, omega, s)
        if f_new < 0.0:
            lo, f_lo = k, f_new
        else:
            hi, f_hi = k, f_new
        # 始终保持根在括号内
        k = 0.5 * (lo + hi) if not (lo < k < hi) else k

    raise DispersionError(
        f"色散方程在 {s.solver_max_iterations} 次迭代内未收敛到容差 {tol:g} 以内",
        field="period",
    )
