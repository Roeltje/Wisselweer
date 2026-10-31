"""Contract voor observationproviders (eigen weerstations, KNMI-waarnemingen)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from wisselweer.weather.base import ProviderInfo


class Observation(BaseModel):
    provider: str
    station_id: str
    latitude: float | None = None
    longitude: float | None = None
    observed_at: datetime  # aware UTC
    temperature_c: float | None = None
    dew_point_c: float | None = None
    humidity_pct: float | None = None
    precip_rate_mm_h: float | None = None
    wind_speed_ms: float | None = None
    pressure_hpa: float | None = None


@runtime_checkable
class ObservationProvider(Protocol):
    def info(self) -> ProviderInfo: ...

    def latest(self) -> list[Observation]:
        """Meest recente waarneming(en). Raise ProviderNotConfigured/ProviderUnavailable."""
        ...
