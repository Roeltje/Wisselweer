"""Garages en afspraken (statusmachine), plus mailto-link (geen verzending)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from urllib.parse import quote

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from wisselweer.core.models import Advice, Direction
from wisselweer.garages.schemas import (
    AppointmentIn,
    AppointmentOut,
    GarageIn,
    GarageOut,
    GaragePatch,
)
from wisselweer.storage.enums import APPOINTMENT_TRANSITIONS, AppointmentStatus
from wisselweer.storage.errors import InvalidOperation, NotFoundError
from wisselweer.storage.orm import Appointment, Garage, TireChange, Vehicle
from wisselweer.vehicles.schemas import VehicleOut


def _garage(session: Session, garage_id: int) -> Garage:
    g = session.get(Garage, garage_id)
    if g is None:
        raise NotFoundError("garage niet gevonden")
    return g


def _g_out(g: Garage) -> GarageOut:
    return GarageOut(
        id=g.id,
        name=g.name,
        address=g.address,
        phone=g.phone,
        email=g.email,
        website=g.website,
        notes=g.notes,
        lead_time_days=g.lead_time_days,
    )


def create_garage(session: Session, data: GarageIn) -> GarageOut:
    g = Garage(**data.model_dump())
    session.add(g)
    session.flush()
    return _g_out(g)


def get_garage(session: Session, garage_id: int) -> GarageOut:
    return _g_out(_garage(session, garage_id))


def list_garages(session: Session) -> list[GarageOut]:
    return [_g_out(g) for g in session.scalars(select(Garage).order_by(Garage.id))]


def update_garage(session: Session, garage_id: int, patch: GaragePatch) -> GarageOut:
    g = _garage(session, garage_id)
    for k, val in patch.model_dump(exclude_unset=True).items():
        if val is None and k in ("name", "lead_time_days"):
            raise InvalidOperation(f"{k} mag niet leeg zijn")
        setattr(g, k, val)
    session.flush()
    return _g_out(g)


def delete_garage(session: Session, garage_id: int) -> None:
    g = _garage(session, garage_id)
    if session.scalar(select(Appointment.id).where(Appointment.garage_id == garage_id).limit(1)):
        raise InvalidOperation("garage heeft afspraken en kan niet verwijderd worden")
    session.execute(
        update(Vehicle)
        .where(Vehicle.preferred_garage_id == garage_id)
        .values(preferred_garage_id=None)
    )
    session.execute(
        update(TireChange).where(TireChange.garage_id == garage_id).values(garage_id=None)
    )
    session.delete(g)
    session.flush()


# --- Afspraken --------------------------------------------------------------------------


def _appt(session: Session, appointment_id: int) -> Appointment:
    a = session.get(Appointment, appointment_id)
    if a is None:
        raise NotFoundError("afspraak niet gevonden")
    return a


def _a_out(a: Appointment) -> AppointmentOut:
    return AppointmentOut(
        id=a.id,
        vehicle_id=a.vehicle_id,
        garage_id=a.garage_id,
        target_direction=a.target_direction,
        target_period_start=a.target_period_start,
        target_period_end=a.target_period_end,
        notes=a.notes,
        status=a.status,
        appointment_at=a.appointment_at,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def create_appointment(session: Session, data: AppointmentIn) -> AppointmentOut:
    if session.get(Vehicle, data.vehicle_id) is None:
        raise NotFoundError("voertuig niet gevonden")
    _garage(session, data.garage_id)
    if (
        data.target_period_start
        and data.target_period_end
        and data.target_period_end < data.target_period_start
    ):
        raise InvalidOperation("periode-einde ligt voor het begin")
    now = datetime.now(UTC)
    a = Appointment(
        **data.model_dump(),
        status=AppointmentStatus.NOT_PLANNED,
        created_at=now,
        updated_at=now,
    )
    session.add(a)
    session.flush()
    return _a_out(a)


def get_appointment(session: Session, appointment_id: int) -> AppointmentOut:
    return _a_out(_appt(session, appointment_id))


def list_appointments(session: Session, vehicle_id: int | None = None) -> list[AppointmentOut]:
    q = select(Appointment).order_by(Appointment.id)
    if vehicle_id is not None:
        q = q.where(Appointment.vehicle_id == vehicle_id)
    return [_a_out(a) for a in session.scalars(q)]


def set_appointment_status(
    session: Session,
    appointment_id: int,
    new_status: AppointmentStatus,
    appointment_at: datetime | None = None,
) -> AppointmentOut:
    a = _appt(session, appointment_id)
    if new_status not in APPOINTMENT_TRANSITIONS[a.status]:
        raise InvalidOperation(
            f"overgang {a.status.value} -> {new_status.value} is niet toegestaan"
        )
    if new_status == AppointmentStatus.CONFIRMED:
        if appointment_at is None and a.appointment_at is None:
            raise InvalidOperation("een bevestigde afspraak heeft een tijdstip nodig")
    if appointment_at is not None:
        a.appointment_at = appointment_at
    a.status = new_status
    a.updated_at = datetime.now(UTC)
    session.flush()
    return _a_out(a)


# --- mailto -----------------------------------------------------------------------------

_DIRECTION_TEXT = {
    Direction.TO_WINTER: "van zomer- naar winterbanden",
    Direction.TO_SUMMER: "van winter- naar zomerbanden",
}


def _fmt(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def mailto_link(vehicle: VehicleOut, garage: GarageOut, advice: Advice | None = None) -> str:
    """Bouwt een `mailto:`-URL (alleen een link; er wordt niets verzonden)."""
    if not garage.email:
        raise InvalidOperation("garage heeft geen e-mailadres")
    direction = advice.direction if advice else Direction.NONE
    wissel = _DIRECTION_TEXT.get(direction, "bandenwissel")
    period = None
    if advice:
        if advice.recommended_period:
            a, b = advice.recommended_period
            period = f"tussen {_fmt(a)} en {_fmt(b)}"
        elif advice.recommended_date:
            period = f"rond {_fmt(advice.recommended_date)}"
        elif advice.plan_appointment_by:
            period = f"uiterlijk rond {_fmt(advice.plan_appointment_by)}"
    subject = f"Afspraak bandenwissel {vehicle.name}"
    lines = [f"Beste {garage.name},", ""]
    lines.append(f"Graag maak ik een afspraak voor het wisselen {wissel}.")
    lines.append(f"Voertuig: {vehicle.name}")
    if vehicle.license_plate:
        lines.append(f"Kenteken: {vehicle.license_plate}")
    if period:
        lines.append(f"Voorgestelde periode: {period}")
    lines += [
        "",
        "Kunt u mij laten weten welke momenten beschikbaar zijn?",
        "",
        "Met vriendelijke groet",
    ]
    body = "\r\n".join(lines)
    return (
        f"mailto:{quote(garage.email, safe='@')}"
        f"?subject={quote(subject, safe='')}&body={quote(body, safe='')}"
    )
