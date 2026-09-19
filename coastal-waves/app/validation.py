"""输入校验：类型、有限性、正性、线性适用上限。

顺序固定：先三要素正性，再线性上限（H/h）。批量场景按“第几条 + 哪个字段”报错。
"""

from __future__ import annotations

import json
import math

from app.config import Settings
from app.errors import LinearLimitExceededError, WaveValidationError

FIELDS = ("water_depth", "wave_height", "period")
FIELD_LABELS = {
    "water_depth": "水深",
    "wave_height": "波高",
    "period": "周期",
}


def parse_json_body(raw: bytes, *, reject_non_finite: bool = False) -> object:
    """解析原始请求体。

    reject_non_finite=True（单条接口）时在最外层拒绝 NaN/Infinity，
    避免非有限数值流入任何后续环节；批量接口保持宽容，由逐条校验按第几条报出。
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise WaveValidationError("请求体不是合法 JSON 对象", field="body") from exc
    if reject_non_finite:
        _reject_non_finite(data)
    return data


def _reject_non_finite(obj: object) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise WaveValidationError("请求中不允许 NaN/Infinity 等非有限数值", field="body")
    elif isinstance(obj, dict):
        for v in obj.values():
            _reject_non_finite(v)
    elif isinstance(obj, list):
        for v in obj:
            _reject_non_finite(v)


def _finite_positive(name: str, value: object) -> float:
    if value is None:
        raise WaveValidationError(f"缺少字段 {name}", field=name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WaveValidationError(f"{FIELD_LABELS[name]}必须为数值", field=name)
    v = float(value)
    if not math.isfinite(v):
        raise WaveValidationError(f"{FIELD_LABELS[name]}必须为有限数值", field=name)
    if v <= 0.0:
        raise WaveValidationError(f"{FIELD_LABELS[name]}必须为正数", field=name)
    return v


def validate_sea_state(
    payload: object,
    settings: Settings,
) -> tuple[float, float, float]:
    """校验一条海况，返回 (water_depth, wave_height, period)。

    payload 不是对象时按整体非法处理。
    """
    if not isinstance(payload, dict):
        raise WaveValidationError("每条海况必须是对象", field="item")

    h = _finite_positive("water_depth", payload.get("water_depth"))
    H = _finite_positive("wave_height", payload.get("wave_height"))
    T = _finite_positive("period", payload.get("period"))

    steepness = H / h
    if steepness > settings.linear_limit:
        raise LinearLimitExceededError(
            f"波高/水深 = {steepness:.6g} 超过线性适用上限 {settings.linear_limit:g}",
            field="wave_height",
        )

    return h, H, T


def validate_grid(payload: dict) -> tuple[list[float] | None, list[float] | None]:
    """校验可选的 positions/times 网格。"""
    def _seq(name: str) -> list[float] | None:
        if name not in payload or payload[name] is None:
            return None
        raw = payload[name]
        if not isinstance(raw, list):
            raise WaveValidationError(f"{name} 必须是数组", field=name)
        out: list[float] = []
        for v in raw:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                raise WaveValidationError(f"{name} 中的网格坐标必须为有限数值", field=name)
            out.append(float(v))
        return out

    positions = _seq("positions")
    times = _seq("times")
    # 只给一维没有意义，按空网格处理（不报错）
    if positions is None or times is None:
        return positions, times
    return positions, times
