"""Weergavemodellen: vertaalt services/adviezen naar wat de templates tonen."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from wisselweer.core.models import (
    Advice,
    AdviceStatus,
    Direction,
    DrivingProfile,
    ProfileKind,
    ReasonItem,
    TireType,
    WarningCode,
)
from wisselweer.garages.schemas import AppointmentOut, GarageOut
from wisselweer.garages.service import list_appointments, list_garages
from wisselweer.i18n import format_date, format_datetime, t
from wisselweer.storage.enums import APPOINTMENT_TRANSITIONS, AppointmentStatus, TireStatus
from wisselweer.storage.orm import AdviceSnapshot, ForecastSnapshot
from wisselweer.tires.schemas import OdometerOut, TireSetOut
from wisselweer.tires.service import (
    km_per_set,
    list_odometer_readings,
    list_tire_changes,
    list_tire_sets,
    list_tread_measurements,
)
from wisselweer.vehicles.schemas import VehicleOut
from wisselweer.weather.base import ProviderInfo

log = logging.getLogger("wisselweer.web")

Tr = Callable[..., str]

SAFETY_WARNINGS = {
    WarningCode.POSSIBLE_FROST,
    WarningCode.POSSIBLE_SNOW,
    WarningCode.POSSIBLE_ICY_CONDITIONS,
}
ACTIVE_APPOINTMENTS = (
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.REQUESTED,
    AppointmentStatus.TO_REQUEST,
)
_BADGE = {
    AdviceStatus.KEEP_CURRENT: ("ok", "check"),
    AdviceStatus.PREPARE_CHANGE: ("prepare", "clock"),
    AdviceStatus.CHANGE_RECOMMENDED: ("change", "swap"),
    AdviceStatus.INSUFFICIENT_DATA: ("unknown", "question"),
}


def make_tr(locale: str) -> Tr:
    def tr(key: str, **params: object) -> str:
        return t(key, locale, **params)

    return tr


def tz_of(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Europe/Amsterdam")
    except Exception:  # noqa: BLE001 - onbekende tijdzone => standaard
        return ZoneInfo("Europe/Amsterdam")


@dataclass
class WarningView:
    code: str
    label: str
    text: str
    window: str


@dataclass
class AdviceView:
    question: str
    status: str
    badge_class: str
    badge_icon: str
    badge_text: str
    heading: str
    date_line: str | None
    plan_by: str | None
    warnings: list[WarningView] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    horizon_text: str | None = None
    no_mounted: bool = False
    direction: str = "none"


@dataclass
class VehicleCard:
    vehicle: VehicleOut
    mounted: TireSetOut | None
    advice: AdviceView | None
    advice_failed: bool
    appointment: dict | None
    weather: dict | None


def _params(params: dict, locale: str) -> dict:
    out = {}
    for k, v in params.items():
        if isinstance(v, str) and len(v) == 10 and v[4:5] == "-" and v[7:8] == "-":
            v = format_date(v, locale)
        out[k] = v
    return out


def _item(item: ReasonItem, locale: str) -> str:
    return t(item.key, locale, **_params(item.params, locale))


def provider_map(infos: list[ProviderInfo]) -> dict[str, ProviderInfo]:
    return {i.id: i for i in infos}


def build_advice_view(
    advice: Advice, locale: str, tz: ZoneInfo, infos: list[ProviderInfo], *, no_mounted: bool
) -> AdviceView:
    tr = make_tr(locale)
    status = advice.status
    badge_class, icon = _BADGE[status]
    question = tr(f"advice.question.{advice.direction.value}")

    date_line: str | None = None
    if advice.direction != Direction.NONE:
        if advice.recommended_date:
            date_line = tr(
                "advice.recommended_date", date=format_date(advice.recommended_date, locale)
            )
        elif advice.recommended_period:
            a, b = advice.recommended_period
            date_line = tr(
                "advice.recommended_period",
                start=format_date(a, locale),
                end=format_date(b, locale),
            )
        else:
            date_line = tr("advice.no_reliable_date")
    plan_by = (
        tr("advice.plan_by", date=format_date(advice.plan_appointment_by, locale))
        if advice.plan_appointment_by and advice.direction != Direction.NONE
        else None
    )

    warnings: list[WarningView] = []
    notices: list[str] = []
    for w in advice.warnings:
        if w.code in SAFETY_WARNINGS:
            window = tr(
                "warning.window",
                start=format_datetime(w.start.astimezone(tz), locale),
                end=format_datetime(w.end.astimezone(tz), locale),
            )
            warnings.append(
                WarningView(
                    code=w.code.value,
                    label=tr(f"warning.label.{w.code.value}"),
                    text=tr(w.detail_key),
                    window=window,
                )
            )
        else:
            notices.append(tr(w.detail_key))

    horizon_text = None
    if advice.horizon_until:
        horizon_text = tr("advice.horizon_until", date=format_date(advice.horizon_until, locale))
        info = next((i for i in infos if i.id == advice.forecast_provider), None)
        if info is not None:
            horizon_text += " " + tr(
                "advice.horizon_provider", name=info.name, days=max(1, info.horizon_hours // 24)
            )

    return AdviceView(
        question=question,
        status=status.value,
        badge_class=badge_class,
        badge_icon=icon,
        badge_text=tr(f"status.{status.value}"),
        heading=tr(advice.heading),
        date_line=date_line,
        plan_by=plan_by,
        warnings=warnings,
        notices=notices,
        reasons=[_item(r, locale) for r in advice.reasons],
        uncertainties=[_item(u, locale) for u in advice.uncertainties],
        horizon_text=horizon_text,
        no_mounted=no_mounted,
        direction=advice.direction.value,
    )


def mounted_set(sets: list[TireSetOut]) -> TireSetOut | None:
    return next((s for s in sets if s.status == TireStatus.MOUNTED), None)


def set_label(s: TireSetOut, tr: Tr) -> str:
    parts = [tr(f"tire.type.{s.type.value}"), s.brand, s.model, s.size]
    return " ".join(p for p in parts if p)


def last_weather(
    session: Session, vehicle_id: int, infos: list[ProviderInfo], locale: str, tz: ZoneInfo
) -> dict | None:
    row = session.execute(
        select(ForecastSnapshot.fetched_at, ForecastSnapshot.provider)
        .join(AdviceSnapshot, AdviceSnapshot.forecast_snapshot_id == ForecastSnapshot.id)
        .where(AdviceSnapshot.vehicle_id == vehicle_id)
        .order_by(AdviceSnapshot.evaluated_at.desc(), AdviceSnapshot.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    info = provider_map(infos).get(row.provider)
    fetched = row.fetched_at
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    return {
        "at": format_datetime(fetched.astimezone(tz), locale),
        "source": info.name if info else row.provider,
        "attribution": info.attribution if info else None,
    }


def appointment_view(
    a: AppointmentOut, garages: dict[int, GarageOut], locale: str, tz: ZoneInfo
) -> dict:
    tr = make_tr(locale)
    g = garages.get(a.garage_id)
    return {
        "id": a.id,
        "status": a.status.value,
        "status_text": tr(f"appointment.status.{a.status.value}"),
        "garage": g,
        "garage_name": g.name if g else "",
        "direction": tr(f"direction.{a.target_direction.value}"),
        "period": (
            f"{format_date(a.target_period_start, locale)} – {format_date(a.target_period_end, locale)}"
            if a.target_period_start and a.target_period_end
            else (format_date(a.target_period_start, locale) if a.target_period_start else "")
        ),
        "at": format_datetime(a.appointment_at.astimezone(tz), locale) if a.appointment_at else "",
        "notes": a.notes,
        "next_statuses": [
            (s.value, tr(f"appointment.status.{s.value}"))
            for s in AppointmentStatus
            if s in APPOINTMENT_TRANSITIONS[a.status]
        ],
    }


def next_appointment(
    session: Session, vehicle_id: int, locale: str, tz: ZoneInfo, now: datetime
) -> dict | None:
    appts = [a for a in list_appointments(session, vehicle_id) if a.status in ACTIVE_APPOINTMENTS]
    if not appts:
        return None

    def sort_key(a: AppointmentOut) -> tuple:
        has_at = a.status == AppointmentStatus.CONFIRMED and a.appointment_at is not None
        upcoming = has_at and a.appointment_at >= now  # type: ignore[operator]
        return (0 if upcoming else 1, a.appointment_at or datetime.max.replace(tzinfo=UTC), a.id)

    best = sorted(appts, key=sort_key)[0]
    garages = {g.id: g for g in list_garages(session)}
    return appointment_view(best, garages, locale, tz)


def profile_summary(profile: DrivingProfile, locale: str) -> str:
    tr = make_tr(locale)
    if profile.kind != ProfileKind.CUSTOM:
        return tr(f"profile.{profile.kind.value}")
    if not profile.slots:
        return tr("profile.custom")
    by_day: dict[int, list[str]] = {}
    for s in profile.slots:
        by_day.setdefault(s.weekday, []).append(f"{s.start:%H:%M}–{s.end:%H:%M}")
    days = [f"{tr(f'weekday.short.{d}')} {', '.join(v)}" for d, v in sorted(by_day.items())]
    return tr("profile.custom") + ": " + "; ".join(days)


def tire_set_rows(session: Session, vehicle_id: int, locale: str) -> list[dict]:
    tr = make_tr(locale)
    rows = []
    for s in list_tire_sets(session, vehicle_id):
        km = km_per_set(session, s.id)
        latest: dict[str, tuple] = {}
        for m in list_tread_measurements(session, s.id):
            latest[m.position.value] = (m.measured_at, m.depth_mm)
        dates = {d for d, _ in latest.values()}
        rows.append(
            {
                "set": s,
                "label": set_label(s, tr),
                "type_text": tr(f"tire.type.{s.type.value}"),
                "status_text": tr(f"tire.status.{s.status.value}"),
                "km": km,
                "tread": {p: f"{v:.1f}".replace(".", ",") for p, (_, v) in latest.items()},
                "tread_date": max(dates) if dates else None,
            }
        )
    return rows


def _final_km(readings: dict[int, OdometerOut], reading_id: int | None) -> int | None:
    seen: set[int] = set()
    r = readings.get(reading_id) if reading_id is not None else None
    while r is not None and r.superseded_by_id is not None and r.id not in seen:
        seen.add(r.id)
        r = readings.get(r.superseded_by_id)
    return r.reading_km if r else None


def change_rows(
    session: Session,
    vehicle_id: int,
    sets: list[TireSetOut],
    garages: dict[int, GarageOut],
    locale: str,
) -> list[dict]:
    tr = make_tr(locale)
    by_id = {s.id: s for s in sets}
    readings = {r.id: r for r in list_odometer_readings(session, vehicle_id, True)}
    out = []
    for c in reversed(list_tire_changes(session, vehicle_id)):
        g = garages.get(c.garage_id) if c.garage_id else None
        out.append(
            {
                "date": c.changed_at,
                "from": set_label(by_id[c.from_set_id], tr) if c.from_set_id in by_id else None,
                "to": set_label(by_id[c.to_set_id], tr) if c.to_set_id in by_id else "",
                "km": _final_km(readings, c.odometer_reading_id),
                "by": tr(f"method.{c.performed_by.value}"),
                "garage": g.name if g else None,
                "cost_cents": c.cost_cents,
                "notes": c.notes,
            }
        )
    return out


def valid_types() -> list[str]:
    return [x.value for x in TireType]
