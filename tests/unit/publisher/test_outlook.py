from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tests.fixtures.builders import Day, repeat
from tests.unit.publisher.helpers import COLD, MILD, NOW, START, FakeForecasts, fc, uniform
from wisselweer.core import PrecipType
from wisselweer.publisher.national import NationalAdviceService, NationalConfig
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
    days = [Day(-3, 2), Day(2, 8), Day(-1, 3, 6.0, PrecipType.SNOW), Day(4, 9, 3.0, PrecipType.RAIN)]
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
        "frost_night",
        "snow_possible",
        "kind",
    }
