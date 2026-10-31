"""Voertuigen en advies per voertuig onder /api/v1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from wisselweer.api.deps import get_advice_service, get_forecast_service, get_session
from wisselweer.api.schemas import VehicleAdviceResponse, build_messages, build_source
from wisselweer.garages import service as garage_service
from wisselweer.storage.enums import ChangeMethod
from wisselweer.vehicles import service
from wisselweer.vehicles.advice import VehicleAdviceService
from wisselweer.vehicles.schemas import VehicleIn, VehicleOut, VehiclePatch

router = APIRouter(prefix="/api/v1", tags=["vehicles"])

SessionDep = Annotated[Session, Depends(get_session)]
AdviceServiceDep = Annotated[VehicleAdviceService, Depends(get_advice_service)]
ForecastsDep = Annotated[Any, Depends(get_forecast_service)]


@router.get("/vehicles", response_model=list[VehicleOut])
def list_vehicles(session: SessionDep) -> list[VehicleOut]:
    return service.list_vehicles(session)


@router.post("/vehicles", response_model=VehicleOut, status_code=201)
def create_vehicle(body: VehicleIn, session: SessionDep) -> VehicleOut:
    return service.create_vehicle(session, body)


@router.get("/vehicles/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: int, session: SessionDep) -> VehicleOut:
    return service.get_vehicle(session, vehicle_id)


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(vehicle_id: int, body: VehiclePatch, session: SessionDep) -> VehicleOut:
    return service.update_vehicle(session, vehicle_id, body)


@router.delete("/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: int, session: SessionDep) -> Response:
    service.delete_vehicle(session, vehicle_id)
    return Response(status_code=204)


@router.get("/vehicles/{vehicle_id}/advice", response_model=VehicleAdviceResponse)
def vehicle_advice(
    vehicle_id: int,
    session: SessionDep,
    advice_service: AdviceServiceDep,
    forecasts: ForecastsDep,
) -> VehicleAdviceResponse:
    # Het advies draait in een eigen transactie (snapshots); daarna lezen we met de request-sessie.
    advice = advice_service.advice_for_vehicle(vehicle_id, datetime.now(UTC))
    vehicle = service.get_vehicle(session, vehicle_id)
    mailto: str | None = None
    if vehicle.change_method == ChangeMethod.GARAGE and vehicle.preferred_garage_id is not None:
        garage = garage_service.get_garage(session, vehicle.preferred_garage_id)
        if garage.email:
            mailto = garage_service.mailto_link(vehicle, garage, advice)
    return VehicleAdviceResponse(
        advice=advice,
        messages_nl=build_messages(advice),
        source=build_source(advice.forecast_provider, forecasts.provider_infos()),
        plan_appointment_by=advice.plan_appointment_by,
        mailto=mailto,
    )
