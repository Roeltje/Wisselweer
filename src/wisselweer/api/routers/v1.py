"""Routers onder /api/v1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from wisselweer import __version__
from wisselweer.api.deps import get_forecast_service, get_settings
from wisselweer.api.schemas import (
    AdviceResponse,
    CalculateRequest,
    HealthResponse,
    ProvidersResponse,
    build_messages,
    build_source,
)
from wisselweer.core import RULES_VERSION, AdviceInput, DrivingProfile, Forecast, TireType, evaluate
from wisselweer.publisher.national import NationalAdviceService
from wisselweer.publisher.public_schema import PublicAdvice
from wisselweer.settings import Settings

if TYPE_CHECKING:
    from wisselweer.weather.service import ForecastService

router = APIRouter(prefix="/api/v1")
# Health blijft openbaar (geen authenticatie), de rest van /api/v1 vereist login.
health_router = APIRouter(prefix="/api/v1")

# ForecastService wordt pas lazy geïmporteerd; tijdens runtime volstaat Any voor FastAPI.
if TYPE_CHECKING:
    ServiceDep = Annotated[ForecastService, Depends(get_forecast_service)]
else:
    ServiceDep = Annotated[Any, Depends(get_forecast_service)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _respond(
    service: ForecastService,
    forecast: Forecast,
    mounted: TireType,
    profile: DrivingProfile | None,
    lead_time_days: int,
) -> AdviceResponse:
    inp = AdviceInput(
        forecast=forecast,
        mounted=mounted,
        profile=profile or DrivingProfile.commute(),
        now=datetime.now(UTC),
        lead_time_days=lead_time_days,
    )
    advice = evaluate(inp)
    infos = service.provider_infos()
    return AdviceResponse(
        advice=advice,
        messages_nl=build_messages(advice),
        source=build_source(forecast.provider, infos),
    )


@health_router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__, rules_version=RULES_VERSION)


@router.post("/advice/calculate", response_model=AdviceResponse)
def calculate(body: CalculateRequest, service: ServiceDep) -> AdviceResponse:
    if body.forecast is not None:
        forecast = body.forecast
    else:
        assert body.latitude is not None and body.longitude is not None
        forecast = service.get_forecast(body.latitude, body.longitude, body.provider)
    return _respond(service, forecast, body.mounted, body.profile, body.lead_time_days)


@router.get("/advice", response_model=AdviceResponse)
def get_advice(
    service: ServiceDep,
    settings: SettingsDep,
    mounted: TireType,
    latitude: Annotated[float | None, Query(ge=-90, le=90)] = None,
    longitude: Annotated[float | None, Query(ge=-180, le=180)] = None,
    provider: Annotated[str | None, Query(max_length=32)] = None,
) -> AdviceResponse:
    if latitude is None and longitude is None:
        latitude, longitude = settings.default_latitude, settings.default_longitude
    if latitude is None or longitude is None:
        raise HTTPException(status_code=422, detail="location_required")
    forecast = service.get_forecast(latitude, longitude, provider)
    return _respond(service, forecast, mounted, None, 7)


@router.get("/public-preview", response_model=PublicAdvice)
def public_preview(service: ServiceDep, settings: SettingsDep) -> PublicAdvice:
    """Berekent het landelijke publieke advies zonder het te publiceren."""
    return NationalAdviceService(service, settings.national_config()).compute()


@router.get("/providers", response_model=ProvidersResponse)
def providers(service: ServiceDep) -> ProvidersResponse:
    return ProvidersResponse(providers=service.provider_infos())
