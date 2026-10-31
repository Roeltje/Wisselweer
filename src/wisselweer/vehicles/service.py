"""Voertuigen: CRUD en locatiehergebruik."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from wisselweer.core.models import DrivingProfile
from wisselweer.storage.errors import InvalidOperation, NotFoundError
from wisselweer.storage.orm import (
    AdviceSnapshot,
    Appointment,
    Garage,
    Location,
    OdometerReading,
    TireChange,
    TireSet,
    TreadMeasurement,
    Vehicle,
)
from wisselweer.vehicles.schemas import (
    LocationIn,
    LocationOut,
    VehicleIn,
    VehicleOut,
    VehiclePatch,
)


def normalize_plate(plate: str | None) -> str | None:
    if plate is None:
        return None
    norm = re.sub(r"[^A-Za-z0-9]", "", plate).upper()
    return norm or None


def get_or_create_location(session: Session, data: LocationIn) -> Location:
    """Zelfde lat/lon afgerond op 4 decimalen => hergebruik (één forecast-fetch per locatie)."""
    lat, lon = round(data.latitude, 4), round(data.longitude, 4)
    loc = session.scalar(
        select(Location).where(Location.latitude == lat, Location.longitude == lon)
    )
    if loc is None:
        loc = Location(name=data.name, latitude=lat, longitude=lon, timezone=data.timezone)
        session.add(loc)
        session.flush()
    return loc


def _out(session: Session, v: Vehicle) -> VehicleOut:
    loc = session.get(Location, v.location_id)
    assert loc is not None
    return VehicleOut(
        id=v.id,
        name=v.name,
        make=v.make,
        model=v.model,
        license_plate=v.license_plate_display,
        license_plate_normalized=v.license_plate,
        build_year=v.build_year,
        location=LocationOut(
            id=loc.id,
            name=loc.name,
            latitude=loc.latitude,
            longitude=loc.longitude,
            timezone=loc.timezone,
        ),
        timezone=v.timezone,
        driving_profile=DrivingProfile.model_validate(v.driving_profile),
        change_method=v.change_method,
        preferred_garage_id=v.preferred_garage_id,
        prep_days=v.prep_days,
        notes=v.notes,
        countries_of_use=list(v.countries_of_use),
        plate_lookup_data=v.plate_lookup_data,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def _check_garage(session: Session, garage_id: int | None) -> None:
    if garage_id is not None and session.get(Garage, garage_id) is None:
        raise NotFoundError("garage niet gevonden")


def _display_plate(plate: str | None) -> str | None:
    return plate.strip().upper() if plate and plate.strip() else None


def create_vehicle(session: Session, data: VehicleIn) -> VehicleOut:
    _check_garage(session, data.preferred_garage_id)
    loc = get_or_create_location(session, data.location)
    now = datetime.now(UTC)
    v = Vehicle(
        name=data.name,
        make=data.make,
        model=data.model,
        license_plate=normalize_plate(data.license_plate),
        license_plate_display=_display_plate(data.license_plate),
        build_year=data.build_year,
        location_id=loc.id,
        timezone=data.timezone,
        driving_profile=data.driving_profile.model_dump(mode="json"),
        change_method=data.change_method,
        preferred_garage_id=data.preferred_garage_id,
        prep_days=data.prep_days,
        notes=data.notes,
        countries_of_use=list(data.countries_of_use),
        plate_lookup_data=data.plate_lookup_data,
        created_at=now,
        updated_at=now,
    )
    session.add(v)
    session.flush()
    return _out(session, v)


def _get(session: Session, vehicle_id: int) -> Vehicle:
    v = session.get(Vehicle, vehicle_id)
    if v is None:
        raise NotFoundError("voertuig niet gevonden")
    return v


def get_vehicle(session: Session, vehicle_id: int) -> VehicleOut:
    return _out(session, _get(session, vehicle_id))


def list_vehicles(session: Session) -> list[VehicleOut]:
    rows = session.scalars(select(Vehicle).order_by(Vehicle.id)).all()
    return [_out(session, v) for v in rows]


def update_vehicle(session: Session, vehicle_id: int, patch: VehiclePatch) -> VehicleOut:
    v = _get(session, vehicle_id)
    fields = patch.model_fields_set
    plain: dict[str, Any] = {}
    for name in (
        "name",
        "make",
        "model",
        "build_year",
        "timezone",
        "change_method",
        "preferred_garage_id",
        "prep_days",
        "notes",
        "countries_of_use",
        "plate_lookup_data",
    ):
        if name in fields:
            plain[name] = getattr(patch, name)
    for non_nullable in ("name", "timezone", "change_method", "prep_days", "countries_of_use"):
        if non_nullable in plain and plain[non_nullable] is None:
            raise InvalidOperation(f"{non_nullable} mag niet leeg zijn")
    if "preferred_garage_id" in plain:
        _check_garage(session, plain["preferred_garage_id"])
    for k, val in plain.items():
        setattr(v, k, val)
    if "license_plate" in fields:
        v.license_plate = normalize_plate(patch.license_plate)
        v.license_plate_display = _display_plate(patch.license_plate)
    if "driving_profile" in fields:
        if patch.driving_profile is None:
            raise InvalidOperation("driving_profile mag niet leeg zijn")
        v.driving_profile = patch.driving_profile.model_dump(mode="json")
    if "location" in fields:
        if patch.location is None:
            raise InvalidOperation("location mag niet leeg zijn")
        v.location_id = get_or_create_location(session, patch.location).id
    v.updated_at = datetime.now(UTC)
    session.flush()
    return _out(session, v)


def delete_vehicle(session: Session, vehicle_id: int) -> None:
    """Verwijdert het voertuig en expliciet alle bijbehorende sets en historie."""
    v = _get(session, vehicle_id)
    set_ids = list(session.scalars(select(TireSet.id).where(TireSet.vehicle_id == vehicle_id)))
    session.execute(delete(TireChange).where(TireChange.vehicle_id == vehicle_id))
    session.execute(
        update(OdometerReading)
        .where(OdometerReading.vehicle_id == vehicle_id)
        .values(superseded_by_id=None)
    )
    session.execute(delete(OdometerReading).where(OdometerReading.vehicle_id == vehicle_id))
    if set_ids:
        session.execute(delete(TreadMeasurement).where(TreadMeasurement.tire_set_id.in_(set_ids)))
    session.execute(delete(TireSet).where(TireSet.vehicle_id == vehicle_id))
    session.execute(delete(Appointment).where(Appointment.vehicle_id == vehicle_id))
    session.execute(delete(AdviceSnapshot).where(AdviceSnapshot.vehicle_id == vehicle_id))
    session.delete(v)
    session.flush()
