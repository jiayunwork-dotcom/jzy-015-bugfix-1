"""历史检索：按分区/状态/周期区间/水深区间条件检索。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.kinematics import DEEP, INTERMEDIATE, SHALLOW
from app.persistence import WaveRepository, get_sql_repository

router = APIRouter(tags=["history"])

_REGIMES = {DEEP, SHALLOW, INTERMEDIATE}


@router.get("/history")
def list_history(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    regime: str | None = Query(None),
    status: str | None = Query(None, pattern="^(ok|error)$"),
    min_period: float | None = Query(None),
    max_period: float | None = Query(None),
    min_water_depth: float | None = Query(None),
    max_water_depth: float | None = Query(None),
    repo: WaveRepository = Depends(get_sql_repository),
    settings: Settings = Depends(get_settings),
) -> dict:
    if regime is not None and regime not in _REGIMES:
        return {
            "status": "error",
            "error": {"code": "INVALID_PARAMETER", "field": "regime",
                      "message": f"regime 必须是 {sorted(_REGIMES)} 之一"},
            "items": [],
            "total": 0,
        }

    filters = {
        "regime": regime,
        "status": status,
        "min_period": min_period,
        "max_period": max_period,
        "min_water_depth": min_water_depth,
        "max_water_depth": max_water_depth,
    }
    items, total = repo.list(limit=limit, offset=offset, **filters)
    return {"status": "ok", "total": total, "limit": limit, "offset": offset, "items": items}
