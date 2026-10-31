"""FastAPI-applicatie."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from wisselweer import __version__
from wisselweer.api.routers.v1 import router as v1_router
from wisselweer.settings import Settings, get_settings
from wisselweer.weather.base import ProviderNotConfigured, ProviderUnavailable, UnknownProvider

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
    app = FastAPI(
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
            response.headers[k] = v
        return response

    app.include_router(v1_router)
    return app
