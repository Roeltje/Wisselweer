"""Banden: sets, metingen, wissels en kilometerstanden.

De functies committen niet zelf; de aanroeper (bv. `session_scope`) doet dat. Een wissel
draait binnen een SAVEPOINT zodat een fout midden in de wissel niets half achterlaat.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from wisselweer.storage.enums import ChangeMethod, OdometerSource, TireStatus
from wisselweer.storage.errors import InvalidOperation, NotFoundError
from wisselweer.storage.orm import (
    AdviceSnapshot,
    Garage,
    OdometerReading,
    TireChange,
    TireSet,
    TreadMeasurement,
    Vehicle,
)
from wisselweer.tires.schemas import (
    KmInterval,
    KmSummary,
    OdometerOut,
    TireChangeOut,
    TireSetIn,
    TireSetOut,
    TireSetPatch,
    TreadMeasurementIn,
    TreadMeasurementOut,
)


def _vehicle(session: Session, vehicle_id: int) -> Vehicle:
    v = session.get(Vehicle, vehicle_id)
    if v is None:
        raise NotFoundError("voertuig niet gevonden")
    return v


def _set(session: Session, set_id: int) -> TireSet:
    s = session.get(TireSet, set_id)
    if s is None:
        raise NotFoundError("bandenset niet gevonden")
    return s


def _set_out(s: TireSet) -> TireSetOut:
    return TireSetOut(
        id=s.id,
        vehicle_id=s.vehicle_id,
        type=s.type,
        brand=s.brand,
        model=s.model,
        size=s.size,
        purchase_date=s.purchase_date,
        purchase_price_cents=s.purchase_price_cents,
        dot_code=s.dot_code,
        notes=s.notes,
        status=s.status,
        created_at=s.created_at,
    )


def _mounted_set(session: Session, vehicle_id: int) -> TireSet | None:
    return session.scalar(
        select(TireSet).where(
            TireSet.vehicle_id == vehicle_id, TireSet.status == TireStatus.MOUNTED
        )
    )


# --- Sets -------------------------------------------------------------------------------


def create_tire_set(session: Session, vehicle_id: int, data: TireSetIn) -> TireSetOut:
    _vehicle(session, vehicle_id)
    if data.status == TireStatus.MOUNTED and _mounted_set(session, vehicle_id) is not None:
        raise InvalidOperation("er is al een gemonteerde set; gebruik een bandenwissel")
    s = TireSet(vehicle_id=vehicle_id, **data.model_dump())
    session.add(s)
    session.flush()
    return _set_out(s)


def get_tire_set(session: Session, set_id: int) -> TireSetOut:
    return _set_out(_set(session, set_id))


def list_tire_sets(session: Session, vehicle_id: int) -> list[TireSetOut]:
    rows = session.scalars(
        select(TireSet).where(TireSet.vehicle_id == vehicle_id).order_by(TireSet.id)
    )
    return [_set_out(s) for s in rows]


def update_tire_set(session: Session, set_id: int, patch: TireSetPatch) -> TireSetOut:
    s = _set(session, set_id)
    changes = patch.model_dump(exclude_unset=True)
    for non_null in ("type", "status"):
        if non_null in changes and changes[non_null] is None:
            raise InvalidOperation(f"{non_null} mag niet leeg zijn")
    new_status = changes.get("status")
    if new_status == TireStatus.MOUNTED and s.status != TireStatus.MOUNTED:
        raise InvalidOperation("monteren gaat via een bandenwissel")
    for k, val in changes.items():
        setattr(s, k, val)
    session.flush()
    return _set_out(s)


def delete_tire_set(session: Session, set_id: int) -> None:
    """Verwijdert een set met metingen; niet als hij gemonteerd is of in de wisselhistorie staat."""
    s = _set(session, set_id)
    if s.status == TireStatus.MOUNTED:
        raise InvalidOperation("een gemonteerde set kan niet verwijderd worden")
    in_history = session.scalar(
        select(TireChange.id)
        .where((TireChange.to_set_id == set_id) | (TireChange.from_set_id == set_id))
        .limit(1)
    )
    if in_history is not None:
        raise InvalidOperation("set staat in de wisselhistorie; zet de status op 'retired'")
    session.execute(delete(TreadMeasurement).where(TreadMeasurement.tire_set_id == set_id))
    session.delete(s)
    session.flush()


def add_tread_measurement(
    session: Session, set_id: int, data: TreadMeasurementIn
) -> TreadMeasurementOut:
    _set(session, set_id)
    m = TreadMeasurement(tire_set_id=set_id, **data.model_dump())
    session.add(m)
    session.flush()
    return TreadMeasurementOut(id=m.id, tire_set_id=set_id, **data.model_dump())


def list_tread_measurements(session: Session, set_id: int) -> list[TreadMeasurementOut]:
    rows = session.scalars(
        select(TreadMeasurement)
        .where(TreadMeasurement.tire_set_id == set_id)
        .order_by(TreadMeasurement.measured_at, TreadMeasurement.id)
    )
    return [
        TreadMeasurementOut(
            id=m.id,
            tire_set_id=m.tire_set_id,
            measured_at=m.measured_at,
            position=m.position,
            depth_mm=m.depth_mm,
        )
        for m in rows
    ]


# --- Kilometerstanden -------------------------------------------------------------------


def _reading_out(r: OdometerReading) -> OdometerOut:
    return OdometerOut(
        id=r.id,
        vehicle_id=r.vehicle_id,
        reading_km=r.reading_km,
        recorded_at=r.recorded_at,
        source=r.source,
        superseded_by_id=r.superseded_by_id,
        note=r.note,
    )


def _resolve(session: Session, reading: OdometerReading | None) -> OdometerReading | None:
    """Volgt de correctieketen naar de geldige stand."""
    seen: set[int] = set()
    while reading is not None and reading.superseded_by_id is not None:
        if reading.id in seen:
            raise InvalidOperation("cyclische correctieketen")
        seen.add(reading.id)
        reading = session.get(OdometerReading, reading.superseded_by_id)
    return reading


def _valid_readings(session: Session, vehicle_id: int) -> list[OdometerReading]:
    return list(
        session.scalars(
            select(OdometerReading)
            .where(
                OdometerReading.vehicle_id == vehicle_id,
                OdometerReading.superseded_by_id.is_(None),
            )
            .order_by(OdometerReading.recorded_at, OdometerReading.id)
        )
    )


def _check_monotonic(session: Session, vehicle_id: int, when: datetime, km: int) -> None:
    for r in _valid_readings(session, vehicle_id):
        if (r.recorded_at <= when and r.reading_km > km) or (
            r.recorded_at > when and r.reading_km < km
        ):
            raise InvalidOperation("kilometerstand past niet bij de bestaande standen")


def add_odometer_reading(
    session: Session,
    vehicle_id: int,
    reading_km: int,
    recorded_at: datetime,
    note: str | None = None,
) -> OdometerOut:
    """Handmatige stand; moet monotoon passen bij de geldige standen."""
    _vehicle(session, vehicle_id)
    if reading_km < 0:
        raise InvalidOperation("kilometerstand mag niet negatief zijn")
    _check_monotonic(session, vehicle_id, recorded_at, reading_km)
    r = OdometerReading(
        vehicle_id=vehicle_id,
        reading_km=reading_km,
        recorded_at=recorded_at,
        source=OdometerSource.MANUAL,
        note=note,
    )
    session.add(r)
    session.flush()
    return _reading_out(r)


def correct_odometer(
    session: Session, reading_id: int, new_km: int, note: str | None = None
) -> OdometerOut:
    """Correctie = nieuwe rij; de oude verwijst ernaar. Nooit verwijderen."""
    old = session.get(OdometerReading, reading_id)
    if old is None:
        raise NotFoundError("kilometerstand niet gevonden")
    if old.superseded_by_id is not None:
        raise InvalidOperation("deze stand is al gecorrigeerd; corrigeer de geldige stand")
    if new_km < 0:
        raise InvalidOperation("kilometerstand mag niet negatief zijn")
    new = OdometerReading(
        vehicle_id=old.vehicle_id,
        reading_km=new_km,
        recorded_at=old.recorded_at,
        source=old.source,
        note=note,
    )
    session.add(new)
    session.flush()
    old.superseded_by_id = new.id
    session.flush()
    return _reading_out(new)


def list_odometer_readings(
    session: Session, vehicle_id: int, include_superseded: bool = False
) -> list[OdometerOut]:
    q = select(OdometerReading).where(OdometerReading.vehicle_id == vehicle_id)
    if not include_superseded:
        q = q.where(OdometerReading.superseded_by_id.is_(None))
    q = q.order_by(OdometerReading.recorded_at, OdometerReading.id)
    return [_reading_out(r) for r in session.scalars(q)]


# --- Bandenwissel -----------------------------------------------------------------------


def _invalidate_advice(session: Session, vehicle_id: int, now: datetime) -> None:
    """Reset van de hysterese: bestaande snapshots tellen niet meer als `previous`."""
    session.execute(
        update(AdviceSnapshot)
        .where(AdviceSnapshot.vehicle_id == vehicle_id, AdviceSnapshot.invalidated_at.is_(None))
        .values(invalidated_at=now)
    )


def register_tire_change(
    session: Session,
    vehicle_id: int,
    to_set_id: int,
    changed_at: date,
    *,
    odometer_km: int | None = None,
    performed_by: ChangeMethod = ChangeMethod.SELF,
    garage_id: int | None = None,
    cost_cents: int | None = None,
    notes: str | None = None,
    allow_lower_odometer: bool = False,
    today: date | None = None,
) -> TireChangeOut:
    """Registreert een wissel atomair (SAVEPOINT): stand, historie, setstatussen, advies-reset."""
    today = today or datetime.now(UTC).date()
    with session.begin_nested():
        _vehicle(session, vehicle_id)
        to_set = _set(session, to_set_id)
        if to_set.vehicle_id != vehicle_id:
            raise InvalidOperation("bandenset hoort niet bij dit voertuig")
        if to_set.status == TireStatus.RETIRED:
            raise InvalidOperation("een afgeschreven set kan niet gemonteerd worden")
        if to_set.status == TireStatus.MOUNTED:
            raise InvalidOperation("deze set is al gemonteerd")
        if changed_at > today:
            raise InvalidOperation("wisseldatum ligt in de toekomst")
        if garage_id is not None and session.get(Garage, garage_id) is None:
            raise NotFoundError("garage niet gevonden")
        if odometer_km is not None and odometer_km < 0:
            raise InvalidOperation("kilometerstand mag niet negatief zijn")

        when = datetime.combine(changed_at, time.min, tzinfo=UTC)
        reading: OdometerReading | None = None
        if odometer_km is not None:
            if not allow_lower_odometer:
                _check_monotonic(session, vehicle_id, when, odometer_km)
            reading = OdometerReading(
                vehicle_id=vehicle_id,
                reading_km=odometer_km,
                recorded_at=when,
                source=OdometerSource.TIRE_CHANGE,
            )
            session.add(reading)
            session.flush()

        from_set = _mounted_set(session, vehicle_id)
        if from_set is not None:
            from_set.status = TireStatus.STORED
            session.flush()  # eerst vrijgeven vanwege de partiële unieke index
        to_set.status = TireStatus.MOUNTED
        change = TireChange(
            vehicle_id=vehicle_id,
            changed_at=changed_at,
            odometer_reading_id=reading.id if reading else None,
            from_set_id=from_set.id if from_set else None,
            to_set_id=to_set.id,
            performed_by=performed_by,
            garage_id=garage_id,
            cost_cents=cost_cents,
            notes=notes,
        )
        session.add(change)
        session.flush()
        _invalidate_advice(session, vehicle_id, datetime.now(UTC))
        return _change_out(change)


def _change_out(c: TireChange) -> TireChangeOut:
    return TireChangeOut(
        id=c.id,
        vehicle_id=c.vehicle_id,
        changed_at=c.changed_at,
        odometer_reading_id=c.odometer_reading_id,
        from_set_id=c.from_set_id,
        to_set_id=c.to_set_id,
        performed_by=c.performed_by,
        garage_id=c.garage_id,
        cost_cents=c.cost_cents,
        notes=c.notes,
    )


def list_tire_changes(session: Session, vehicle_id: int) -> list[TireChangeOut]:
    rows = session.scalars(
        select(TireChange)
        .where(TireChange.vehicle_id == vehicle_id)
        .order_by(TireChange.changed_at, TireChange.id)
    )
    return [_change_out(c) for c in rows]


# --- Kilometers per set -----------------------------------------------------------------


def km_per_set(session: Session, set_id: int) -> KmSummary:
    """Km per montage-interval uit geldige standen; onbekend/negatief => interval onbekend."""
    s = _set(session, set_id)
    changes = list(
        session.scalars(
            select(TireChange)
            .where((TireChange.to_set_id == set_id) | (TireChange.from_set_id == set_id))
            .order_by(TireChange.changed_at, TireChange.id)
        )
    )

    def km_of(change: TireChange | None) -> int | None:
        if change is None or change.odometer_reading_id is None:
            return None
        r = _resolve(session, session.get(OdometerReading, change.odometer_reading_id))
        return r.reading_km if r else None

    latest = _valid_readings(session, s.vehicle_id)
    latest_km = latest[-1].reading_km if latest else None

    # Elke wissel kan voor deze set zowel demontage (from) als montage (to) zijn.
    spans: list[tuple[TireChange | None, TireChange | None]] = []
    open_start: TireChange | None = None
    is_open = False
    for c in changes:
        if c.from_set_id == set_id and c.to_set_id != set_id:
            spans.append((open_start if is_open else None, c))
            is_open, open_start = False, None
        elif c.to_set_id == set_id:
            if is_open:  # twee montages achter elkaar: eerste is niet af te sluiten
                spans.append((open_start, None))
            is_open, open_start = True, c
    still_open = is_open
    if is_open:
        spans.append((open_start, None))
    elif s.status == TireStatus.MOUNTED:
        spans.append((None, None))  # gemonteerd zonder vastgelegde montage
        still_open = True

    intervals: list[KmInterval] = []
    for i, (start, end) in enumerate(spans):
        start_km = km_of(start)
        is_last_open = end is None and still_open and i == len(spans) - 1
        end_km = km_of(end) if end is not None else (latest_km if is_last_open else None)
        km: int | None = None
        if start_km is not None and end_km is not None and end_km >= start_km:
            km = end_km - start_km
        intervals.append(
            KmInterval(
                start_change_id=start.id if start else None,
                end_change_id=end.id if end else None,
                start_date=start.changed_at if start else None,
                end_date=end.changed_at if end else None,
                start_km=start_km,
                end_km=end_km,
                km=km,
            )
        )
    known = [i.km for i in intervals if i.km is not None]
    return KmSummary(
        known_km=sum(known) if known else None,
        complete=bool(intervals) and len(known) == len(intervals),
        intervals=intervals,
    )
