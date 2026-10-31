from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from tests.fixtures.builders import Day, repeat
from tests.unit.publisher.helpers import (
    COLD,
    LATE_COLD,
    MILD,
    NAMES,
    NOW,
    FakeForecasts,
    fc,
    uniform,
)
from wisselweer.publisher.national import NationalAdviceService, NationalConfig
from wisselweer.weather.base import ProviderUnavailable

SHIFTED_COLD = repeat(Day(9, 15), 2) + repeat(Day(-3, 2), 14)


def compute(svc, cfg=None, now=NOW):
    return NationalAdviceService(svc, cfg or NationalConfig()).compute(now)


def test_all_agree_with_common_date():
    a = compute(uniform(COLD))
    assert a.status == "CHANGE_RECOMMENDED"
    assert a.next_season == "winter" and a.heading == "Wanneer winterbanden?"
    assert a.recommended_date == date(2026, 11, 10) and a.recommended_period is None
    assert a.regional_variation is False
    assert [r.name for r in a.regions] == NAMES
    assert a.forecast_until == date(2026, 11, 25)
    assert a.source.name == "Testbron"


def test_majority_wins_and_flags_variation():
    by = {n: fc(MILD) for n in NAMES[:2]}  # 2 van 7 mild, 5 koud ⇒ 5/7 < 0.75
    by |= {n: fc(COLD) for n in NAMES[2:]}
    assert compute(FakeForecasts(by)).status == "REGIONAL_DIFFERENCES"
    by = {NAMES[0]: fc(MILD)} | {n: fc(COLD) for n in NAMES[1:]}  # 6/7 ≥ 0.75
    a = compute(FakeForecasts(by))
    assert a.status == "CHANGE_RECOMMENDED"
    assert a.regional_variation is True
    assert a.recommended_date == date(2026, 11, 10)  # alleen de eensgezinde regio's tellen


def test_split_gives_regional_differences_without_dates():
    by = {n: fc(MILD) for n in NAMES[:4]} | {n: fc(COLD) for n in NAMES[4:]}
    a = compute(FakeForecasts(by))
    assert a.status == "REGIONAL_DIFFERENCES"
    assert a.summary.startswith(
        "De omstandigheden verschillen per regio. Er is nog geen eenduidig landelijk wisselmoment."
    )
    assert a.recommended_date is None and a.recommended_period is None
    assert a.regional_variation is True


def test_too_few_regions_with_data():
    by = {n: fc(COLD) for n in NAMES[:3]} | {n: ProviderUnavailable("x") for n in NAMES[3:]}
    a = compute(FakeForecasts(by))
    assert a.status == "INSUFFICIENT_DATA"
    assert a.recommended_date is None and a.forecast_until is None
    assert sum(r.status == "INSUFFICIENT_DATA" for r in a.regions) == 4


def test_some_providers_fail_but_enough_data():
    by = {n: fc(COLD) for n in NAMES[:5]} | {n: ProviderUnavailable("x") for n in NAMES[5:]}
    a = compute(FakeForecasts(by))
    assert a.status == "CHANGE_RECOMMENDED"
    assert a.regional_variation is True
    assert {r.status for r in a.regions[5:]} == {"INSUFFICIENT_DATA"}


def test_unexpected_errors_are_contained():
    by = {NAMES[0]: RuntimeError("boom")}
    a = compute(FakeForecasts(by, default=fc(COLD)))
    assert a.status == "CHANGE_RECOMMENDED"


def test_different_dates_give_period():
    by = {n: fc(COLD) for n in NAMES[:3]} | {n: fc(SHIFTED_COLD) for n in NAMES[3:]}
    a = compute(FakeForecasts(by))
    assert a.status == "CHANGE_RECOMMENDED"
    assert a.recommended_date is None
    assert a.recommended_period is not None
    assert a.recommended_period.start == date(2026, 11, 10)
    assert a.recommended_period.end == date(2026, 11, 11)


def test_trend_only_gives_period():
    a = compute(uniform(LATE_COLD))
    assert a.status == "PREPARE_CHANGE"
    assert a.recommended_date is None and a.recommended_period is not None


def test_no_date_when_not_supported():
    a = compute(uniform(MILD))
    assert a.status == "KEEP_CURRENT"
    assert a.recommended_date is None and a.recommended_period is None


def test_forecast_until_is_minimum():
    by = {NAMES[0]: fc(COLD[:8])}
    a = compute(FakeForecasts(by, default=fc(COLD)))
    assert a.forecast_until == date(2026, 11, 17)


def test_warning_note_is_generic():
    a = compute(uniform(COLD))
    assert a.summary.endswith("Lokaal kan het glad zijn; let op waarschuwingen van het KNMI.")
    assert not any(ch.isdigit() for ch in a.summary)
    assert "KNMI" not in compute(uniform(MILD)).summary


@pytest.mark.parametrize(
    ("day", "season"),
    [
        (date(2026, 1, 31), "winter"),
        (date(2026, 2, 1), "summer"),
        (date(2026, 7, 31), "summer"),
        (date(2026, 8, 1), "winter"),
        (date(2026, 11, 10), "winter"),
    ],
)
def test_season_windows(day, season):
    assert NationalConfig().season_for(day) == season


def test_summer_direction_uses_winter_mounted():
    now = datetime(2026, 3, 20, 8, tzinfo=UTC)
    f = fc(repeat(Day(12, 20), 16), start=date(2026, 3, 20))
    f = f.model_copy(update={"fetched_at": now})
    a = compute(FakeForecasts({}, default=f), now=now)
    assert a.next_season == "summer" and a.heading == "Wanneer zomerbanden?"
    assert a.status in {"KEEP_CURRENT", "PREPARE_CHANGE", "CHANGE_RECOMMENDED"}


def test_season_boundary_uses_local_date():
    # 31 jan 23:30 UTC = 1 feb 00:30 lokaal ⇒ zomervraag.
    now = datetime(2027, 1, 31, 23, 30, tzinfo=UTC)
    a = compute(FakeForecasts({}, default=None), now=now)
    assert a.next_season == "summer"


def test_stale_after_and_utc_z():
    a = compute(uniform(COLD))
    assert a.generated_at == NOW and a.stale_after == NOW + timedelta(hours=18)
    data = a.model_dump(mode="json")
    assert data["generated_at"] == "2026-11-10T08:00:00Z"
    assert data["stale_after"] == "2026-11-11T02:00:00Z"
    cfg = NationalConfig(stale_hours=6)
    assert compute(uniform(COLD), cfg).stale_after == NOW + timedelta(hours=6)
