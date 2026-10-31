from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from tests.fixtures.builders import Day, make_forecast, repeat
from tests.integration.conftest import vehicle_in
from wisselweer.core import AdviceStatus, EngineConfig
from wisselweer.garages import service as gsvc
from wisselweer.garages.schemas import GarageIn
from wisselweer.storage.db import session_scope
from wisselweer.storage.enums import ChangeMethod, TireStatus
from wisselweer.storage.orm import AdviceSnapshot, ForecastSnapshot
from wisselweer.tires import service as tsvc
from wisselweer.tires.schemas import TireSetIn
from wisselweer.vehicles import service as vsvc
from wisselweer.vehicles.advice import VehicleAdviceService
from wisselweer.weather.base import FetchResult, ProviderInfo, ProviderUnavailable
from wisselweer.weather.cache import ForecastCache, InMemoryBackend
from wisselweer.weather.service import ForecastService

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)


class FakeProvider:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def info(self):
        return ProviderInfo(
            id="fake",
            name="Fake",
            attribution="-",
            license_url="https://example.invalid",
            horizon_hours=240,
            commercial_use_ok=True,
        )

    def fetch(self, lat, lon, *, if_modified_since=None):
        self.calls += 1
        if self.fail:
            raise ProviderUnavailable("down")
        fc = make_forecast(
            date(2026, 11, 20), repeat(Day(-6, 0), 10), fetched_at=NOW, provider="fake"
        )
        return FetchResult(forecast=fc)


def _service(factory, provider):
    fs = ForecastService({"fake": provider}, ForecastCache(InMemoryBackend()), "fake")
    return VehicleAdviceService(factory, fs, EngineConfig())


def _vehicle_with_summer(factory, name="A", **kw):
    with session_scope(factory) as s:
        v = vsvc.create_vehicle(s, vehicle_in(name=name, **kw))
        tsvc.create_tire_set(s, v.id, TireSetIn(type="summer", status=TireStatus.MOUNTED))
        return v.id


def test_two_vehicles_one_fetch(factory):
    a = _vehicle_with_summer(factory, "A", plate="XX-000-X")
    b = _vehicle_with_summer(factory, "B", plate=None)
    p = FakeProvider()
    svc = _service(factory, p)
    adv_a = svc.advice_for_vehicle(a, NOW)
    svc.advice_for_vehicle(b, NOW)
    assert p.calls == 1
    assert adv_a.status != AdviceStatus.INSUFFICIENT_DATA
    with session_scope(factory) as s:
        assert s.scalar(select(func.count()).select_from(AdviceSnapshot)) == 2
        assert s.scalar(select(func.count()).select_from(ForecastSnapshot)) == 1


def test_provider_failure_gives_insufficient_data(factory):
    a = _vehicle_with_summer(factory)
    adv = _service(factory, FakeProvider(fail=True)).advice_for_vehicle(a, NOW)
    assert adv.status == AdviceStatus.INSUFFICIENT_DATA
    with session_scope(factory) as s:
        snap = s.scalar(select(AdviceSnapshot))
        assert snap.forecast_snapshot_id is None


def test_previous_snapshot_used_and_reset_after_change(factory):
    a = _vehicle_with_summer(factory)
    svc = _service(factory, FakeProvider())
    svc.advice_for_vehicle(a, NOW)
    svc.advice_for_vehicle(a, NOW + timedelta(hours=1))
    with session_scope(factory) as s:
        w = tsvc.create_tire_set(s, a, TireSetIn(type="winter"))
        tsvc.register_tire_change(s, a, w.id, date(2026, 11, 20), today=date(2026, 11, 20))
        snaps = s.scalars(select(AdviceSnapshot)).all()
        assert len(snaps) == 2 and all(x.invalidated_at is not None for x in snaps)
    adv = svc.advice_for_vehicle(a, NOW + timedelta(hours=2))
    assert adv.confirm_streak == 0


def test_garage_lead_time_used(factory):
    seen = []
    import wisselweer.vehicles.advice as mod

    real = mod.evaluate

    def spy(inp):
        seen.append(inp.lead_time_days)
        return real(inp)

    mod.evaluate = spy
    try:
        with session_scope(factory) as s:
            g = gsvc.create_garage(s, GarageIn(name="G", lead_time_days=21))
        garage_v = _vehicle_with_summer(
            factory,
            "G",
            plate=None,
            change_method=ChangeMethod.GARAGE,
            preferred_garage_id=g.id,
            prep_days=3,
        )
        self_v = _vehicle_with_summer(
            factory, "S", plate=None, prep_days=3, preferred_garage_id=g.id
        )
        svc = _service(factory, FakeProvider())
        svc.advice_for_vehicle(garage_v, NOW)
        svc.advice_for_vehicle(self_v, NOW)
    finally:
        mod.evaluate = real
    assert seen == [21, 3]
