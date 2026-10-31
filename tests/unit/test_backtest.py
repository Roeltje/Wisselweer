from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from tests.fixtures.builders import Day, make_forecast, repeat
from wisselweer.backtest import (
    DailyObservation,
    ForecastSnapshotData,
    evaluate_against_observations,
    replay,
)
from wisselweer.core import AdviceStatus, DrivingProfile, EngineConfig, TireType

CFG = EngineConfig()
PROFILE = DrivingProfile.commute()
MILD = Day(8, 15)
COLD = Day(-4, 1)
START = date(2026, 11, 2)
T0 = datetime(2026, 11, 2, 7, tzinfo=UTC)


def snap(at: datetime, days: list[Day]) -> ForecastSnapshotData:
    fc = make_forecast(at.date(), days, fetched_at=at, provider="fixture")
    return ForecastSnapshotData(fetched_at=at, forecast=fc)


def run(snaps, mounted=TireType.SUMMER):
    return replay(snaps, mounted, PROFILE, CFG)


def test_empty_input():
    assert run([]) == []
    ev = evaluate_against_observations([], {})
    assert ev.steps == 0 and ev.status_changes == 0 and ev.first_change_recommended_at is None


def test_no_future_leak_later_snapshot_not_used():
    mild = snap(T0, repeat(MILD, 10))
    cold = snap(T0 + timedelta(days=1), repeat(COLD, 10))
    both = run([mild, cold])
    alone = run([mild])
    assert both[0].advice.model_dump() == alone[0].advice.model_dump()
    assert both[0].status == AdviceStatus.KEEP_CURRENT
    assert both[1].raw_status == AdviceStatus.CHANGE_RECOMMENDED


def test_forecast_newer_than_decision_moment_rejected():
    fc = make_forecast(START, repeat(MILD, 10), fetched_at=T0 + timedelta(hours=1))
    with pytest.raises(AssertionError):
        run([ForecastSnapshotData(fetched_at=T0, forecast=fc)])


def test_input_is_sorted_chronologically():
    a, b = snap(T0, repeat(MILD, 10)), snap(T0 + timedelta(days=1), repeat(COLD, 10))
    assert [s.decided_at for s in run([b, a])] == [T0, T0 + timedelta(days=1)]


def test_hysteresis_carries_over():
    # winter -> zomer: verlaging van CHANGE_RECOMMENDED pas na meerdere bevestigingen
    cold = snap(T0, repeat(COLD, 10))
    mild1 = snap(T0 + timedelta(days=1), repeat(MILD, 10))
    mild2 = snap(T0 + timedelta(days=2), repeat(MILD, 10))
    steps = run([cold, mild1, mild2])
    assert steps[0].status == AdviceStatus.CHANGE_RECOMMENDED
    assert steps[1].raw_status != AdviceStatus.CHANGE_RECOMMENDED
    assert steps[1].status == AdviceStatus.CHANGE_RECOMMENDED  # vastgehouden
    assert steps[2].status == steps[2].raw_status != AdviceStatus.CHANGE_RECOMMENDED


def test_flip_flop_and_status_change_count():
    # onvoldoende data -> advies -> onvoldoende data -> advies (hysterese reset bij INSUFFICIENT)
    s = [
        snap(T0, repeat(COLD, 10)),
        snap(T0 + timedelta(days=1), repeat(COLD, 1)),
        snap(T0 + timedelta(days=2), repeat(COLD, 10)),
    ]
    steps = run(s)
    ev = evaluate_against_observations(steps, {})
    assert [x.status for x in steps] == [
        AdviceStatus.CHANGE_RECOMMENDED,
        AdviceStatus.INSUFFICIENT_DATA,
        AdviceStatus.CHANGE_RECOMMENDED,
    ]
    assert ev.status_changes == 2
    assert ev.flip_flops == 1


def test_observed_streak_and_lead():
    steps = run([snap(T0, repeat(COLD, 10))])
    obs = {
        START + timedelta(days=i): DailyObservation(START + timedelta(days=i), 1.0 if i >= 3 else 9)
        for i in range(8)
    }
    ev = evaluate_against_observations(steps, obs, CFG)
    assert ev.first_change_recommended_at == START
    assert ev.observed_streak_start == START + timedelta(days=3)
    assert ev.lead_days == 3


def test_no_observed_streak():
    steps = run([snap(T0, repeat(COLD, 10))])
    obs = {START: DailyObservation(START, 1.0)}
    assert evaluate_against_observations(steps, obs).observed_streak_start is None
