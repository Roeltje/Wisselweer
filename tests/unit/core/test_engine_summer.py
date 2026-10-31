from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tests.unit.core.helpers import Day, repeat, run
from wisselweer.core import AdviceStatus, Direction, TireType, WarningCode

S = AdviceStatus
W = TireType.WINTER
WARM = Day(8, 17)  # mean 12,5
CHILL = Day(2, 7)

APRIL = date(2027, 4, 12)
APRIL_NOW = datetime(2027, 4, 12, 7, 0, tzinfo=UTC)  # 09:00 lokaal (CEST)


def keys(items):
    return [r.key for r in items]


def spring(days, **kw):
    return run(days, W, start=APRIL, now=APRIL_NOW, **kw)


def test_mild_winter_keeps_winter_tires():
    now = datetime(2027, 1, 11, 7, 0, tzinfo=UTC)
    a = run(repeat(Day(7, 12), 14), W, start=date(2027, 1, 11), now=now)
    assert a.direction == Direction.TO_SUMMER
    assert a.status == S.KEEP_CURRENT
    assert "reason.summer_season_not_open" in keys(a.reasons)
    assert a.recommended_date is None


def test_short_warm_spell_in_january_gives_no_summer_advice():
    now = datetime(2027, 1, 11, 7, 0, tzinfo=UTC)
    days = [*repeat(CHILL, 3), *repeat(Day(9, 15), 3), *repeat(CHILL, 8)]
    a = run(days, W, start=date(2027, 1, 11), now=now)
    assert a.status == S.KEEP_CURRENT
    assert a.recommended_date is None
    assert "reason.warm_spell_too_short" in keys(a.reasons)


def test_short_warm_spell_in_season_keeps_winter():
    days = [*repeat(WARM, 3), *repeat(CHILL, 11)]
    a = spring(days)
    assert a.status == S.KEEP_CURRENT
    assert "reason.warm_spell_too_short" in keys(a.reasons)


def test_stable_spring_warming_recommends_change():
    a = spring([*repeat(CHILL, 2), *repeat(WARM, 12)])
    assert a.status == S.CHANGE_RECOMMENDED
    assert a.recommended_date == APRIL + timedelta(days=2)
    assert (
        a.plan_appointment_by == APRIL + timedelta(days=2) - timedelta(days=7)
        or a.plan_appointment_by == APRIL
    )
    assert "reason.warm_streak" in keys(a.reasons)


def test_late_spring_frost_blocks_summer_advice():
    days = [*repeat(WARM, 4), Day(-1, 10), *repeat(WARM, 9)]
    a = spring(days)
    assert a.status == S.KEEP_CURRENT
    assert "reason.frost_in_horizon" in keys(a.reasons)
    assert a.recommended_date is None


def test_frost_beyond_72h_still_blocks_but_no_warning():
    days = [*repeat(WARM, 8), Day(-1, 10), *repeat(WARM, 5)]
    a = spring(days)
    assert a.status == S.KEEP_CURRENT
    assert WarningCode.POSSIBLE_FROST not in {w.code for w in a.warnings}


def test_short_horizon_does_not_confirm_warm_streak():
    a = spring(repeat(WARM, 5))
    assert a.status == S.KEEP_CURRENT
    assert a.recommended_date is None
    assert "uncertainty.beyond_horizon" in keys(a.uncertainties)


def test_warm_streak_in_second_week_gives_period():
    a = spring([*repeat(CHILL, 7), *repeat(WARM, 7)])
    assert a.status == S.PREPARE_CHANGE
    assert a.recommended_date is None
    assert a.recommended_period == (APRIL + timedelta(days=4), APRIL + timedelta(days=7))


def test_cold_streak_does_not_trigger_summer_logic_reversed():
    # winterbanden in april + kou: gewoon behouden
    a = spring(repeat(CHILL, 14))
    assert a.status == S.KEEP_CURRENT
    assert a.direction == Direction.TO_SUMMER
