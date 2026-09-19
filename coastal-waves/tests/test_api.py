"""接口层：校验拒绝、波陡越限、单条求解、配置/健康/示范。"""

import math

import pytest


def test_config_echoes_pinned_constants(client):
    cfg = client.get("/config").json()
    assert cfg["gravity"] == 9.80665
    assert cfg["deep_water_threshold"] == math.pi
    assert cfg["shallow_water_threshold"] == pytest.approx(math.pi / 10)
    assert cfg["linear_limit"] == 0.5
    assert cfg["solver_tolerance"] == 1e-12


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "up"


def test_solve_single_returns_all_quantities(client):
    r = client.post("/solve", json={"water_depth": 10, "wave_height": 2, "period": 8})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    d, k = body["dispersion"], body["kinematics"]
    assert d["regime"] == "intermediate"
    assert k["wavelength"] > 0
    assert k["phase_velocity"] > 0
    assert 0 < k["group_velocity"] < k["phase_velocity"]
    assert "at_origin_t0" in body["surface_elevation"]
    assert body["surface_elevation"]["at_origin_t0"] == pytest.approx(1.0)


def test_solve_with_elevation_grid(client):
    r = client.post("/solve", json={
        "water_depth": 10, "wave_height": 2, "period": 8,
        "positions": [0.0, 10.0], "times": [0.0, 5.0],
    })
    grid = r.json()["surface_elevation_grid"]
    assert grid["shape"] == [2, 2]
    assert len(grid["eta"]) == 2 and len(grid["eta"][0]) == 2


def test_solve_nonsquare_grid_shape_matches_array(client):
    # 复现算例：3 个位置、2 个时刻 → 标称形状与真实数组都必须是 2 行 3 列
    positions, times = [0.0, 5.0, 10.0], [0.0, 1.0]
    r = client.post("/solve", json={
        "water_depth": 10, "wave_height": 2, "period": 8,
        "positions": positions, "times": times,
    })
    assert r.status_code == 200
    grid = r.json()["surface_elevation_grid"]

    assert grid["shape"] == [2, 3]
    assert len(grid["eta"]) == 2
    assert all(len(row) == 3 for row in grid["eta"])

    body = r.json()
    k = body["dispersion"]["wavenumber"]
    omega = body["dispersion"]["angular_frequency"]
    for i, t in enumerate(times):
        for j, x in enumerate(positions):
            assert grid["eta"][i][j] == pytest.approx(
                math.cos(k * x - omega * t)
            )


def test_solve_grid_empty_when_one_axis_missing(client):
    r = client.post("/solve", json={
        "water_depth": 10, "wave_height": 2, "period": 8,
        "positions": [0.0, 5.0, 10.0],
    })
    body = r.json()
    assert "surface_elevation_grid" not in body
    r = client.post("/solve", json={
        "water_depth": 10, "wave_height": 2, "period": 8,
        "positions": [], "times": [0.0, 1.0],
    })
    grid = r.json()["surface_elevation_grid"]
    assert grid["shape"] == [2, 0]
    assert grid["eta"] == []


def test_steepness_over_limit_rejected(client):
    r = client.post("/solve", json={"water_depth": 10, "wave_height": 6.0, "period": 8})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "LINEAR_LIMIT_EXCEEDED"
    assert err["field"] == "wave_height"


@pytest.mark.parametrize("payload", [
    {"wave_height": 1, "period": 8},            # 缺字段
    {"water_depth": "x", "wave_height": 1, "period": 8},   # 非数值
    {"water_depth": 10, "wave_height": 1, "period": 0},    # 非正
    {"water_depth": -1, "wave_height": 1, "period": 8},
    {"water_depth": 10, "wave_height": 0, "period": 8},
    "not-an-object",
])
def test_invalid_parameters_rejected(client, payload):
    r = client.post("/solve", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["code"] in {"INVALID_PARAMETER", "LINEAR_LIMIT_EXCEEDED"}


def test_non_finite_values_rejected(client):
    # NaN / Infinity：客户端按 JSON 字面量直送，服务端必须在入口拒绝而非 500
    for literal in ("NaN", "Infinity", "-Infinity"):
        r = client.post(
            "/solve",
            content=f'{{"water_depth": {literal}, "wave_height": 1, "period": 8}}',
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 422, literal
        assert r.json()["error"]["code"] == "INVALID_PARAMETER"


def test_non_finite_value_in_batch_is_reported_per_item(client):
    r = client.post(
        "/solve/batch",
        content=(
            '{"items": ['
            '{"water_depth": 10, "wave_height": 2, "period": 8}, '
            '{"water_depth": NaN, "wave_height": 1, "period": 8}'
            ']}'
        ),
        headers={"content-type": "application/json"},
    )
    body = r.json()
    assert body["success_count"] == 1
    assert body["error_count"] == 1
    assert body["results"][1]["error"]["field"] == "water_depth"


def test_demo_is_intermediate_full_dispersion(client):
    body = client.get("/demo").json()
    kh = body["dispersion"]["kh"]
    assert kh < math.pi and kh > math.pi / 10
    assert all(body["strict_checks"].values())
    c = body["kinematics"]["phase_velocity"]
    c0 = body["limits"]["deep_water_phase_velocity"]
    cs = body["limits"]["shallow_water_phase_velocity"]
    assert c < c0 and c < cs
