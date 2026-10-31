"""FastAPI-dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from wisselweer.settings import Settings

if TYPE_CHECKING:
    from wisselweer.weather.service import ForecastService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_forecast_service(request: Request) -> ForecastService:
    """Bouwt de service lazy en bewaart hem per app."""
    app = request.app
    service = getattr(app.state, "forecast_service", None)
    if service is None:
        from wisselweer.weather.registry import build_forecast_service

        service = build_forecast_service(app.state.settings.providers_config())
        app.state.forecast_service = service
    return service
