"""FastAPI-dependencies.

Database en services worden lazy per app opgebouwd (`app.state`) en zijn in tests te
overschrijven via `app.dependency_overrides` of door `app.state.session_factory` te zetten.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, FastAPI, Request
from sqlalchemy.orm import Session, sessionmaker

from wisselweer.settings import Settings

if TYPE_CHECKING:
    from wisselweer.vehicles.advice import VehicleAdviceService
    from wisselweer.weather.service import ForecastService

_init_lock = threading.RLock()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def ensure_db(app: FastAPI) -> sessionmaker[Session]:
    """Maakt `data_dir` aan, draait de migraties en bouwt engine + sessionmaker (eenmalig)."""
    factory = getattr(app.state, "session_factory", None)
    if factory is not None:
        return factory
    with _init_lock:
        factory = getattr(app.state, "session_factory", None)
        if factory is None:
            from wisselweer.storage.db import make_engine, make_session_factory, migrate

            settings: Settings = app.state.settings
            data_dir = settings.data_dir
            data_dir.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{(data_dir / 'wisselweer.db').resolve()}"
            migrate(url)
            app.state.engine = make_engine(url)
            factory = make_session_factory(app.state.engine)
            app.state.session_factory = factory
    return factory


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return ensure_db(request.app)


def get_session(request: Request) -> Iterator[Session]:
    """Eén sessie per request: commit bij succes, rollback bij een fout."""
    session = ensure_db(request.app)()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


DEFAULT_PROVIDER_KEY = "default_provider"


def apply_default_provider_setting(factory: sessionmaker[Session], service: Any) -> None:
    """De in de instellingen gekozen standaardbron (`app_setting`) wint van de omgevingsvariabele."""
    from wisselweer.storage.orm import AppSetting
    from wisselweer.weather.base import UnknownProvider

    with factory() as s:
        row = s.get(AppSetting, DEFAULT_PROVIDER_KEY)
        value = row.value if row is not None else None
    if isinstance(value, str):
        try:
            service.set_default_provider(value)
        except UnknownProvider:
            pass


def get_forecast_service(request: Request) -> ForecastService:
    """Bouwt de service lazy (met SQLite-cache) en bewaart hem per app."""
    app = request.app
    service = getattr(app.state, "forecast_service", None)
    if service is None:
        with _init_lock:
            service = getattr(app.state, "forecast_service", None)
            if service is None:
                from wisselweer.storage.cache_backend import SqliteCacheBackend
                from wisselweer.weather.registry import build_forecast_service

                backend = SqliteCacheBackend(ensure_db(app))
                service = build_forecast_service(app.state.settings.providers_config(), backend)
                apply_default_provider_setting(ensure_db(app), service)
                app.state.forecast_service = service
    return service


def get_advice_service(
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    forecasts: Annotated[Any, Depends(get_forecast_service)],
) -> VehicleAdviceService:
    from wisselweer.vehicles.advice import VehicleAdviceService

    return VehicleAdviceService(factory, forecasts)
