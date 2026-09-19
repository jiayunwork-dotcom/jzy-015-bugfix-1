"""配置回显、运行状态（监控采集）、服务信息。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.persistence import WaveRepository, get_sql_repository

router = APIRouter(tags=["meta"])


@router.get("/config")
def config_echo(settings: Settings = Depends(get_settings)) -> dict:
    """回显重力加速度、深浅水判据、线性适用上限与求根容差。"""
    return {
        "gravity": settings.gravity,
        "gravity_unit": "m/s^2",
        "deep_water_threshold": settings.deep_water_threshold,       # kh > π
        "shallow_water_threshold": settings.shallow_water_threshold,  # kh < π/10
        "linear_limit": settings.linear_limit,                        # H/h 上限
        "linear_limit_definition": "wave_height / water_depth",
        "solver_tolerance": settings.solver_tolerance,
        "solver_max_iterations": settings.solver_max_iterations,
    }


@router.get("/health")
def health(repo: WaveRepository = Depends(get_sql_repository)) -> dict:
    """供监控采集的运行状态端点。"""
    db_ok = repo.ping()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/")
def root() -> dict:
    return {
        "service": "coastal-wave-dispersion",
        "description": "线性重力波色散反演与运动学/波面还原",
        "endpoints": [
            "POST /solve",
            "POST /solve/batch",
            "GET  /demo",
            "GET  /history",
            "GET  /config",
            "GET  /health",
        ],
    }
