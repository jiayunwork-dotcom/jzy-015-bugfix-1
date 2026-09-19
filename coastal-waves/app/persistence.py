"""持久化：每次核算（含输入与结果、成功或失败）落库，供事后条件检索。

生产用 PostgreSQL 16；同时给出同一接口的内存实现，供并发/接口测试零依赖运行。
所有仓储方法都是无共享请求级会话，线程安全。
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import Settings, get_settings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class WaveCalculation(Base):
    __tablename__ = "wave_calculations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_kind: Mapped[str] = mapped_column(String(16), default="single")
    batch_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)  # ok / error
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error_field: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    water_depth: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    wave_height: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    period: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    regime: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)

    wavenumber: Mapped[float | None] = mapped_column(Float, nullable=True)
    wavelength: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_velocity: Mapped[float | None] = mapped_column(Float, nullable=True)
    group_velocity: Mapped[float | None] = mapped_column(Float, nullable=True)

    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    __table_args__ = (
        Index("ix_wavecalc_kind_time", "request_kind", "created_at"),
    )


# 落库到历史接口时回显的字段（避免把整个网格无条件回吐）
EXPORT_KEYS = (
    "id", "request_kind", "batch_index", "status", "error_code", "error_field",
    "error_message", "water_depth", "wave_height", "period", "regime",
    "wavenumber", "wavelength", "phase_velocity", "group_velocity",
    "created_at", "result",
)


def build_entry(
    *,
    request_kind: str,
    batch_index: int | None,
    status: str,
    payload: Any,
    result: dict | None = None,
    error_code: str | None = None,
    error_field: str | None = None,
    error_message: str | None = None,
) -> dict:
    """把一次核算整理成统一的入库字典（成功/失败同形）。"""
    inp = result.get("input") if result else None
    disp = result.get("dispersion") if result else None
    kin = result.get("kinematics") if result else None

    def _num(name: str) -> float | None:
        if inp and isinstance(inp.get(name), (int, float)):
            return float(inp[name])
        if isinstance(payload, dict) and isinstance(payload.get(name), (int, float)):
            v = float(payload[name])
            return v if v == v and v not in (float("inf"), float("-inf")) else None
        return None

    return {
        "request_kind": request_kind,
        "batch_index": batch_index,
        "status": status,
        "error_code": error_code,
        "error_field": error_field,
        "error_message": error_message,
        "water_depth": _num("water_depth"),
        "wave_height": _num("wave_height"),
        "period": _num("period"),
        "regime": disp.get("regime") if disp else None,
        "wavenumber": disp.get("wavenumber") if disp else None,
        "wavelength": kin.get("wavelength") if kin else None,
        "phase_velocity": kin.get("phase_velocity") if kin else None,
        "group_velocity": kin.get("group_velocity") if kin else None,
        "result": result or {},
    }


def _entry_matches(
    e: dict,
    *,
    regime: str | None = None,
    status: str | None = None,
    min_period: float | None = None,
    max_period: float | None = None,
    min_water_depth: float | None = None,
    max_water_depth: float | None = None,
) -> bool:
    if regime and e.get("regime") != regime:
        return False
    if status and e.get("status") != status:
        return False
    if min_period is not None and (e.get("period") is None or e["period"] < min_period):
        return False
    if max_period is not None and (e.get("period") is None or e["period"] > max_period):
        return False
    if min_water_depth is not None and (e.get("water_depth") is None or e["water_depth"] < min_water_depth):
        return False
    if max_water_depth is not None and (e.get("water_depth") is None or e["water_depth"] > max_water_depth):
        return False
    return True


class WaveRepository(Protocol):
    def add(self, entry: dict) -> dict: ...
    def list(
        self, *, limit: int, offset: int, **filters: Any
    ) -> tuple[list[dict], int]: ...
    def ping(self) -> bool: ...


class InMemoryWaveRepository:
    """线程安全的内存仓储，供测试使用。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: list[dict] = []
        self._seq = 0

    def add(self, entry: dict) -> dict:
        with self._lock:
            self._seq += 1
            row = dict(entry)
            row["id"] = self._seq
            row.setdefault("created_at", _utcnow())
            self._rows.append(row)
            return dict(row)

    def list(self, *, limit: int, offset: int, **filters: Any) -> tuple[list[dict], int]:
        with self._lock:
            matched = [dict(r) for r in self._rows if _entry_matches(r, **filters)]
            total = len(matched)
            ordered = sorted(matched, key=lambda r: r["id"], reverse=True)
            return ordered[offset:offset + limit], total

    def ping(self) -> bool:
        return True


class SqlWaveRepository:
    """PostgreSQL 仓储（请求级 Session，线程之间不共享会话）。"""

    def __init__(self, session_factory: sessionmaker[Session]):
        self._factory = session_factory

    def add(self, entry: dict) -> dict:
        with self._factory() as session:
            row = WaveCalculation(**entry)
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._row_to_dict(row)

    def list(self, *, limit: int, offset: int, **filters: Any) -> tuple[list[dict], int]:
        with self._factory() as session:
            stmt = select(WaveCalculation)
            count_stmt = select(WaveCalculation)
            conditions = []
            if filters.get("regime"):
                conditions.append(WaveCalculation.regime == filters["regime"])
            if filters.get("status"):
                conditions.append(WaveCalculation.status == filters["status"])
            if filters.get("min_period") is not None:
                conditions.append(WaveCalculation.period >= filters["min_period"])
            if filters.get("max_period") is not None:
                conditions.append(WaveCalculation.period <= filters["max_period"])
            if filters.get("min_water_depth") is not None:
                conditions.append(WaveCalculation.water_depth >= filters["min_water_depth"])
            if filters.get("max_water_depth") is not None:
                conditions.append(WaveCalculation.water_depth <= filters["max_water_depth"])
            for c in conditions:
                stmt = stmt.where(c)
                count_stmt = count_stmt.where(c)

            total = len(session.scalars(count_stmt).all())
            rows = session.scalars(
                stmt.order_by(WaveCalculation.id.desc()).limit(limit).offset(offset)
            ).all()
            return [self._row_to_dict(r) for r in rows], total

    def ping(self) -> bool:
        try:
            with self._factory() as session:
                session.execute(select(1))
            return True
        except Exception:
            return False

    @staticmethod
    def _row_to_dict(row: WaveCalculation) -> dict:
        return {k: getattr(row, k) for k in EXPORT_KEYS if k != "id"} | {"id": row.id}


# ---- 引擎/仓储工厂 ----

_engine = None
_session_factory: sessionmaker[Session] | None = None


def init_database(settings: Settings | None = None, *, wait: bool = False) -> None:
    """建表。wait=True 时在 Compose 启动阶段等待 PostgreSQL 就绪。"""
    global _engine, _session_factory
    s = settings or get_settings()
    _engine = create_engine(s.database_url, pool_pre_ping=True, future=True)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)

    import time

    deadline = time.time() + 60.0
    while True:
        try:
            Base.metadata.create_all(_engine)
            return
        except Exception:
            if not wait or time.time() > deadline:
                raise
            time.sleep(1.0)


def get_sql_repository() -> SqlWaveRepository:
    if _session_factory is None:
        init_database(wait=True)
    assert _session_factory is not None
    return SqlWaveRepository(_session_factory)
