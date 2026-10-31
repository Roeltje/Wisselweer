"""Contract voor forecastproviders. Implementaties leven in aparte modules per bron."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from wisselweer.core.models import Forecast


class ProviderInfo(BaseModel):
    """Wat een provider kan en mag; getoond in de beheerinterface."""

    id: str  # bv. "metno"
    name: str  # bv. "MET Norway"
    attribution: str  # verplichte bronvermelding
    license_url: str
    variables: set[str] = Field(default_factory=set)  # HourlyPoint-veldnamen die geleverd kunnen worden
    horizon_hours: int
    commercial_use_ok: bool
    needs_credentials: bool = False
    configured: bool = True
    status_detail: str | None = None  # i18n-sleutel, bv. "provider.missing_contact"


class ProviderError(Exception):
    """Basisfout; boodschap bevat nooit secrets of persoonsgegevens."""


class ProviderNotConfigured(ProviderError):
    pass


class ProviderUnavailable(ProviderError):
    """Netwerkfout, 5xx of time-out."""


class ProviderRateLimited(ProviderUnavailable):
    def __init__(self, retry_after: datetime | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class FetchResult(BaseModel):
    """Ruwe fetch-uitkomst inclusief HTTP-cachemetadata."""

    forecast: Forecast | None  # None bij HTTP 304 (niet gewijzigd)
    not_modified: bool = False
    expires: datetime | None = None
    last_modified: str | None = None  # letterlijk header-waarde, voor If-Modified-Since


@runtime_checkable
class ForecastProvider(Protocol):
    def info(self) -> ProviderInfo: ...

    def fetch(
        self, latitude: float, longitude: float, *, if_modified_since: str | None = None
    ) -> FetchResult:
        """Haalt een verwachting op. Raise ProviderNotConfigured/ProviderUnavailable."""
        ...
