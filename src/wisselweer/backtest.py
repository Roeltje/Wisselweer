"""Replay van opgeslagen forecast-snapshots door de adviesengine.

Waarom snapshots? Een eerlijke backtest moet weten wat de app OP DAT MOMENT kon weten:
de verwachting zoals die toen was opgehaald. Historische *waarnemingen* of een heranalyse
als "voorspelling" gebruiken is vals-optimistisch (de toekomst is dan bekend). Daarom bewaart
de app bij elke fetch een `forecast_snapshot`. Zie `docs/backtesting.md`.

Garanties van `replay`:
- beslismoment `now = snapshot.fetched_at`;
- de engine krijgt uitsluitend die ene snapshot plus het vorige advies (hysterese);
- nooit een latere snapshot en nooit waarnemingen (afgedwongen met een assert).

De uitkomsten zijn tellingen en datums, GEEN nauwkeurigheidspercentage. De adviesregels
zijn nog niet wetenschappelijk gevalideerd.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from wisselweer.core import (
    Advice,
    AdviceInput,
    AdviceStatus,
    Direction,
    DrivingProfile,
    EngineConfig,
    Forecast,
    TireType,
    evaluate,
)


@dataclass(frozen=True)
class ForecastSnapshotData:
    """Eén opgeslagen forecast (één locatie, één provider) en het moment van ophalen."""

    fetched_at: datetime
    forecast: Forecast


@dataclass(frozen=True)
class DailyObservation:
    """Waargenomen daggemiddelde temperatuur (°C) op een lokale kalenderdag."""

    day: date
    mean_c: float


@dataclass(frozen=True)
class ReplayStep:
    decided_at: datetime
    direction: Direction
    status: AdviceStatus
    raw_status: AdviceStatus | None
    recommended_date: date | None
    recommended_period: tuple[date, date] | None
    advice: Advice = field(repr=False, compare=False)


@dataclass(frozen=True)
class ReplayEvaluation:
    """Feitelijke getallen; geen oordeel en geen percentage."""

    steps: int
    status_changes: int
    flip_flops: int
    first_change_recommended_at: date | None
    first_recommended_date: date | None
    observed_streak_start: date | None
    # observed_streak_start - first_change_recommended_at in dagen (positief = advies vooraf).
    lead_days: int | None
    direction: Direction | None


def replay(
    snapshots: Sequence[ForecastSnapshotData],
    mounted: TireType | None,
    profile: DrivingProfile,
    config: EngineConfig,
    *,
    lead_time_days: int = 7,
) -> list[ReplayStep]:
    """Evalueer elk beslismoment alleen met de op dat moment beschikbare snapshot."""
    ordered = sorted(snapshots, key=lambda s: s.fetched_at)
    steps: list[ReplayStep] = []
    previous: Advice | None = None
    for snap in ordered:
        now = snap.fetched_at
        # Geen toekomstlek: de forecast mag niet later zijn opgehaald dan het beslismoment.
        assert snap.forecast.fetched_at <= now, "forecast is nieuwer dan het beslismoment"
        advice = evaluate(
            AdviceInput(
                forecast=snap.forecast,
                mounted=mounted,
                profile=profile,
                now=now,
                previous=previous,
                lead_time_days=lead_time_days,
                config=config,
            )
        )
        steps.append(
            ReplayStep(
                decided_at=now,
                direction=advice.direction,
                status=advice.status,
                raw_status=advice.raw_status,
                recommended_date=advice.recommended_date,
                recommended_period=advice.recommended_period,
                advice=advice,
            )
        )
        previous = advice
    return steps


def _observed_streak_start(
    observed: dict[date, DailyObservation], direction: Direction, config: EngineConfig, after: date
) -> date | None:
    """Eerste dag (>= after) van een reeks waargenomen koude (winter) of warme (zomer) dagen.

    Eenvoudig: daggemiddelde, niet gewogen naar rijmomenten, met dezelfde drempels als de engine.
    """
    if direction == Direction.TO_WINTER:
        need, hit = config.cold_streak_days, lambda t: t < config.cold_day_mean_c
    elif direction == Direction.TO_SUMMER:
        need, hit = config.warm_streak_days, lambda t: t >= config.warm_day_mean_c
    else:
        return None
    for day in sorted(d for d in observed if d >= after):
        if all(
            (day + timedelta(days=i)) in observed and hit(observed[day + timedelta(days=i)].mean_c)
            for i in range(need)
        ):
            return day
    return None


def evaluate_against_observations(
    steps: Sequence[ReplayStep],
    observed_daily: dict[date, DailyObservation],
    config: EngineConfig | None = None,
) -> ReplayEvaluation:
    """Vergelijk het verloop van het advies met de later waargenomen temperaturen.

    - `first_change_recommended_at`: datum waarop de status voor het eerst CHANGE_RECOMMENDED werd.
    - `observed_streak_start`: begin van de eerste waargenomen koude (naar winter) of warme
      (naar zomer) reeks op of na het eerste beslismoment, volgens dezelfde drempels.
    - `status_changes`: aantal keren dat de status verschilt van de vorige stap.
    - `flip_flops`: wissel A -> B -> A (status keert direct terug).
    """
    cfg = config or EngineConfig()
    statuses = [s.status for s in steps]
    changes = sum(1 for a, b in zip(statuses, statuses[1:], strict=False) if a != b)
    compressed: list[AdviceStatus] = []
    for st in statuses:
        if not compressed or compressed[-1] != st:
            compressed.append(st)
    flips = sum(1 for i in range(2, len(compressed)) if compressed[i] == compressed[i - 2])

    direction = (
        next((s.direction for s in steps if s.direction != Direction.NONE), steps[0].direction)
        if steps
        else None
    )
    first = next((s for s in steps if s.status == AdviceStatus.CHANGE_RECOMMENDED), None)
    first_at = first.decided_at.date() if first else None
    streak = None
    if steps and direction is not None:
        streak = _observed_streak_start(observed_daily, direction, cfg, steps[0].decided_at.date())
    lead = (streak - first_at).days if streak and first_at else None
    return ReplayEvaluation(
        steps=len(steps),
        status_changes=changes,
        flip_flops=flips,
        first_change_recommended_at=first_at,
        first_recommended_date=first.recommended_date if first else None,
        observed_streak_start=streak,
        lead_days=lead,
        direction=direction,
    )
