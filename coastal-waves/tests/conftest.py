import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.persistence import InMemoryWaveRepository  # noqa: E402


@pytest.fixture
def settings():
    # auto_init_db=False：测试不触碰 PostgreSQL
    s = get_settings().model_copy(update={"auto_init_db": False})
    return s


@pytest.fixture
def repo():
    return InMemoryWaveRepository()


@pytest.fixture
def app(settings, repo):
    app = create_app(settings)
    app.dependency_overrides = {}
    from app.persistence import get_sql_repository

    app.dependency_overrides[get_sql_repository] = lambda: repo
    # 关闭配置缓存依赖覆盖（保持钉死的默认常数）
    yield app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
