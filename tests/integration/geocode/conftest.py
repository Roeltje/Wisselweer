from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.auth import bearer, make_admin
from wisselweer import geocoding
from wisselweer.api.app import create_app
from wisselweer.settings import Settings

NOMINATIM = "https://nominatim.example.invalid"
CONTACT = "https://example.invalid/contact"


class FakeTime:
    """Nepklok: `sleep` laat de tijd vooruitlopen zonder echt te wachten."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_time(monkeypatch) -> FakeTime:
    ft = FakeTime()
    limiter = geocoding.RateLimiter(clock=ft.clock, sleep=ft.sleep)
    monkeypatch.setattr(geocoding, "UPSTREAM_LIMITER", limiter)
    # De cache van elke Geocoder gebruikt dezelfde nepklok.
    monkeypatch.setattr(geocoding, "_now", ft.clock)
    return ft


def make_app(tmp_path, **overrides):
    values = {"geocoder_url": NOMINATIM, "contact": CONTACT, **overrides}
    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "data", **values))
    make_admin(app)
    return app


@pytest.fixture
def app(tmp_path, fake_time):
    return make_app(tmp_path)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False, headers=bearer(app)) as c:
        yield c


@pytest.fixture
def anon(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
