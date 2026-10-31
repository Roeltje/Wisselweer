import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from wisselweer.core.models import Forecast
from wisselweer.weather.base import (
    FetchResult,
    ProviderInfo,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderUnavailable,
)
from wisselweer.weather.cache import ForecastCache, InMemoryBackend
from wisselweer.weather.registry import ProvidersConfig, build_forecast_service
from wisselweer.weather.service import ForecastService

T0 = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


def fc(provider="p"):
    return Forecast(
        provider=provider, latitude=52.0, longitude=5.0, timezone="Europe/Amsterdam", fetched_at=T0
    )


class Fake:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, ims):
        self.calls.append(ims)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def mk(clock, **kw):
    return ForecastCache(InMemoryBackend(), clock=clock, **kw)


def test_fresh_uses_cache():
    clock, f = Clock(), Fake([FetchResult(forecast=fc(), expires=T0 + timedelta(hours=1))])
    c = mk(clock)
    c.get_or_fetch("k", f)
    clock.advance(minutes=30)
    out = c.get_or_fetch("k", f)
    assert len(f.calls) == 1 and not out.is_stale


def test_no_expires_uses_min_refresh():
    clock, f = Clock(), Fake([FetchResult(forecast=fc()), FetchResult(forecast=fc())])
    c = mk(clock, min_refresh_minutes=30)
    c.get_or_fetch("k", f)
    clock.advance(minutes=29)
    c.get_or_fetch("k", f)
    assert len(f.calls) == 1
    clock.advance(minutes=2)
    c.get_or_fetch("k", f)
    assert len(f.calls) == 2


def test_expired_refetches_with_ims_and_304():
    clock = Clock()
    f = Fake(
        [
            FetchResult(forecast=fc(), expires=T0 + timedelta(hours=1), last_modified="LM1"),
            FetchResult(forecast=None, not_modified=True, expires=T0 + timedelta(hours=3)),
        ]
    )
    c = mk(clock)
    c.get_or_fetch("k", f)
    clock.advance(hours=1, minutes=1)
    out = c.get_or_fetch("k", f)
    assert f.calls == [None, "LM1"]
    assert out.valid_until == T0 + timedelta(hours=3)
    clock.advance(hours=1)
    c.get_or_fetch("k", f)  # expires bijgewerkt: geen nieuwe fetch
    assert len(f.calls) == 2


def test_error_falls_back_stale_then_too_old():
    clock = Clock()
    f = Fake(
        [
            FetchResult(forecast=fc(), expires=T0 + timedelta(hours=1)),
            ProviderUnavailable("x"),
            ProviderUnavailable("x"),
        ]
    )
    c = mk(clock, max_stale_hours=24)
    c.get_or_fetch("k", f)
    clock.advance(hours=2)
    out = c.get_or_fetch("k", f)
    assert out.is_stale
    clock.advance(hours=23)  # 25 u na fetch
    with pytest.raises(ProviderUnavailable):
        c.get_or_fetch("k", f)


def test_error_without_cache_raises():
    with pytest.raises(ProviderUnavailable):
        mk(Clock()).get_or_fetch("k", Fake([ProviderUnavailable("x")]))


def test_retry_after_respected():
    clock = Clock()
    f = Fake(
        [
            FetchResult(forecast=fc(), expires=T0 + timedelta(minutes=10)),
            ProviderRateLimited(T0 + timedelta(hours=1)),
        ]
    )
    c = mk(clock)
    c.get_or_fetch("k", f)
    clock.advance(minutes=20)
    assert c.get_or_fetch("k", f).is_stale
    clock.advance(minutes=10)  # nog binnen retry_after: geen nieuwe fetch
    assert c.get_or_fetch("k", f).is_stale
    assert len(f.calls) == 2


def test_not_configured_propagates_even_with_cache():
    clock = Clock()
    f = Fake(
        [FetchResult(forecast=fc(), expires=T0 + timedelta(minutes=1)), ProviderNotConfigured("x")]
    )
    c = mk(clock)
    c.get_or_fetch("k", f)
    clock.advance(minutes=5)
    with pytest.raises(ProviderNotConfigured):
        c.get_or_fetch("k", f)


class SlowProvider:
    def __init__(self):
        self.calls = 0

    def info(self):
        return ProviderInfo(
            id="p",
            name="P",
            attribution="a",
            license_url="u",
            horizon_hours=1,
            commercial_use_ok=True,
        )

    def fetch(self, latitude, longitude, *, if_modified_since=None):
        self.calls += 1
        time.sleep(0.05)
        return FetchResult(forecast=fc(), expires=datetime.now(UTC) + timedelta(hours=1))


def test_two_cars_one_fetch():
    prov = SlowProvider()
    svc = ForecastService({"p": prov}, ForecastCache(InMemoryBackend()), "p")
    out = []
    ts = [
        threading.Thread(target=lambda: out.append(svc.get_forecast(52.12341, 5.0)))
        for _ in range(2)
    ]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert prov.calls == 1 and len(out) == 2
    svc.get_forecast(52.12339, 5.0)  # zelfde afgeronde sleutel
    assert prov.calls == 1


def test_service_infos_and_registry():
    svc = build_forecast_service(ProvidersConfig(commercial=True))
    infos = {i.id: i for i in svc.provider_infos()}
    assert set(infos) == {"metno", "openmeteo", "brightsky", "knmi_forecast"}
    assert not infos["metno"].configured and not infos["openmeteo"].configured
    with pytest.raises(ProviderNotConfigured):
        svc.get_forecast(52, 5)
    with pytest.raises(ProviderNotConfigured):
        svc.get_forecast(52, 5, "openmeteo")
