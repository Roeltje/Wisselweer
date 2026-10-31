from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.auth import ADMIN_PASSWORD, ADMIN_USER, make_admin
from tests.integration.api.conftest import FakeProvider
from wisselweer.api.app import create_app
from wisselweer.api.deps import ensure_db, get_forecast_service
from wisselweer.settings import Settings
from wisselweer.storage.cache_backend import SqliteCacheBackend
from wisselweer.weather.base import ProviderUnavailable
from wisselweer.weather.cache import ForecastCache
from wisselweer.weather.service import ForecastService


class FailingProvider(FakeProvider):
    def info(self):
        info = super().info()
        return info.model_copy(update={"id": "broken", "name": "Kapot"})

    def fetch(self, lat, lon, *, if_modified_since=None):
        self.calls += 1
        raise ProviderUnavailable("down")


class OtherProvider(FakeProvider):
    def info(self):
        info = super().info()
        return info.model_copy(update={"id": "other", "name": "Andere bron"})


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def other_provider() -> OtherProvider:
    return OtherProvider()


@pytest.fixture
def app(tmp_path, provider, other_provider):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "data"))
    make_admin(app)
    factory = ensure_db(app)
    service = ForecastService(
        {"fake": provider, "other": other_provider},
        ForecastCache(SqliteCacheBackend(factory)),
        "fake",
    )
    app.state.test_service = service
    app.dependency_overrides[get_forecast_service] = lambda: service
    return app


@pytest.fixture
def anon(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def csrf_from(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, html[:500]
    return m.group(1)


class Web:
    """Ingelogde testclient met CSRF-hulp."""

    def __init__(self, client: TestClient) -> None:
        self.c = client

    def get(self, url: str, **kw):
        return self.c.get(url, follow_redirects=False, **kw)

    def token(self) -> str:
        return csrf_from(self.c.get("/").text)

    def post(self, url: str, data: dict | None = None, **kw):
        body = {"csrf_token": self.token(), **(data or {})}
        return self.c.post(url, data=body, follow_redirects=False, **kw)

    def follow(self, url: str, data: dict | None = None):
        r = self.post(url, data)
        assert r.status_code == 303, r.text[:800]
        return self.c.get(r.headers["location"])


@pytest.fixture
def web(anon) -> Web:
    page = anon.get("/login")
    r = anon.post(
        "/login",
        data={
            "username": ADMIN_USER,
            "password": ADMIN_PASSWORD,
            "csrf_token": csrf_from(page.text),
            "next": "/",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    return Web(anon)


VEHICLE_FORM = {
    "name": "Testauto",
    "make": "Merk",
    "model": "Model",
    "license_plate": "XX-000-X",
    "build_year": "2019",
    "location_name": "Utrecht",
    "latitude": "52,0907",
    "longitude": "5.1214",
    "timezone": "Europe/Amsterdam",
}


def create_vehicle(web: Web, **overrides) -> int:
    r = web.post("/vehicles/new", {**VEHICLE_FORM, **overrides})
    assert r.status_code == 303, r.text[:1500]
    return int(r.headers["location"].rsplit("/", 1)[1])


def create_sets(web: Web, vid: int) -> None:
    r = web.post(
        f"/vehicles/{vid}/sets/new", {"type": "summer", "status": "mounted", "brand": "ZomerMerk"}
    )
    assert r.status_code == 303, r.text[:1500]
    r = web.post(
        f"/vehicles/{vid}/sets/new", {"type": "winter", "status": "stored", "brand": "WinterMerk"}
    )
    assert r.status_code == 303, r.text[:1500]
