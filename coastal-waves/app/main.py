"""FastAPI 应用装配与全局错误处理。

仓储依赖可被测试覆盖（app.dependency_overrides），因此并发请求各自经过
无共享的纯函数 compute_sea_state 与请求级仓储写入，互不串扰。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.errors import WaveServiceError
from app.persistence import get_sql_repository
from app.routes import history, meta, solve

logger = logging.getLogger("coastal_waves")
logging.basicConfig(level=logging.INFO)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    app = FastAPI(
        title="海岸线性重力波服务",
        version="1.0.0",
        description="色散反演、运动学量与波面高程还原（无账户体系、不做潮汐/日志/订舱）",
    )

    @app.exception_handler(WaveServiceError)
    async def _wave_error_handler(_: Request, exc: WaveServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "error": {
                    "code": exc.code,
                    "field": exc.field,
                    "message": exc.message,
                },
            },
        )

    app.include_router(meta.router)
    app.include_router(solve.router)
    app.include_router(history.router)

    @app.on_event("startup")
    def _startup() -> None:
        if s.auto_init_db:
            from app.persistence import init_database

            init_database(s, wait=True)
            logger.info("database initialized")

    return app


app = create_app()
