from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.fixtures.builders import Day, make_forecast, repeat
from wisselweer.api.app import create_app
from wisselweer.api.deps import get_forecast_service
from wisselweer.settings import Settings
from wisselweer.weather.base import ProviderInfo, ProviderNotConfigured, ProviderUnavailable

SECRET = "super-geheim-key-123"


class FakeService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[float, float, str | None]] = []

    def get_forecast(self, latitude, longitude, provider_id=None):
        self.calls.append((latitude, longitude, provider_id))
        if self.error:
            raise self.error
        return make_forecast(date.today(), repeat(Day(tmin=12, tmax=20), 10), provider="metno")

    def provider_infos(self):
        return [
            ProviderInfo(
                id="metno",
                name="MET Norway",
                attribution="Data van MET Norway",
                license_url="https://example.invalid/license",
                variables={"temperature_c"},
                horizon_hours=240,
                commercial_use_ok=True,
            )
        ]


def make_client(service=None, **settings_kw):
    settings = Settings(_env_file=None, **settings_kw)
    app = create_app(settings)
    svc = service or FakeService()
    app.dependency_overrides[get_forecast_service] = lambda: svc
    return TestClient(app, raise_server_exceptions=False), svc


def test_health():
    c, _ = make_client()
    r = c.get("/api/v1/health")
    assert r.status_code == 200
    assert set(r.json()) == {"status", "version", "rules_version"}


def test_calculate_inline_forecast():
    c, svc = make_client()
    fc = make_forecast(date.today(), repeat(Day(tmin=12, tmax=20), 10), provider="metno")
    r = c.post(
        "/api/v1/advice/calculate",
        json={"forecast": fc.model_dump(mode="json"), "mounted": "summer"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["advice"]["direction"] == "to_winter"
    assert body["messages_nl"][f"heading.to_winter.{body['advice']['status']}"]
    assert body["source"]["attribution"] == "Data van MET Norway"
    assert svc.calls == []


def test_calculate_latlon_via_fake():
    c, svc = make_client()
    r = c.post(
        "/api/v1/advice/calculate",
        json={"latitude": 52.1, "longitude": 5.2, "provider": "metno", "mounted": "winter"},
    )
    assert r.status_code == 200, r.text
    assert svc.calls == [(52.1, 5.2, "metno")]
    assert r.json()["advice"]["direction"] == "to_summer"


def test_get_advice_and_default_location():
    c, svc = make_client(default_latitude=52.0, default_longitude=5.0)
    assert c.get("/api/v1/advice", params={"mounted": "summer"}).status_code == 200
    assert svc.calls == [(52.0, 5.0, None)]
    c2, _ = make_client()
    assert c2.get("/api/v1/advice", params={"mounted": "summer"}).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"mounted": "summer"},
        {"latitude": 52.0, "mounted": "summer"},
        {"latitude": 91, "longitude": 5, "mounted": "summer"},
        {"latitude": 52, "longitude": 181, "mounted": "summer"},
        {"latitude": 52, "longitude": 5, "mounted": "slicks"},
        {"latitude": 52, "longitude": 5, "mounted": "summer", "lead_time_days": -1},
    ],
)
def test_calculate_validation(body):
    c, _ = make_client()
    assert c.post("/api/v1/advice/calculate", json=body).status_code == 422


def test_get_advice_validation():
    c, _ = make_client()
    r = c.get("/api/v1/advice", params={"mounted": "summer", "latitude": 95, "longitude": 5})
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (ProviderNotConfigured(f"missing {SECRET}"), "provider_not_configured"),
        (ProviderUnavailable(f"down {SECRET}"), "provider_unavailable"),
    ],
)
def test_provider_errors_503(exc, code):
    c, _ = make_client(FakeService(error=exc))
    r = c.get("/api/v1/advice", params={"mounted": "summer", "latitude": 52, "longitude": 5})
    assert r.status_code == 503
    assert r.json() == {"detail": code}
    assert SECRET not in r.text


def test_unexpected_error_is_generic():
    c, _ = make_client(FakeService(error=RuntimeError(f"boom {SECRET}")))
    r = c.get("/api/v1/advice", params={"mounted": "summer", "latitude": 52, "longitude": 5})
    assert r.status_code == 500
    assert r.json() == {"detail": "internal_error"}
    assert SECRET not in r.text
    assert r.headers["X-Frame-Options"] == "DENY"


def test_docs_disabled():
    c, _ = make_client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404


def test_security_headers():
    c, _ = make_client()
    h = c.get("/api/v1/health").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "no-referrer"
    assert "default-src" in h["Content-Security-Policy"]


def test_defaults_and_secrets_not_leaked(monkeypatch):
    for k in ("HOST", "PORT"):
        monkeypatch.delenv(f"WISSELWEER_{k}", raising=False)
    assert Settings(_env_file=None).host == "127.0.0.1"
    s = Settings(
        _env_file=None,
        openmeteo_api_key=SecretStr(SECRET),
        knmi_api_key=SecretStr(SECRET),
        wu_api_key=SecretStr(SECRET),
        secret_key=SecretStr(SECRET),
    )
    assert SECRET not in repr(s)
    assert SECRET not in str(s)
    c, _ = make_client(openmeteo_api_key=SecretStr(SECRET), secret_key=SecretStr(SECRET))
    for path in ("/api/v1/providers", "/api/v1/health"):
        r = c.get(path)
        assert r.status_code == 200
        assert SECRET not in r.text
