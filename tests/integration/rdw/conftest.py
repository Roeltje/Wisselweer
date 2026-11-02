from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.auth import bearer, make_admin
from wisselweer.api.app import create_app
from wisselweer.settings import Settings

RDW = "https://rdw.example.invalid"


def make_app(tmp_path, **overrides):
    values = {"rdw_url": RDW, **overrides}
    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "data", **values))
    make_admin(app)
    return app


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False, headers=bearer(app)) as c:
        yield c


@pytest.fixture
def anon(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
