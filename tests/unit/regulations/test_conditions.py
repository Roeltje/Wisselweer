from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tests.fixtures.builders import Day, make_forecast, repeat
from wisselweer.core import EngineConfig, PrecipType
from wisselweer.core.engine import hour_flags
from wisselweer.regulations.conditions import CountryCondition, evaluate_country
from wisselweer.regulations.models import ReferenceLocation

NOW = datetime(2026, 12, 1, 8, 0, tzinfo=UTC)
START = date(2026, 12, 1)
A = ReferenceLocation(name="A", latitude=50.0, longitude=6.0)
B = ReferenceLocation(name="B", latitude=47.0, longitude=11.0, mountain=True)

MILD = repeat(Day(6, 12), 5)
FROST = repeat(Day(-3, 4), 5)
SNOW = repeat(Day(-4, 0, 6.0, PrecipType.SNOW), 5)
FREEZING = repeat(Day(-2, 0, 4.0, PrecipType.FREEZING_RAIN), 5)


def fc(days, **kw):
    return make_forecast(START, days, fetched_at=NOW, **kw)


def run(a, b):
    return evaluate_country([(A, a), (B, b)], NOW)


def test_none_expected():
    r = run(fc(MILD), fc(MILD))
    assert r.status == CountryCondition.NONE_EXPECTED and not r.partial
    assert r.window_hours == 72 and len(r.locations) == 2


def test_frost_only():
    r = run(fc(MILD), fc(FROST))
    assert r.status == CountryCondition.FROST_POSSIBLE
    assert [(f.name, f.frost, f.snow) for f in r.locations] == [
        ("A", False, False),
        ("B", True, False),
    ]


def test_snow():
    r = run(fc(MILD), fc(SNOW))
    assert r.status == CountryCondition.WINTER_CONDITIONS_EXPECTED
    assert r.locations[1].snow and r.locations[1].mountain


def test_icy():
    r = run(fc(FREEZING), fc(MILD))
    assert r.status == CountryCondition.WINTER_CONDITIONS_EXPECTED
    assert r.locations[0].icy


def test_unknown_without_any_data():
    r = run(None, None)
    assert r.status == CountryCondition.UNKNOWN and r.locations == []


def test_partial():
    r = run(None, fc(SNOW))
    assert r.status == CountryCondition.WINTER_CONDITIONS_EXPECTED
    assert r.partial and [f.name for f in r.locations] == ["B"]
    r2 = run(fc(MILD), None)
    assert r2.status == CountryCondition.NONE_EXPECTED and r2.partial


def test_only_next_72_hours_count():
    late = repeat(Day(6, 12), 4) + repeat(Day(-4, 0, 6.0, PrecipType.SNOW), 2)
    assert run(fc(late), fc(late)).status == CountryCondition.NONE_EXPECTED


def test_too_old_forecast_unusable():
    old = make_forecast(START, SNOW, fetched_at=NOW - timedelta(days=3))
    assert run(old, old).status == CountryCondition.UNKNOWN


def test_same_detection_as_engine():
    cfg = EngineConfig()
    assert any(hour_flags(p, cfg).snow for p in fc(SNOW).hourly)
