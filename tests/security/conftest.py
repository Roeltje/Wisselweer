from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.auth import ADMIN_PASSWORD, ADMIN_USER, make_admin, make_token
from wisselweer.api.app import create_app
from wisselweer.settings import Settings


@pytest.fixture
def app(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "data"))
    make_admin(app)
    return app


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def token(app) -> str:
    return make_token(app)


def csrf_from(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, html
    return m.group(1)


def login(client: TestClient, password: str = ADMIN_PASSWORD, next_: str = "/", **kw):
    page = client.get("/login")
    return client.post(
        "/login",
        data={
            "username": ADMIN_USER,
            "password": password,
            "csrf_token": csrf_from(page.text),
            "next": next_,
        },
        follow_redirects=False,
        **kw,
    )


@pytest.fixture
def session_client(client):
    r = login(client)
    assert r.status_code == 303
    return client


@pytest.fixture
def csrf(session_client) -> str:
    # Het sessietoken staat in de loginpagina niet meer (ingelogd ⇒ redirect); lees uit cookie-sessie.
    import base64
    import json

    raw = session_client.cookies.get("ww_session")
    payload = raw.split(".")[0]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["csrf"]
