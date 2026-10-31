"""Pure adviesberekening: evaluate(AdviceInput) -> Advice. Geen IO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from wisselweer.core.config import EngineConfig
from wisselweer.core.models import (
    Advice,
    AdviceInput,
    AdviceStatus,
    AdviceWarning,
    Direction,
    DrivingProfile,
    HourlyPoint,
    PrecipType,
    ReasonItem,
    TireType,
    WarningCode,
    heading_key,
)
from wisselweer.core.rules_version import RULES_VERSION
from wisselweer.core.stability import apply_hysteresis

_HOUR = timedelta(hours=1)
_WINTRY = {PrecipType.SNOW, PrecipType.SLEET}
_ANY_PRECIP = {PrecipType.RAIN, PrecipType.SNOW, PrecipType.SLEET, PrecipType.FREEZING_RAIN}
# Variabelen waarvan het ontbreken de nauwkeurigheid van waarschuwingen beperkt.
_OPTIONAL_VARIABLES = ("dew_point_c", "humidity_pct", "precip_mm", "precip_type", "snow_cm")


# --------------------------------------------------------------------------- aggregatie


@dataclass(frozen=True)
class DayAggregate:
    """Aggregaat per lokale kalenderdag."""

    day: date
    hours: int  # uren met temperatuur (25 op DST-terugdag)
    min_c: float
    max_c: float
    mean_c: float
    drive_mean_c: float | None  # gemiddelde over uren binnen profielslots; None = geen slot
    wintry: bool  # sneeuw/ijzel-uur aanwezig

    @property
    def decision_c(self) -> float:
        """Rijmoment-temperatuur, of daggemiddelde als de dag geen slot heeft."""
        return self.drive_mean_c if self.drive_mean_c is not None else self.mean_c

    @property
    def used_fallback(self) -> bool:
        return self.drive_mean_c is None


def _is_wintry(p: HourlyPoint) -> bool:
    return (p.snow_cm is not None and p.snow_cm > 0) or p.precip_type in _WINTRY


def _in_slot(profile: DrivingProfile, weekday: int, minute_of_day: int) -> bool:
    """Uur [m, m+60) overlapt een slot (lokale wandtijd)."""
    for s in profile.slots:
        if s.weekday != weekday:
            continue
        start = s.start.hour * 60 + s.start.minute
        end = s.end.hour * 60 + s.end.minute
        if minute_of_day < end and minute_of_day + 60 > start:
            return True
    return False


def aggregate_days(
    points: list[HourlyPoint], profile: DrivingProfile, tz: ZoneInfo, min_hours: int = 1
) -> dict[date, DayAggregate]:
    """Groepeer uren per lokale dag (DST-correct via zoneinfo). Dagen met < min_hours
    uren temperatuur worden weggelaten."""
    temps: dict[date, list[float]] = {}
    drive: dict[date, list[float]] = {}
    wintry: dict[date, bool] = {}
    for p in points:
        local = p.time.astimezone(tz)
        d = local.date()
        if _is_wintry(p):
            wintry[d] = True
        if p.temperature_c is None:
            continue
        temps.setdefault(d, []).append(p.temperature_c)
        if _in_slot(profile, d.weekday(), local.hour * 60 + local.minute):
            drive.setdefault(d, []).append(p.temperature_c)
    out: dict[date, DayAggregate] = {}
    for d, ts in temps.items():
        if len(ts) < min_hours:
            continue
        dv = drive.get(d)
        out[d] = DayAggregate(
            day=d,
            hours=len(ts),
            min_c=min(ts),
            max_c=max(ts),
            mean_c=sum(ts) / len(ts),
            drive_mean_c=(sum(dv) / len(dv)) if dv else None,
            wintry=wintry.get(d, False),
        )
    return out


# --------------------------------------------------------------------------- waarschuwingen


def _icy(p: HourlyPoint, cfg: EngineConfig) -> bool:
    if p.precip_type == PrecipType.FREEZING_RAIN:
        return True
    t = p.temperature_c
    if t is None:
        return False
    has_precip = (p.precip_mm is not None and p.precip_mm >= cfg.precip_threshold_mm) or (
        p.precip_type in _ANY_PRECIP
    )
    if has_precip and p.precip_type != PrecipType.SNOW and t <= cfg.icy_precip_temp_c:
        return True
    if (
        t <= cfg.frost_threshold_c
        and p.dew_point_c is not None
        and p.dew_point_c >= t - cfg.icy_dewpoint_margin_c
        and (p.humidity_pct is None or p.humidity_pct >= cfg.icy_humidity_pct)
    ):
        return True
    return False


def _warnings(
    points: list[HourlyPoint], now: datetime, cfg: EngineConfig, mounted: TireType | None
) -> list[AdviceWarning]:
    end_window = now + timedelta(hours=cfg.short_term_hours)
    spans: dict[WarningCode, list[datetime]] = {}
    for p in points:
        if not (now - _HOUR < p.time < end_window):
            continue
        t = p.temperature_c
        if t is not None and t <= cfg.frost_threshold_c:
            spans.setdefault(WarningCode.POSSIBLE_FROST, []).append(p.time)
        if _is_wintry(p):
            spans.setdefault(WarningCode.POSSIBLE_SNOW, []).append(p.time)
        if _icy(p, cfg):
            spans.setdefault(WarningCode.POSSIBLE_ICY_CONDITIONS, []).append(p.time)
    names = {
        WarningCode.POSSIBLE_FROST: "warning.frost",
        WarningCode.POSSIBLE_SNOW: "warning.snow",
        WarningCode.POSSIBLE_ICY_CONDITIONS: "warning.icy",
    }
    suffix = ".summer_tires" if mounted == TireType.SUMMER else ""
    result = []
    for code in names:
        if code in spans:
            times = spans[code]
            result.append(
                AdviceWarning(
                    code=code,
                    start=min(times),
                    end=max(times) + _HOUR,
                    detail_key=names[code] + suffix,
                )
            )
    return result


def _missing_variables(fc_vars: set[str], points: list[HourlyPoint]) -> list[ReasonItem]:
    out = []
    for var in _OPTIONAL_VARIABLES:
        provided = var in fc_vars and any(getattr(p, var) is not None for p in points)
        if not provided:
            out.append(ReasonItem(key="uncertainty.missing_variable", params={"variable": var}))
    return out


# --------------------------------------------------------------------------- reeksen


def _first_run(flags: list[bool], n: int) -> int | None:
    """Index waar de eerste reeks van n aaneengesloten True begint."""
    run = 0
    for i, f in enumerate(flags):
        run = run + 1 if f else 0
        if run >= n:
            return i - n + 1
    return None


def _trailing_run(flags: list[bool]) -> int:
    n = 0
    for f in reversed(flags):
        if not f:
            break
        n += 1
    return n


def _season_open(today: date, cfg: EngineConfig, direction: Direction) -> bool:
    md = (today.month, today.day)
    summer_window = cfg.summer_earliest <= md < cfg.winter_earliest
    return summer_window if direction == Direction.TO_SUMMER else not summer_window


@dataclass
class _Outcome:
    status: AdviceStatus
    recommended_date: date | None = None
    period: tuple[date, date] | None = None


def _iso(d: date) -> str:
    return d.isoformat()


def _to_winter(
    days: list[date],
    agg: dict[date, DayAggregate],
    today: date,
    cfg: EngineConfig,
    reasons: list[ReasonItem],
    uncertainties: list[ReasonItem],
) -> _Outcome:
    if not _season_open(today, cfg, Direction.TO_WINTER):
        reasons.append(ReasonItem(key="reason.winter_season_not_open"))
        return _Outcome(AdviceStatus.KEEP_CURRENT)

    cold = [d in agg and agg[d].decision_c < cfg.cold_day_mean_c for d in days]
    frost = [d in agg and agg[d].min_c <= cfg.frost_threshold_c for d in days]
    snow = [d in agg and agg[d].wintry for d in days]
    candidates: list[tuple[int, int, str, int]] = []  # (start, prioriteit, sleutel, n)
    for prio, (flags, n, key) in enumerate(
        (
            (frost, cfg.persistent_frost_days, "reason.persistent_frost"),
            (snow, cfg.persistent_snow_days, "reason.persistent_snow"),
            (cold, cfg.cold_streak_days, "reason.cold_streak"),
        )
    ):
        start = _first_run(flags, n)
        if start is not None:
            candidates.append((start, prio, key, n))

    if candidates:
        start, _, key, n = min(candidates)
        start_date = days[start]
        params: dict = {"start": _iso(start_date), "days": n}
        if key == "reason.cold_streak":
            params["threshold"] = cfg.cold_day_mean_c
        reasons.append(ReasonItem(key=key, params=params))
        if start + 1 <= cfg.concrete_until_day:
            return _Outcome(
                AdviceStatus.CHANGE_RECOMMENDED, max(start_date - timedelta(days=1), today)
            )
        reasons.append(ReasonItem(key="reason.trend_only"))
        lo = max(today, start_date - timedelta(days=cfg.prepare_days_before))
        return _Outcome(AdviceStatus.PREPARE_CHANGE, period=(lo, start_date))

    trail = _trailing_run(cold)
    if trail >= max(1, cfg.cold_streak_days - 1) and trail < cfg.cold_streak_days:
        start_date = days[len(days) - trail]
        uncertainties.append(ReasonItem(key="uncertainty.beyond_horizon"))
        lo = max(today, start_date - timedelta(days=cfg.prepare_days_before))
        return _Outcome(AdviceStatus.PREPARE_CHANGE, period=(lo, start_date))

    reasons.append(ReasonItem(key="reason.no_sustained_cold"))
    return _Outcome(AdviceStatus.KEEP_CURRENT)


def _to_summer(
    days: list[date],
    agg: dict[date, DayAggregate],
    today: date,
    cfg: EngineConfig,
    reasons: list[ReasonItem],
    uncertainties: list[ReasonItem],
) -> _Outcome:
    warm = [d in agg and agg[d].decision_c >= cfg.warm_day_mean_c for d in days]
    n = cfg.warm_streak_days

    # Korte warme periode (afgesloten binnen de horizon) herkennen voor de uitleg.
    short_spell = False
    run = 0
    for i, f in enumerate(warm):
        run = run + 1 if f else 0
        if f and (i + 1 < len(warm)) and not warm[i + 1] and 2 <= run < n:
            short_spell = True

    if not _season_open(today, cfg, Direction.TO_SUMMER):
        reasons.append(ReasonItem(key="reason.summer_season_not_open"))
        if short_spell:
            reasons.append(ReasonItem(key="reason.warm_spell_too_short"))
        return _Outcome(AdviceStatus.KEEP_CURRENT)

    cold_days = [
        d for d in days if d in agg and (agg[d].min_c <= cfg.frost_threshold_c or agg[d].wintry)
    ]
    if cold_days:
        reasons.append(
            ReasonItem(key="reason.frost_in_horizon", params={"first_day": _iso(cold_days[0])})
        )
        return _Outcome(AdviceStatus.KEEP_CURRENT)

    start = _first_run(warm, n)
    if start is not None:
        start_date = days[start]
        reasons.append(
            ReasonItem(
                key="reason.warm_streak",
                params={"start": _iso(start_date), "days": n, "threshold": cfg.warm_day_mean_c},
            )
        )
        if start + 1 <= cfg.concrete_until_day:
            return _Outcome(AdviceStatus.CHANGE_RECOMMENDED, max(start_date, today))
        reasons.append(ReasonItem(key="reason.trend_only"))
        lo = max(today, start_date - timedelta(days=cfg.prepare_days_before))
        return _Outcome(AdviceStatus.PREPARE_CHANGE, period=(lo, start_date))

    if short_spell:
        reasons.append(ReasonItem(key="reason.warm_spell_too_short"))
    else:
        reasons.append(ReasonItem(key="reason.not_warm_enough"))
    if 0 < _trailing_run(warm) < n:
        uncertainties.append(ReasonItem(key="uncertainty.beyond_horizon"))
    return _Outcome(AdviceStatus.KEEP_CURRENT)


# --------------------------------------------------------------------------- evaluate


def _finish(
    inp: AdviceInput,
    direction: Direction,
    status: AdviceStatus,
    *,
    warnings: list[AdviceWarning],
    reasons: list[ReasonItem],
    uncertainties: list[ReasonItem],
    recommended_date: date | None = None,
    period: tuple[date, date] | None = None,
    today: date | None = None,
    horizon_until: date | None = None,
) -> Advice:
    plan_by = None
    anchor = recommended_date or (period[0] if period else None)
    if anchor is not None and today is not None:
        plan_by = anchor - timedelta(days=inp.lead_time_days)
        if plan_by < today:
            late = (today - plan_by).days
            plan_by = today
            reasons.append(ReasonItem(key="reason.appointment_urgent", params={"days_late": late}))
    advice = Advice(
        direction=direction,
        heading=heading_key(direction, status),
        status=status,
        warnings=warnings,
        recommended_date=recommended_date,
        recommended_period=period,
        plan_appointment_by=plan_by,
        horizon_until=horizon_until,
        reasons=reasons,
        uncertainties=uncertainties,
        rules_version=RULES_VERSION,
        evaluated_at=inp.now,
        forecast_provider=inp.forecast.provider if inp.forecast else None,
        raw_status=status,
    )
    if inp.previous is not None:
        advice = apply_hysteresis(advice, inp.previous, inp.config)
    return advice


def _direction(mounted: TireType | None) -> Direction:
    if mounted == TireType.SUMMER:
        return Direction.TO_WINTER
    if mounted == TireType.WINTER:
        return Direction.TO_SUMMER
    return Direction.NONE


def evaluate(inp: AdviceInput) -> Advice:
    cfg = inp.config
    now = inp.now
    direction = _direction(inp.mounted)
    fc = inp.forecast
    insufficient = AdviceStatus.INSUFFICIENT_DATA

    if fc is None:
        w = AdviceWarning(
            code=WarningCode.FORECAST_UNAVAILABLE,
            start=now,
            end=now,
            detail_key="warning.forecast_unavailable",
        )
        return _finish(
            inp,
            direction,
            insufficient,
            warnings=[w],
            reasons=[ReasonItem(key="reason.no_forecast")],
            uncertainties=[],
        )

    tz = ZoneInfo(fc.timezone)
    today = now.astimezone(tz).date()
    horizon_until = max(p.time for p in fc.hourly).astimezone(tz).date() if fc.hourly else None
    age_h = (now - fc.fetched_at).total_seconds() / 3600
    stale = fc.is_stale or age_h > cfg.stale_after_hours

    if age_h > cfg.max_forecast_age_hours:
        w = AdviceWarning(
            code=WarningCode.FORECAST_STALE,
            start=fc.fetched_at,
            end=now,
            detail_key="warning.forecast_stale",
        )
        return _finish(
            inp,
            direction,
            insufficient,
            warnings=[w],
            reasons=[ReasonItem(key="reason.forecast_too_old")],
            uncertainties=[],
            horizon_until=horizon_until,
        )

    future_temp_hours = sum(
        1 for p in fc.hourly if p.temperature_c is not None and p.time + _HOUR > now
    )
    if future_temp_hours < cfg.min_hours_required:
        w = AdviceWarning(
            code=WarningCode.FORECAST_UNAVAILABLE,
            start=now,
            end=now,
            detail_key="warning.forecast_unavailable",
        )
        return _finish(
            inp,
            direction,
            insufficient,
            warnings=[w],
            reasons=[ReasonItem(key="reason.insufficient_hours")],
            uncertainties=[],
            horizon_until=horizon_until,
        )

    warnings = _warnings(fc.hourly, now, cfg, inp.mounted)
    reasons: list[ReasonItem] = []
    uncertainties = _missing_variables(fc.available_variables, fc.hourly)
    if stale:
        warnings.append(
            AdviceWarning(
                code=WarningCode.FORECAST_STALE,
                start=fc.fetched_at,
                end=now,
                detail_key="warning.forecast_stale",
            )
        )
        uncertainties.append(ReasonItem(key="uncertainty.forecast_stale"))

    def done(out: _Outcome) -> Advice:
        return _finish(
            inp,
            direction,
            out.status,
            warnings=warnings,
            reasons=reasons,
            uncertainties=uncertainties,
            recommended_date=out.recommended_date,
            period=out.period,
            today=today,
            horizon_until=horizon_until,
        )

    if inp.mounted is None:
        reasons.append(ReasonItem(key="reason.no_mounted_set"))
        return done(_Outcome(insufficient))
    if direction == Direction.NONE:
        reasons.append(ReasonItem(key="reason.all_season_warnings_only"))
        return done(_Outcome(AdviceStatus.KEEP_CURRENT))

    agg = aggregate_days(fc.hourly, inp.profile, tz, cfg.min_hours_per_day)
    last = horizon_until or today
    days = [today + timedelta(days=i) for i in range((last - today).days + 1)]
    used = [agg[d] for d in days if d in agg]
    if inp.profile.slots:
        fallback = sum(1 for a in used if a.used_fallback)
        if fallback:
            reasons.append(
                ReasonItem(key="reason.drive_window_fallback", params={"days": fallback})
            )
        else:
            reasons.append(ReasonItem(key="reason.drive_window_used"))
    else:
        reasons.append(ReasonItem(key="reason.drive_window_fallback", params={"days": len(used)}))

    fn = _to_winter if direction == Direction.TO_WINTER else _to_summer
    return done(fn(days, agg, today, cfg, reasons, uncertainties))
