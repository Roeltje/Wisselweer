"""Sneeuw of ijzel binnen de korte termijn (0-72 u) met zomerbanden ⇒ direct wisselen."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tests.fixtures.builders import Day, make_forecast, repeat
from tests.unit.core.helpers import AUTUMN_NOW, AUTUMN_START, run
from wisselweer.core import AdviceStatus, PrecipType, TireType, WarningCode
from wisselweer.core.models import Forecast

MILD = Day(8, 15)
S = AdviceStatus


def keys(a):
    return [r.key for r in a.reasons]


def with_hours(base: Forecast, hours: dict[datetime, dict]) -> Forecast:
    pts = []
    for p in base.hourly:
        if p.time in hours:
            p = p.model_copy(update=hours[p.time])
        pts.append(p)
    return base.model_copy(update={"hourly": pts})


def mild(start: date = AUTUMN_START, n: int = 14) -> Forecast:
    return make_forecast(start, repeat(MILD, n), fetched_at=AUTUMN_NOW - timedelta(hours=1))


def snow_hours(base: Forecast, first: datetime, n: int, **extra) -> Forecast:
    upd = {"precip_type": PrecipType.SNOW, "snow_cm": 0.5, "precip_mm": 0.5, **extra}
    return with_hours(base, {first + timedelta(hours=i): upd for i in range(n)})


T0 = datetime(2026, 11, 4, 10, tzinfo=UTC)  # ~2 dagen vooruit


def test_two_snow_hours_within_72h_recommends_change_today():
    a = run(None, fc=snow_hours(mild(), T0, 2))
    assert a.status == S.CHANGE_RECOMMENDED
    assert a.recommended_date == AUTUMN_START
    r = next(r for r in a.reasons if r.key == "reason.short_term_wintry")
    assert r.params == {"start": "2026-11-04", "kind": "snow"}
    snow = next(w for w in a.warnings if w.code == WarningCode.POSSIBLE_SNOW)
    assert snow.detail_key == "warning.snow.summer_tires"


def test_single_snow_hour_is_model_noise():
    a = run(None, fc=snow_hours(mild(), T0, 1))
    assert "reason.short_term_wintry" not in keys(a)
    assert a.status == S.KEEP_CURRENT


def test_snow_after_72h_does_not_trigger_rule():
    a = run(None, fc=snow_hours(mild(), AUTUMN_NOW + timedelta(hours=80), 3))
    assert "reason.short_term_wintry" not in keys(a)


def test_dewpoint_only_icy_is_just_a_warning():
    base = mild()
    fc = with_hours(
        base,
        {
            T0 + timedelta(hours=i): {
                "temperature_c": -2.0,
                "dew_point_c": -2.2,
                "humidity_pct": 95,
            }
            for i in range(5)
        },
    )
    a = run(None, fc=fc)
    assert WarningCode.POSSIBLE_ICY_CONDITIONS in {w.code for w in a.warnings}
    assert "reason.short_term_wintry" not in keys(a)
    assert a.status == S.KEEP_CURRENT


def test_freezing_rain_gives_kind_ice():
    fc = with_hours(
        mild(),
        {
            T0 + timedelta(hours=i): {
                "precip_type": PrecipType.FREEZING_RAIN,
                "precip_mm": 1.0,
                "temperature_c": -1.0,
            }
            for i in range(2)
        },
    )
    a = run(None, fc=fc)
    assert a.status == S.CHANGE_RECOMMENDED
    r = next(r for r in a.reasons if r.key == "reason.short_term_wintry")
    assert r.params["kind"] == "ice"


def test_snow_wins_over_ice_when_both():
    fc = with_hours(
        snow_hours(mild(), T0, 1),
        {
            T0 + timedelta(hours=1): {"precip_type": PrecipType.FREEZING_RAIN, "precip_mm": 1.0},
        },
    )
    a = run(None, fc=fc)
    r = next(r for r in a.reasons if r.key == "reason.short_term_wintry")
    assert r.params["kind"] == "snow"


def test_winter_tires_mounted_not_applicable():
    a = run(None, TireType.WINTER, fc=snow_hours(mild(), T0, 4))
    assert "reason.short_term_wintry" not in keys(a)


def test_applies_outside_winter_season():
    now = datetime(2026, 9, 15, 7, tzinfo=UTC)
    start = date(2026, 9, 15)
    base = make_forecast(start, repeat(MILD, 14), fetched_at=now - timedelta(hours=1))
    fc = snow_hours(base, datetime(2026, 9, 16, 10, tzinfo=UTC), 3)
    a = run(None, fc=fc, now=now, start=start)
    assert a.status == S.CHANGE_RECOMMENDED
    assert a.recommended_date == start
    assert "reason.winter_season_not_open" not in keys(a)


def test_min_hours_is_configurable():
    from wisselweer.core import EngineConfig

    a = run(None, fc=snow_hours(mild(), T0, 1), config=EngineConfig(short_term_wintry_min_hours=1))
    assert a.status == S.CHANGE_RECOMMENDED
