from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from tests.unit.core.helpers import AUTUMN_NOW, AUTUMN_START, Day, repeat, run
from wisselweer.core import (
    AdviceStatus,
    Direction,
    DriveSlot,
    DrivingProfile,
    PrecipType,
    TireType,
    WarningCode,
)

MILD = Day(8, 15)
COLD = Day(1, 6)  # daggemiddelde 3,5 / rijmoment ~4,3 < 5
S = AdviceStatus


def codes(a):
    return {w.code for w in a.warnings}


def keys(items):
    return [r.key for r in items]


def test_mild_autumn_keeps_summer():
    a = run(repeat(MILD, 14))
    assert a.direction == Direction.TO_WINTER
    assert a.status == S.KEEP_CURRENT
    assert a.recommended_date is None and a.recommended_period is None
    assert a.plan_appointment_by is None
    assert not codes(a)
    assert "reason.no_sustained_cold" in keys(a.reasons)
    assert a.heading == "heading.to_winter.keep_current"


def test_stable_cold_autumn_recommends_day_before_streak():
    a = run([MILD, MILD, *repeat(COLD, 12)])
    assert a.status == S.CHANGE_RECOMMENDED
    assert a.recommended_date == AUTUMN_START + timedelta(days=1)  # dag vóór start (dag 3)
    assert a.recommended_period is None
    assert a.plan_appointment_by == a.recommended_date - timedelta(
        days=7
    ) or a.plan_appointment_by == date(2026, 11, 2)
    assert "reason.cold_streak" in keys(a.reasons)


def test_recommended_date_never_in_past():
    a = run(repeat(COLD, 14))  # reeks begint vandaag
    assert a.status == S.CHANGE_RECOMMENDED
    assert a.recommended_date == AUTUMN_START


def test_single_cold_night_is_only_a_warning():
    days = [MILD, MILD, Day(-2, 10), *repeat(MILD, 11)]
    a = run(days)
    assert a.status == S.KEEP_CURRENT
    assert WarningCode.POSSIBLE_FROST in codes(a)
    assert a.recommended_date is None


def test_persistent_frost_counts_heavily():
    # dagen 2-4 met vorst; daggemiddelde ver onder drempel
    days = [MILD, *repeat(Day(-3, 2), 3), *repeat(MILD, 10)]
    a = run(days)
    assert a.status == S.CHANGE_RECOMMENDED
    assert a.recommended_date == AUTUMN_START  # dag vóór dag 2 = vandaag
    assert "reason.persistent_frost" in keys(a.reasons)
    assert WarningCode.POSSIBLE_FROST in codes(a)


def test_single_snow_day_with_summer_tires_warns_but_no_auto_change():
    days = [MILD, Day(-1, 1, 6.0, PrecipType.SNOW), *repeat(MILD, 12)]
    a = run(days, TireType.SUMMER)
    assert WarningCode.POSSIBLE_SNOW in codes(a)
    snow = next(w for w in a.warnings if w.code == WarningCode.POSSIBLE_SNOW)
    assert snow.detail_key == "warning.snow.summer_tires"
    assert a.status == S.KEEP_CURRENT


def test_snow_warning_not_emphasised_on_winter_tires():
    days = [MILD, Day(-1, 1, 6.0, PrecipType.SNOW), *repeat(MILD, 12)]
    a = run(days, TireType.WINTER)
    snow = next(w for w in a.warnings if w.code == WarningCode.POSSIBLE_SNOW)
    assert snow.detail_key == "warning.snow"


def test_persistent_snow_recommends_change():
    days = [MILD, *repeat(Day(-1, 1, 6.0, PrecipType.SNOW), 2), *repeat(MILD, 11)]
    a = run(days)
    assert a.status == S.CHANGE_RECOMMENDED
    assert "reason.persistent_snow" in keys(a.reasons)


def test_cold_rain_without_wintry_precip():
    rainy_cold = Day(2, 5, 6.0, PrecipType.RAIN)
    a = run([MILD, MILD, *repeat(rainy_cold, 5), *repeat(MILD, 7)])
    assert WarningCode.POSSIBLE_SNOW not in codes(a)
    assert WarningCode.POSSIBLE_ICY_CONDITIONS not in codes(a)
    assert WarningCode.POSSIBLE_FROST not in codes(a)
    assert a.status == S.CHANGE_RECOMMENDED


def test_icy_from_freezing_rain_and_cold_rain_at_one_degree():
    a = run([MILD, Day(0.5, 3, 4.0, PrecipType.RAIN), *repeat(MILD, 12)])
    assert WarningCode.POSSIBLE_ICY_CONDITIONS in codes(a)
    b = run([MILD, Day(5, 8, 4.0, PrecipType.FREEZING_RAIN), *repeat(MILD, 12)])
    assert WarningCode.POSSIBLE_ICY_CONDITIONS in codes(b)


def test_icy_from_dewpoint_near_temperature_at_frost():
    a = run([MILD, Day(-3, 3), *repeat(MILD, 12)], dew_offset=0.5, humidity=95.0)
    assert WarningCode.POSSIBLE_ICY_CONDITIONS in codes(a)


def test_cold_streak_only_in_week_two_gives_period_not_date():
    days = [*repeat(MILD, 9), *repeat(COLD, 5)]  # start dag 10
    a = run(days)
    assert a.status == S.PREPARE_CHANGE
    assert a.recommended_date is None
    assert a.recommended_period == (
        AUTUMN_START + timedelta(days=6),
        AUTUMN_START + timedelta(days=9),
    )
    assert "reason.trend_only" in keys(a.reasons)


def test_short_horizon_cannot_confirm_streak():
    a = run([*repeat(MILD, 3), *repeat(COLD, 2)])  # 5 dagen horizon, reeks nog 2/3
    assert a.status == S.PREPARE_CHANGE
    assert a.recommended_date is None
    assert "uncertainty.beyond_horizon" in keys(a.uncertainties)


def test_all_season_only_warnings():
    a = run([MILD, Day(-3, 2), *repeat(MILD, 12)], TireType.ALL_SEASON)
    assert a.direction == Direction.NONE
    assert a.status == S.KEEP_CURRENT
    assert WarningCode.POSSIBLE_FROST in codes(a)
    assert a.recommended_date is None


def test_no_mounted_set_is_insufficient():
    a = run(repeat(MILD, 14), None)
    assert a.status == S.INSUFFICIENT_DATA


def test_summer_tires_in_summer_season_are_fine():
    now = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)
    a = run(repeat(COLD, 14), start=date(2026, 6, 1), now=now)
    assert a.status == S.KEEP_CURRENT
    assert "reason.winter_season_not_open" in keys(a.reasons)


def test_profiles_can_give_different_results():
    days = [MILD, *repeat(Day(0.5, 11.5), 12), MILD]  # dagmin ~0.5, gemiddelde 6
    morning = DrivingProfile.custom(
        [DriveSlot(weekday=d, start=time(6), end=time(8)) for d in range(7)]
    )
    afternoon = DrivingProfile.custom(
        [DriveSlot(weekday=d, start=time(14), end=time(16)) for d in range(7)]
    )
    a_morning = run(days, profile=morning)
    a_afternoon = run(days, profile=afternoon)
    assert a_morning.status == S.CHANGE_RECOMMENDED
    assert a_afternoon.status == S.KEEP_CURRENT


def test_days_without_slot_fall_back_and_say_so():
    days = repeat(COLD, 14)
    a = run(days, profile=DrivingProfile.weekend())  # werkdagen zonder slot
    assert any(r.key == "reason.drive_window_fallback" and r.params["days"] > 0 for r in a.reasons)
    assert a.status == S.CHANGE_RECOMMENDED


def test_long_garage_lead_time_gives_urgent_appointment():
    a = run([MILD, MILD, *repeat(COLD, 12)], lead_time_days=14)
    assert a.recommended_date == AUTUMN_START + timedelta(days=1)
    assert a.plan_appointment_by == AUTUMN_START  # niet in het verleden: vandaag
    assert "reason.appointment_urgent" in keys(a.reasons)


def test_lead_time_subtracted_from_date():
    a = run([*repeat(MILD, 6), *repeat(COLD, 8)], lead_time_days=3)  # reeks start dag 7
    assert a.recommended_date == AUTUMN_START + timedelta(days=5)
    assert a.plan_appointment_by == AUTUMN_START + timedelta(days=2)
    assert "reason.appointment_urgent" not in keys(a.reasons)


def test_dst_fall_back_day_has_25_hours_and_aggregates_correctly():
    from tests.fixtures.builders import AMS, make_forecast
    from wisselweer.core.engine import aggregate_days

    fc = make_forecast(date(2026, 10, 24), [Day(8, 14), Day(8, 14), Day(8, 14)])
    assert len(fc.hourly) == 24 + 25 + 24
    agg = aggregate_days(fc.hourly, DrivingProfile.commute(), AMS)
    assert sorted(agg) == [date(2026, 10, 24), date(2026, 10, 25), date(2026, 10, 26)]
    assert [agg[d].hours for d in sorted(agg)] == [24, 25, 24]
    # zondag 25 okt: geen commute-slot -> terugval op daggemiddelde
    assert agg[date(2026, 10, 25)].drive_mean_c is None
    assert agg[date(2026, 10, 26)].drive_mean_c is not None
    assert agg[date(2026, 10, 25)].min_c == min(
        p.temperature_c for p in fc.hourly if p.time.astimezone(AMS).date() == date(2026, 10, 25)
    )


def test_dst_evaluation_runs_across_transition():
    now = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)
    a = run(repeat(COLD, 14), start=date(2026, 10, 24), now=now)
    assert a.status == S.CHANGE_RECOMMENDED
    assert a.recommended_date == date(2026, 10, 24)


def test_now_aware_utc_default_constant():
    assert AUTUMN_NOW.tzinfo is not None
