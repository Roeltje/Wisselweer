"""Garages en afspraken onder /api/v1."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from wisselweer.api.deps import get_session
from wisselweer.api.schemas import AppointmentCreate, AppointmentStatusIn, MailtoResponse
from wisselweer.core.models import Advice
from wisselweer.garages import service
from wisselweer.garages.schemas import (
    AppointmentIn,
    AppointmentOut,
    GarageIn,
    GarageOut,
    GaragePatch,
)
from wisselweer.storage.orm import AdviceSnapshot
from wisselweer.vehicles import service as vehicle_service

router = APIRouter(prefix="/api/v1", tags=["garages"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/garages", response_model=list[GarageOut])
def list_garages(session: SessionDep) -> list[GarageOut]:
    return service.list_garages(session)


@router.post("/garages", response_model=GarageOut, status_code=201)
def create_garage(body: GarageIn, session: SessionDep) -> GarageOut:
    return service.create_garage(session, body)


@router.get("/garages/{garage_id}", response_model=GarageOut)
def get_garage(garage_id: int, session: SessionDep) -> GarageOut:
    return service.get_garage(session, garage_id)


@router.patch("/garages/{garage_id}", response_model=GarageOut)
def update_garage(garage_id: int, body: GaragePatch, session: SessionDep) -> GarageOut:
    return service.update_garage(session, garage_id, body)


@router.delete("/garages/{garage_id}", status_code=204)
def delete_garage(garage_id: int, session: SessionDep) -> Response:
    service.delete_garage(session, garage_id)
    return Response(status_code=204)


@router.get("/vehicles/{vehicle_id}/appointments", response_model=list[AppointmentOut])
def list_appointments(vehicle_id: int, session: SessionDep) -> list[AppointmentOut]:
    vehicle_service.get_vehicle(session, vehicle_id)  # 404 bij onbekend voertuig
    return service.list_appointments(session, vehicle_id)


@router.post("/vehicles/{vehicle_id}/appointments", response_model=AppointmentOut, status_code=201)
def create_appointment(
    vehicle_id: int, body: AppointmentCreate, session: SessionDep
) -> AppointmentOut:
    return service.create_appointment(
        session, AppointmentIn(vehicle_id=vehicle_id, **body.model_dump())
    )


@router.patch("/appointments/{appointment_id}", response_model=AppointmentOut)
def update_appointment_status(
    appointment_id: int, body: AppointmentStatusIn, session: SessionDep
) -> AppointmentOut:
    return service.set_appointment_status(session, appointment_id, body.status, body.appointment_at)


@router.get("/appointments/{appointment_id}/mailto", response_model=MailtoResponse)
def appointment_mailto(appointment_id: int, session: SessionDep) -> MailtoResponse:
    appt = service.get_appointment(session, appointment_id)
    vehicle = vehicle_service.get_vehicle(session, appt.vehicle_id)
    garage = service.get_garage(session, appt.garage_id)
    # Laatste geldige advies-snapshot (geen nieuwe provider-fetch); alleen als de richting klopt.
    row = session.scalar(
        select(AdviceSnapshot)
        .where(
            AdviceSnapshot.vehicle_id == appt.vehicle_id, AdviceSnapshot.invalidated_at.is_(None)
        )
        .order_by(AdviceSnapshot.evaluated_at.desc(), AdviceSnapshot.id.desc())
        .limit(1)
    )
    advice = Advice.model_validate(row.advice) if row else None
    if advice is not None and advice.direction != appt.target_direction:
        advice = None
    return MailtoResponse(mailto=service.mailto_link(vehicle, garage, advice))
