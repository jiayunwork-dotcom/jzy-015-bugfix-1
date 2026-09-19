"""核心接口：解一条海况、批量解一组、示范算例。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.config import Settings, get_settings
from app.errors import WaveServiceError
from app.persistence import WaveRepository, build_entry, get_sql_repository
from app.validation import parse_json_body
from app.wave import compute_sea_state

router = APIRouter(tags=["waves"])

# 自带的中等水深涌浪示范算例：h=10 m，H=2 m，T=8 s
# kh≈0.887（明显小于 π=3.1416，明显大于 π/10=0.3142），走完整色散。
DEMO_SEA_STATE = {"water_depth": 10.0, "wave_height": 2.0, "period": 8.0}


def _record(repo: WaveRepository, entry: dict) -> dict:
    return repo.add(entry)


@router.post("/solve")
async def solve_one(
    request: Request,
    settings: Settings = Depends(get_settings),
    repo: WaveRepository = Depends(get_sql_repository),
) -> dict:
    """单条：返回色散解与全部导出量；非法或不闭合返回 422 并落库。"""
    payload = parse_json_body(await request.body(), reject_non_finite=True)
    try:
        result = compute_sea_state(payload, settings=settings)
    except WaveServiceError as exc:
        _record(
            repo,
            build_entry(
                request_kind="single",
                batch_index=None,
                status="error",
                payload=payload,
                error_code=exc.code,
                error_field=exc.field,
                error_message=exc.message,
            ),
        )
        raise

    row = _record(
        repo,
        build_entry(request_kind="single", batch_index=None, status="ok",
                    payload=payload, result=result),
    )
    return {"status": "ok", "history_id": row["id"], **result}


@router.post("/solve/batch")
async def solve_batch(
    request: Request,
    settings: Settings = Depends(get_settings),
    repo: WaveRepository = Depends(get_sql_repository),
) -> dict:
    """批量：逐条核算，某条非法只在该条上点明第几条/哪个参数，其余照常算完。"""
    payload = parse_json_body(await request.body())
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return {
            "status": "error",
            "error": {
                "code": "INVALID_BATCH",
                "message": "请求体必须是含 items 数组的对象",
                "field": "items",
            },
            "results": [],
            "success_count": 0,
            "error_count": 0,
        }

    items = payload["items"]
    positions = payload.get("positions")
    times = payload.get("times")

    results: list[dict] = []
    success_count = 0
    error_count = 0

    for idx, item in enumerate(items):
        raw = item
        if isinstance(item, dict) and positions is not None and "positions" not in item:
            item = {**item, "positions": positions}
        if isinstance(item, dict) and times is not None and "times" not in item:
            item = {**item, "times": times}

        try:
            result = compute_sea_state(item, settings=settings)
        except WaveServiceError as exc:
            error_count += 1
            row = _record(
                repo,
                build_entry(
                    request_kind="batch",
                    batch_index=idx,
                    status="error",
                    payload=raw,
                    error_code=exc.code,
                    error_field=exc.field,
                    error_message=exc.message,
                ),
            )
            results.append({
                "index": idx,
                "status": "error",
                "history_id": row["id"],
                "error": {
                    "code": exc.code,
                    "field": exc.field,
                    "message": exc.message,
                },
            })
            continue
        except Exception as exc:  # 防御：单条意外异常也不得拖垮整批
            error_count += 1
            row = _record(
                repo,
                build_entry(
                    request_kind="batch",
                    batch_index=idx,
                    status="error",
                    payload=raw,
                    error_code="INTERNAL_ERROR",
                    error_field=None,
                    error_message=str(exc),
                ),
            )
            results.append({
                "index": idx,
                "status": "error",
                "history_id": row["id"],
                "error": {"code": "INTERNAL_ERROR", "field": None, "message": str(exc)},
            })
            continue

        success_count += 1
        row = _record(
            repo,
            build_entry(request_kind="batch", batch_index=idx, status="ok",
                        payload=raw, result=result),
        )
        results.append({"index": idx, "status": "ok", "history_id": row["id"], **result})

    return {
        "status": "ok",
        "total": len(items),
        "success_count": success_count,
        "error_count": error_count,
        "results": results,
    }


@router.get("/demo")
def demo(settings: Settings = Depends(get_settings)) -> dict:
    """中等水深涌浪示范算例（只读，不落库）。"""
    result = compute_sea_state(DEMO_SEA_STATE, settings=settings)
    c0 = result["limits"]["deep_water_phase_velocity"]
    cs = result["limits"]["shallow_water_phase_velocity"]
    c = result["kinematics"]["phase_velocity"]
    return {
        "description": (
            "中等水深涌浪 h=10m, H=2m, T=8s。kh≈0.887，介于 π/10 与 π 之间，"
            "走完整色散 g·k·tanh(kh)=ω²。"
        ),
        "physics_note": (
            "由色散关系严格有 c = c0·sqrt(tanh(kh)/kh) < c0 且 c = sqrt(gh)·sqrt(tanh(kh)/kh) < sqrt(gh)："
            "同一 (h,T) 下精确相速度严格小于两个闭式极限中的任意一个，二者都是上界。"
        ),
        "strict_checks": {
            "c_less_than_deep_limit": c < c0,
            "c_less_than_shallow_limit": c < cs,
            "kh_below_pi": result["dispersion"]["kh"] < settings.deep_water_threshold,
            "kh_above_pi_over_10": result["dispersion"]["kh"] > settings.shallow_water_threshold,
        },
        **result,
    }
