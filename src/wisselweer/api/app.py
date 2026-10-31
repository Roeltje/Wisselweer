"""FastAPI-applicatie."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError

from wisselweer import __version__
from wisselweer.api.auth import install_auth, require_user
from wisselweer.api.deps import ensure_db
from wisselweer.api.routers.garages import router as garages_router
from wisselweer.api.routers.tires import router as tires_router
from wisselweer.api.routers.v1 import health_router
from wisselweer.api.routers.v1 import router as v1_router
from wisselweer.api.routers.vehicles import router as vehicles_router
from wisselweer.publisher.scheduler import start_scheduler, stop_scheduler
from wisselweer.settings import Settings, get_settings
from wisselweer.storage.errors import InvalidOperation, NotFoundError
from wisselweer.weather.base import ProviderNotConfigured, ProviderUnavailable, UnknownProvider
from wisselweer.web import routes as web_routes

log = logging.getLogger("wisselweer.api")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'",
}


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": code})


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ensure_db(app)  # data_dir aanmaken + migraties bij opstarten
        task = start_scheduler(app.state.settings)
        try:
            yield
        finally:
            await stop_scheduler(task)

    app = FastAPI(
        lifespan=lifespan,
        title="Wisselweer",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings or get_settings()
    app.state.forecast_service = None

    @app.exception_handler(ProviderNotConfigured)
    async def _not_configured(request: Request, exc: ProviderNotConfigured) -> JSONResponse:
        log.warning("provider_not_configured path=%s", request.url.path)
        return _error(503, "provider_not_configured")

    @app.exception_handler(UnknownProvider)
    async def _unknown(request: Request, exc: UnknownProvider) -> JSONResponse:
        return _error(422, "unknown_provider")

    @app.exception_handler(ProviderUnavailable)
    async def _unavailable(request: Request, exc: ProviderUnavailable) -> JSONResponse:
        log.warning("provider_unavailable path=%s", request.url.path)
        return _error(503, "provider_unavailable")

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> Response:
        if request.url.path.startswith("/api/"):
            return _error(404, "not_found")
        return web_routes.not_found_page(request)

    @app.exception_handler(InvalidOperation)
    async def _invalid(request: Request, exc: InvalidOperation) -> JSONResponse:
        # Servicemeldingen bevatten bewust geen persoonsgegevens; begrensd in lengte.
        return JSONResponse(
            status_code=409,
            content={"detail": "invalid_operation", "reason": str(exc)[:200]},
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError) -> JSONResponse:
        log.warning("integrity_error path=%s", request.url.path)  # geen statement/parameters
        return _error(409, "conflict")

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Standaard echoot FastAPI de invoer terug (kan PII bevatten): alleen locatie + type.
        errors = [{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
        return JSONResponse(
            status_code=422, content={"detail": "validation_error", "errors": errors}
        )

    @app.middleware("http")
    async def _security(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            response = await call_next(request)
        except Exception as exc:
            # Alleen type en pad loggen: geen traceback, query of waarden (kunnen PII/secrets bevatten).
            log.error("internal_error type=%s path=%s", type(exc).__name__, request.url.path)
            response = _error(500, "internal_error")
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)  # een route mag een eigen CSP zetten (/docs)
        return response

    install_auth(app, app.state.settings)
    protected = [Depends(require_user)]
    app.include_router(health_router)  # enige openbare API-route
    app.include_router(v1_router, dependencies=protected)
    app.include_router(vehicles_router, dependencies=protected)
    app.include_router(tires_router, dependencies=protected)
    app.include_router(garages_router, dependencies=protected)
    app.mount("/static", web_routes.static_files, name="static")
    app.include_router(web_routes.router)
    return app
