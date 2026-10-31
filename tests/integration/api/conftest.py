from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.auth import bearer
from tests.fixtures.builders import Day, make_forecast, repeat
from wisselweer.api.app import create_app
from wisselweer.api.deps import ensure_db, get_forecast_service
from wisselweer.settings import Settings
from wisselweer.storage.cache_backend import SqliteCacheBackend
from wisselweer.weather.base import FetchResult, ProviderInfo
from wisselweer.weather.cache import ForecastCache
from wisselweer.weather.service import ForecastService

PLATE = "XX-000-X"
MAIL = "garage@example.invalid"


class FakeProvider:
    """Geen netwerk; telt het aantal fetches."""

    def __init__(self) -> None:
        self.calls = 0

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id="fake",
            name="Fake",
            attribution="Fake data",
            license_url="https://example.invalid/license",
            horizon_hours=240,
            commercial_use_ok=True,
        )

    def fetch(self, lat, lon, *, if_modified_since=None):
        self.calls += 1
        fc = make_forecast(
            date.today(),
            repeat(Day(-6, 0), 10),
            fetched_at=datetime.now(UTC),
            provider="fake",
        )
        return FetchResult(forecast=fc)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def app(tmp_path, provider):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "data"))
    factory = ensure_db(app)
    service = ForecastService(
        {"fake": provider}, ForecastCache(SqliteCacheBackend(factory)), "fake"
    )
    app.dependency_overrides[get_forecast_service] = lambda: service
    return app


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False, headers=bearer(app)) as c:
        yield c


def vehicle_body(name: str = "Testauto", plate: str | None = PLATE, **kw) -> dict:
    body = {
        "name": name,
        "license_plate": plate,
        "location": {"name": "Utrecht", "latitude": 52.0907, "longitude": 5.1214},
    }
    body.update(kw)
    return body
