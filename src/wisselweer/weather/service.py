"""ForecastService: kiest een provider en haalt (gecachet) een verwachting op."""

from __future__ import annotations

from wisselweer.core.models import Forecast
from wisselweer.weather.base import (
    ForecastProvider,
    ProviderInfo,
    ProviderNotConfigured,
    UnknownProvider,
)
from wisselweer.weather.cache import ForecastCache, cache_key


class ForecastService:
    def __init__(
        self,
        providers: dict[str, ForecastProvider],
        cache: ForecastCache,
        default_provider: str,
    ) -> None:
        if default_provider not in providers:
            raise ValueError("default_provider is geen geregistreerde provider")
        self._providers = providers
        self._cache = cache
        self._default = default_provider

    def get_forecast(
        self, latitude: float, longitude: float, provider_id: str | None = None
    ) -> Forecast:
        pid = provider_id or self._default
        provider = self._providers.get(pid)
        if provider is None:
            raise UnknownProvider("onbekende provider")
        if not provider.info().configured:
            raise ProviderNotConfigured(f"{pid}: niet geconfigureerd")
        lat, lon = round(latitude, 4), round(longitude, 4)
        return self._cache.get_or_fetch(
            cache_key(pid, lat, lon),
            lambda ims: provider.fetch(lat, lon, if_modified_since=ims),
        )

    def provider_infos(self) -> list[ProviderInfo]:
        return [p.info() for p in self._providers.values()]
