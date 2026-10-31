"""Bandensets, metingen, wissels en kilometerstanden onder /api/v1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from wisselweer.api.deps import get_session
from wisselweer.api.schemas import OdometerCorrectionIn, OdometerIn, TireChangeIn
from wisselweer.tires import service
from wisselweer.tires.schemas import (
    KmSummary,
    OdometerOut,
    TireChangeOut,
    TireSetIn,
    TireSetOut,
    TireSetPatch,
    TreadMeasurementIn,
    TreadMeasurementOut,
)
from wisselweer.vehicles import service as vehicle_service

router = APIRouter(prefix="/api/v1", tags=["tires"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/vehicles/{vehicle_id}/tire-sets", response_model=list[TireSetOut])
def list_tire_sets(vehicle_id: int, session: SessionDep) -> list[TireSetOut]:
    vehicle_service.get_vehicle(session, vehicle_id)  # 404 bij onbekend voertuig
    return service.list_tire_sets(session, vehicle_id)


@router.post("/vehicles/{vehicle_id}/tire-sets", response_model=TireSetOut, status_code=201)
def create_tire_set(vehicle_id: int, body: TireSetIn, session: SessionDep) -> TireSetOut:
    return service.create_tire_set(session, vehicle_id, body)


@router.get("/tire-sets/{set_id}", response_model=TireSetOut)
def get_tire_set(set_id: int, session: SessionDep) -> TireSetOut:
    return service.get_tire_set(session, set_id)


@router.patch("/tire-sets/{set_id}", response_model=TireSetOut)
def update_tire_set(set_id: int, body: TireSetPatch, session: SessionDep) -> TireSetOut:
    return service.update_tire_set(session, set_id, body)


@router.delete("/tire-sets/{set_id}", status_code=204)
def delete_tire_set(set_id: int, session: SessionDep) -> Response:
    service.delete_tire_set(session, set_id)
    return Response(status_code=204)


@router.post(
    "/tire-sets/{set_id}/tread-measurements",
    response_model=TreadMeasurementOut,
    status_code=201,
)
def add_tread_measurement(
    set_id: int, body: TreadMeasurementIn, session: SessionDep
) -> TreadMeasurementOut:
    return service.add_tread_measurement(session, set_id, body)


@router.get("/tire-sets/{set_id}/km", response_model=KmSummary)
def tire_set_km(set_id: int, session: SessionDep) -> KmSummary:
    return service.km_per_set(session, set_id)


@router.get("/vehicles/{vehicle_id}/tire-changes", response_model=list[TireChangeOut])
def list_tire_changes(vehicle_id: int, session: SessionDep) -> list[TireChangeOut]:
    vehicle_service.get_vehicle(session, vehicle_id)
    return service.list_tire_changes(session, vehicle_id)


@router.post("/vehicles/{vehicle_id}/tire-changes", response_model=TireChangeOut, status_code=201)
def register_tire_change(vehicle_id: int, body: TireChangeIn, session: SessionDep) -> TireChangeOut:
    return service.register_tire_change(
        session,
        vehicle_id,
        body.to_set_id,
        body.changed_at,
        odometer_km=body.odometer_km,
        performed_by=body.performed_by,
        garage_id=body.garage_id,
        cost_cents=body.cost_cents,
        notes=body.notes,
        allow_lower_odometer=body.allow_lower_odometer,
    )


@router.get("/vehicles/{vehicle_id}/odometer", response_model=list[OdometerOut])
def list_odometer(
    vehicle_id: int, session: SessionDep, include_superseded: bool = False
) -> list[OdometerOut]:
    vehicle_service.get_vehicle(session, vehicle_id)
    return service.list_odometer_readings(session, vehicle_id, include_superseded)


@router.post("/odometer/{reading_id}/correct", response_model=OdometerOut)
def correct_odometer(
    reading_id: int, body: OdometerCorrectionIn, session: SessionDep
) -> OdometerOut:
    return service.correct_odometer(session, reading_id, body.new_km, body.note)


@router.post("/vehicles/{vehicle_id}/odometer", response_model=OdometerOut, status_code=201)
def add_odometer(vehicle_id: int, body: OdometerIn, session: SessionDep) -> OdometerOut:
    recorded_at = body.recorded_at or datetime.now(UTC)
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=UTC)
    return service.add_odometer_reading(
        session, vehicle_id, body.reading_km, recorded_at, body.note
    )
