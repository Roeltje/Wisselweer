"""Bouwt providers/service uit configuratie."""

from __future__ import annotations

from pydantic import BaseModel, SecretStr

from wisselweer.observations.base import ObservationProvider
from wisselweer.observations.wunderground import WundergroundProvider
from wisselweer.weather.base import ForecastProvider
from wisselweer.weather.brightsky import BrightSkyObservationProvider, BrightSkyProvider
from wisselweer.weather.cache import ForecastCache, InMemoryBackend
from wisselweer.weather.knmi import KnmiForecastProvider, KnmiObservationProvider
from wisselweer.weather.metno import MetNoProvider
from wisselweer.weather.openmeteo import OpenMeteoProvider
from wisselweer.weather.service import ForecastService


def _secret(s: SecretStr | None) -> str | None:
    return s.get_secret_value() if s is not None else None


class ProvidersConfig(BaseModel):
    contact: str | None = None
    commercial: bool = False
    openmeteo_base_url: str = "https://api.open-meteo.com"
    openmeteo_api_key: SecretStr | None = None
    knmi_api_key: SecretStr | None = None
    knmi_station_id: str | None = None  # toegevoegd: KNMI-waarnemingen hebben een station nodig
    wu_station_id: str | None = None
    wu_api_key: SecretStr | None = None
    default_provider: str = "metno"
    max_stale_hours: float = 24


def build_forecast_service(cfg: ProvidersConfig) -> ForecastService:
    providers: dict[str, ForecastProvider] = {
        "metno": MetNoProvider(cfg.contact),
        "openmeteo": OpenMeteoProvider(
            base_url=cfg.openmeteo_base_url,
            api_key=_secret(cfg.openmeteo_api_key),
            commercial=cfg.commercial,
        ),
        "brightsky": BrightSkyProvider(),
        "knmi_forecast": KnmiForecastProvider(_secret(cfg.knmi_api_key)),
    }
    cache = ForecastCache(InMemoryBackend(), max_stale_hours=cfg.max_stale_hours)
    return ForecastService(providers, cache, cfg.default_provider)


def build_observation_providers(
    cfg: ProvidersConfig, latitude: float, longitude: float
) -> dict[str, ObservationProvider]:
    return {
        "brightsky_obs": BrightSkyObservationProvider(latitude, longitude),
        "knmi": KnmiObservationProvider(_secret(cfg.knmi_api_key), cfg.knmi_station_id),
        "wunderground": WundergroundProvider(cfg.wu_station_id, _secret(cfg.wu_api_key)),
    }
