"""批量部分失败、历史落库、并发互不串扰。"""

import threading

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.dispersion import angular_frequency, solve_wavenumber


def test_batch_partial_failure_others_still_computed(client):
    items = [
        {"water_depth": 10, "wave_height": 2, "period": 8},          # 0 ok 中等
        {"water_depth": 10, "wave_height": 6, "period": 8},          # 1 波陡越限
        {"water_depth": -5, "wave_height": 1, "period": 8},          # 2 水深非正
        {"wave_height": 1, "period": 8},                             # 3 缺字段
        {"water_depth": 1000, "wave_height": 1, "period": 8},        # 4 ok 深水
        {"water_depth": 10, "wave_height": 2, "period": "x"},        # 5 非数值
    ]
    r = client.post("/solve/batch", json={"items": items})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 6
    assert body["success_count"] == 2
    assert body["error_count"] == 4

    by_index = {row["index"]: row for row in body["results"]}
    assert by_index[0]["status"] == "ok"
    assert by_index[4]["status"] == "ok"
    for bad, field in [(1, "wave_height"), (2, "water_depth"), (3, "water_depth"), (5, "period")]:
        row = by_index[bad]
        assert row["status"] == "error"
        assert row["error"]["field"] == field
        assert row["index"] == bad


def test_batch_malformed_body_does_not_crash(client):
    r = client.post("/solve/batch", json={"nope": []})
    assert r.status_code == 200
    assert r.json()["status"] == "error"
    assert r.json()["error"]["code"] == "INVALID_BATCH"


def test_batch_shared_grid_applies_to_each_item(client):
    items = [
        {"water_depth": 10, "wave_height": 2, "period": 8},
        {"water_depth": 1000, "wave_height": 1, "period": 8},
    ]
    r = client.post("/solve/batch", json={
        "items": items, "positions": [0.0, 5.0], "times": [0.0],
    })
    body = r.json()
    assert body["success_count"] == 2
    for row in body["results"]:
        assert row["surface_elevation_grid"]["shape"] == [1, 2]


def test_batch_non_square_grid_matches_declared_shape_and_values(client):
    """批量共享 3 位置 × 2 时刻网格：每行结果都必须 2 行 3 列、逐元素对位。"""
    import math

    positions, times = [0.0, 5.0, 10.0], [0.0, 1.0]
    r = client.post("/solve/batch", json={
        "items": [
            {"water_depth": 10, "wave_height": 2, "period": 8},
            {"water_depth": 1000, "wave_height": 1, "period": 8},
        ],
        "positions": positions,
        "times": times,
    })
    body = r.json()
    assert body["success_count"] == 2
    for row in body["results"]:
        grid = row["surface_elevation_grid"]
        assert grid["shape"] == [2, 3]
        eta = grid["eta"]
        assert len(eta) == 2 and all(len(r0) == 3 for r0 in eta)

        H = row["input"]["wave_height"]
        k = row["dispersion"]["wavenumber"]
        omega = row["dispersion"]["angular_frequency"]
        for i, t in enumerate(times):
            for j, x in enumerate(positions):
                assert eta[i][j] == pytest.approx(
                    0.5 * H * math.cos(k * x - omega * t), rel=1e-12
                )


def test_history_persists_success_and_error_and_filters(client):
    client.post("/solve", json={"water_depth": 10, "wave_height": 2, "period": 8})
    client.post("/solve", json={"water_depth": 1000, "wave_height": 1, "period": 8})
    client.post("/solve", json={"water_depth": 10, "wave_height": 9, "period": 8})  # error

    all_rows = client.get("/history").json()
    assert all_rows["total"] == 3

    ok_rows = client.get("/history", params={"status": "ok"}).json()
    assert ok_rows["total"] == 2

    err_rows = client.get("/history", params={"status": "error"}).json()
    assert err_rows["total"] == 1
    assert err_rows["items"][0]["error_code"] == "LINEAR_LIMIT_EXCEEDED"

    deep_rows = client.get("/history", params={"regime": "deep"}).json()
    assert deep_rows["total"] == 1

    period_rows = client.get("/history", params={"min_period": 8, "max_period": 8}).json()
    assert period_rows["total"] == 3


def test_history_stores_input_and_result(client):
    client.post("/solve", json={"water_depth": 10, "wave_height": 2, "period": 8})
    row = client.get("/history", params={"limit": 1}).json()["items"][0]
    assert row["water_depth"] == 10
    assert row["wave_height"] == 2
    assert row["period"] == 8
    assert row["regime"] == "intermediate"
    assert row["wavenumber"] > 0
    assert row["phase_velocity"] > 0
    assert row["result"]["dispersion"]["wavenumber"] == row["wavenumber"]


def test_concurrent_requests_do_not_cross_contaminate(app):
    """并发多请求：结果各自正确、历史各记各的，不串扰。

    每个工作线程使用独立的 TestClient（各自 portal），才能真正并发打到
    共享的内存仓储；工况按 (h,T) 唯一，事后按 (h,T) 联合核对计数。
    """
    cases = [
        (10.0, 2.0, 8.0),
        (1000.0, 1.0, 12.0),
        (2.0, 0.1, 30.0),
        (50.0, 5.0, 11.0),
        (1.0, 0.2, 50.0),
    ]
    repeats = 6
    errors: list[Exception] = []

    def worker(h, H, T):
        local = TestClient(app)
        try:
            for _ in range(repeats):
                r = local.post("/solve", json={
                    "water_depth": h, "wave_height": H, "period": T,
                })
                assert r.status_code == 200
                body = r.json()
                assert body["input"] == {"water_depth": h, "wave_height": H, "period": T}
                k_expected = solve_wavenumber(h, T, settings=get_settings())
                assert body["dispersion"]["wavenumber"] == pytest.approx(k_expected, rel=1e-12)
                assert body["kinematics"]["phase_velocity"] == pytest.approx(
                    angular_frequency(T, get_settings()) / k_expected, rel=1e-12
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=c) for c in cases]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors

    check = TestClient(app)
    hist = check.get("/history").json()
    assert hist["total"] == len(cases) * repeats
    # 每个 (h,T) 恰好 repeats 条，且输入没有写串到别的工况上
    for h, H, T in cases:
        rows = check.get("/history", params={
            "min_period": T, "max_period": T,
            "min_water_depth": h, "max_water_depth": h,
        }).json()
        assert rows["total"] == repeats, (h, T)
        for row in rows["items"]:
            assert row["wave_height"] == H
