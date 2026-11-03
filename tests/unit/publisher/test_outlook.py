from __future__ import annotations

import json
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from tests.fixtures.builders import Day, repeat
from tests.unit.publisher.helpers import COLD, MILD, NOW, START, FakeForecasts, fc, uniform
from wisselweer.core import Forecast, HourlyPoint, PrecipType
from wisselweer.publisher.national import NationalAdviceService, NationalConfig, national_profile
from wisselweer.publisher.outlook import build_outlook
from wisselweer.publisher.public_schema import PublicOutlookDay


def day_kw(**kw):
    base = {
        "date": "2026-11-10",
        "temp_min_c": 1.04,
        "temp_max_c": 8.0,
        "frost_night": False,
        "snow_possible": False,
        "kind": "concrete",
    }
    return base | kw


def test_schema_accepts_rounds_and_rejects():
    d = PublicOutlookDay.model_validate(day_kw())
    assert d.temp_min_c == 1.0
    PublicOutlookDay.model_validate(day_kw(temp_min_c=None, temp_max_c=None))
    with pytest.raises(ValidationError):
        PublicOutlookDay.model_validate(day_kw(kind="other"))
    with pytest.raises(ValidationError):
        PublicOutlookDay.model_validate(day_kw(extra=1))


def test_split_concrete_and_trend_without_fabricated_days():
    out = build_outlook(fc(MILD), NOW)  # 16 dagen data
    assert out is not None and len(out) == 14
    assert [d.kind for d in out] == ["concrete"] * 7 + ["trend"] * 7
    assert out[0].date == START


def test_only_days_covered_by_provider():
    out = build_outlook(fc(repeat(Day(2, 9), 9)), NOW)
    assert out is not None and len(out) == 9
    assert [d.kind for d in out].count("trend") == 2
    assert out[-1].date == START.replace(day=START.day + 8)


def test_no_coverage_gives_none():
    assert build_outlook(fc([]), NOW) is None


def test_frost_and_snow_detection():
    days = [
        Day(-3, 2),
        Day(2, 8),
        Day(-1, 3, 6.0, PrecipType.SNOW),
        Day(4, 9, 3.0, PrecipType.RAIN),
    ]
    out = build_outlook(fc(days), NOW)
    assert out is not None
    assert [d.frost_night for d in out] == [True, False, True, False]
    assert [d.snow_possible for d in out] == [False, False, True, False]
    assert out[0].temp_min_c is not None and out[0].temp_min_c <= -2.9
    assert out[0].temp_max_c is not None and out[0].temp_max_c <= 2.0


def test_service_adds_outlook_from_first_location_only():
    by = {"De Bilt": fc(COLD)}
    a = NationalAdviceService(FakeForecasts(by, default=fc(MILD)), NationalConfig()).compute(NOW)
    assert a.outlook is not None and all(d.frost_night for d in a.outlook)


def test_service_without_reference_forecast_has_no_outlook():
    a = NationalAdviceService(
        FakeForecasts({"De Bilt": None}, default=fc(MILD)), NationalConfig()
    ).compute(NOW)
    assert a.outlook is None


def test_outlook_contains_no_pii_fields():
    a = NationalAdviceService(uniform(COLD), NationalConfig()).compute(NOW)
    raw = json.loads(a.model_dump_json())
    assert set(raw["outlook"][0]) == {
        "date",
        "temp_min_c",
        "temp_max_c",
        "temp_drive_c",
        "frost_night",
        "snow_possible",
        "kind",
    }


def test_national_profile_slots():
    prof = national_profile()
    slots = {(s.weekday, s.start.hour, s.end.hour) for s in prof.slots}
    assert slots == (
        {(d, 7, 9) for d in range(5)} | {(d, 16, 19) for d in range(5)} | {(5, 10, 18), (6, 10, 18)}
    )


def _drive_mean(fc_: Forecast, day, windows: list[tuple[int, int]]) -> float:
    tz = ZoneInfo("Europe/Amsterdam")
    vals = [
        p.temperature_c
        for p in fc_.hourly
        if p.time.astimezone(tz).date() == day
        and any(lo <= p.time.astimezone(tz).hour < hi for lo, hi in windows)
    ]
    return sum(vals) / len(vals)


def test_temp_drive_c_weekday_and_weekend():
    f = fc(repeat(Day(0, 10), 16))
    out = build_outlook(f, NOW, national_profile())
    assert out is not None
    tue, sat = out[0], out[4]  # 2026-11-10 = dinsdag, 2026-11-14 = zaterdag
    assert tue.date.weekday() == 1 and sat.date.weekday() == 5
    assert tue.temp_drive_c == round(_drive_mean(f, tue.date, [(7, 9), (16, 19)]), 1)
    assert sat.temp_drive_c == round(_drive_mean(f, sat.date, [(10, 18)]), 1)
    assert tue.temp_drive_c != sat.temp_drive_c
    assert tue.temp_min_c is not None and tue.temp_max_c is not None
    assert tue.temp_min_c < tue.temp_drive_c < tue.temp_max_c


def test_temp_drive_c_none_without_profile():
    out = build_outlook(fc(MILD), NOW)
    assert out is not None and all(d.temp_drive_c is None for d in out)


def test_temp_drive_c_none_when_no_points_in_slot():
    f = fc(MILD)
    # Alleen nachtpunten (01, 03, 05 en 22 uur) op de eerste dag: geen punt in een slot.
    tz = ZoneInfo("Europe/Amsterdam")
    night = {1, 3, 5, 22}
    pts: list[HourlyPoint] = []
    for p in f.hourly:
        local = p.time.astimezone(tz)
        if local.date() == START and local.hour not in night:
            continue
        pts.append(p)
    sparse = f.model_copy(update={"hourly": pts})
    out = build_outlook(sparse, NOW, national_profile())
    assert out is not None
    assert out[0].temp_drive_c is None
    assert out[1].temp_drive_c is not None


def test_service_outlook_uses_national_profile():
    a = NationalAdviceService(uniform(MILD), NationalConfig()).compute(NOW)
    assert a.outlook is not None and all(d.temp_drive_c is not None for d in a.outlook)
