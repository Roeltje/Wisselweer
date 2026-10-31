from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tests.unit.core.helpers import AUTUMN_NOW, Day, repeat, run
from wisselweer.core import (
    Advice,
    AdviceStatus,
    AdviceWarning,
    Direction,
    EngineConfig,
    TireType,
    WarningCode,
    apply_hysteresis,
)

S = AdviceStatus
MILD = Day(8, 15)
COLD = Day(1, 6)
WARM = Day(8, 17)
CFG = EngineConfig()
NOW = datetime(2026, 11, 2, 7, tzinfo=UTC)


def adv(status, direction=Direction.TO_SUMMER, **kw) -> Advice:
    return Advice(
        direction=direction,
        heading="h",
        status=status,
        evaluated_at=NOW,
        raw_status=status,
        recommended_date=date(2027, 4, 15) if status == S.CHANGE_RECOMMENDED else None,
        **kw,
    )


def test_first_evaluation_passes_through():
    assert apply_hysteresis(adv(S.CHANGE_RECOMMENDED), None, CFG).status == S.CHANGE_RECOMMENDED


def test_to_winter_raise_is_immediate():
    prev = adv(S.KEEP_CURRENT, Direction.TO_WINTER)
    out = apply_hysteresis(adv(S.CHANGE_RECOMMENDED, Direction.TO_WINTER), prev, CFG)
    assert out.status == S.CHANGE_RECOMMENDED


def test_to_summer_raise_needs_confirmations():
    prev = adv(S.KEEP_CURRENT)
    first = apply_hysteresis(adv(S.CHANGE_RECOMMENDED), prev, CFG)
    assert first.status == S.KEEP_CURRENT and first.confirm_streak == 1
    assert first.recommended_date is None
    assert any(r.key == "reason.status_held" for r in first.reasons)
    second = apply_hysteresis(adv(S.CHANGE_RECOMMENDED), first, CFG)
    assert second.status == S.CHANGE_RECOMMENDED and second.confirm_streak == 0


def test_lowering_needs_confirmations_and_keeps_date():
    prev = adv(S.CHANGE_RECOMMENDED, Direction.TO_WINTER)
    first = apply_hysteresis(adv(S.KEEP_CURRENT, Direction.TO_WINTER), prev, CFG)
    assert first.status == S.CHANGE_RECOMMENDED
    assert first.recommended_date == prev.recommended_date
    second = apply_hysteresis(adv(S.KEEP_CURRENT, Direction.TO_WINTER), first, CFG)
    assert second.status == S.KEEP_CURRENT and second.recommended_date is None


def test_interrupted_confirmation_resets_streak():
    prev = adv(S.CHANGE_RECOMMENDED, Direction.TO_WINTER)
    a = apply_hysteresis(adv(S.KEEP_CURRENT, Direction.TO_WINTER), prev, CFG)
    b = apply_hysteresis(adv(S.CHANGE_RECOMMENDED, Direction.TO_WINTER), a, CFG)
    assert b.status == S.CHANGE_RECOMMENDED and b.confirm_streak == 0
    c = apply_hysteresis(adv(S.KEEP_CURRENT, Direction.TO_WINTER), b, CFG)
    assert c.status == S.CHANGE_RECOMMENDED and c.confirm_streak == 1


def test_direction_change_resets():
    prev = adv(S.CHANGE_RECOMMENDED, Direction.TO_WINTER)
    out = apply_hysteresis(adv(S.KEEP_CURRENT, Direction.TO_SUMMER), prev, CFG)
    assert out.status == S.KEEP_CURRENT and out.confirm_streak == 0


def test_insufficient_data_passes_through():
    prev = adv(S.CHANGE_RECOMMENDED, Direction.TO_WINTER)
    assert (
        apply_hysteresis(adv(S.INSUFFICIENT_DATA, Direction.TO_WINTER), prev, CFG).status
        == S.INSUFFICIENT_DATA
    )


def test_warnings_are_never_dampened():
    prev = adv(S.CHANGE_RECOMMENDED, Direction.TO_WINTER)
    w = AdviceWarning(
        code=WarningCode.POSSIBLE_FROST,
        start=NOW,
        end=NOW + timedelta(hours=3),
        detail_key="warning.frost",
    )
    new = adv(S.KEEP_CURRENT, Direction.TO_WINTER, warnings=[w])
    out = apply_hysteresis(new, prev, CFG)
    assert out.status == S.CHANGE_RECOMMENDED and out.warnings == [w]


def test_no_flip_flop_over_four_noisy_evaluations_summer():
    """Ruis tussen 'warm' en 'vorst' mag het zomeradvies niet heen en weer laten springen."""
    from datetime import date as d

    start, now = d(2027, 4, 12), datetime(2027, 4, 12, 7, tzinfo=UTC)
    good = [*repeat(WARM, 14)]
    bad = [*repeat(WARM, 4), Day(-1, 10), *repeat(WARM, 9)]
    prev = None
    statuses = []
    for days in (good, bad, good, bad):
        prev = run(days, TireType.WINTER, start=start, now=now, previous=prev)
        statuses.append(prev.status)
    assert len(set(statuses)) == 1
    assert statuses == [S.KEEP_CURRENT] * 4 or statuses == [S.CHANGE_RECOMMENDED] * 4


def test_no_flip_flop_over_four_noisy_evaluations_winter():
    cold = [MILD, MILD, *repeat(COLD, 12)]
    mild = repeat(MILD, 14)
    prev = None
    statuses = []
    for days in (cold, mild, cold, mild):
        prev = run(days, TireType.SUMMER, previous=prev)
        statuses.append(prev.status)
    changes = sum(1 for a, b in zip(statuses, statuses[1:], strict=False) if a != b)
    assert statuses[0] == S.CHANGE_RECOMMENDED
    assert changes == 0, statuses


def test_sustained_change_eventually_lowers():
    cold = [MILD, MILD, *repeat(COLD, 12)]
    mild = repeat(MILD, 14)
    prev = run(cold, TireType.SUMMER)
    prev = run(mild, TireType.SUMMER, previous=prev)
    assert prev.status == S.CHANGE_RECOMMENDED
    prev = run(mild, TireType.SUMMER, previous=prev)
    assert prev.status == S.KEEP_CURRENT
    assert prev.recommended_date is None


def test_frost_warning_visible_even_when_status_held():
    cold = [MILD, MILD, *repeat(COLD, 12)]
    frosty_mild = [MILD, Day(-2, 9), *repeat(MILD, 12)]
    prev = run(cold, TireType.SUMMER)
    out = run(frosty_mild, TireType.SUMMER, previous=prev)
    assert out.status == S.CHANGE_RECOMMENDED  # gehouden
    assert WarningCode.POSSIBLE_FROST in {w.code for w in out.warnings}
    assert AUTUMN_NOW  # silence unused
