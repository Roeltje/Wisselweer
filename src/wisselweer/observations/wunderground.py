"""Weather Underground PWS (eigen weerstation) via api.weather.com."""

from __future__ import annotations

import httpx

from wisselweer.observations.base import Observation
from wisselweer.weather._util import (
    http_get,
    json_body,
    make_client,
    num,
    parse_iso_utc,
    quiet_httpx_logging,
)
from wisselweer.weather.base import ProviderInfo, ProviderNotConfigured, ProviderUnavailable

URL = "https://api.weather.com/v2/pws/observations/current"
_KMH_TO_MS = 1 / 3.6


class WundergroundProvider:
    id = "wunderground"

    def __init__(
        self, station_id: str | None, api_key: str | None, client: httpx.Client | None = None
    ) -> None:
        self._station = station_id or None
        self._key = api_key or None
        self._client = make_client(client)
        if self._key:
            quiet_httpx_logging()  # apiKey staat in de query-string

    def info(self) -> ProviderInfo:
        ok = bool(self._station and self._key)
        return ProviderInfo(
            id=self.id,
            name="Weather Underground (eigen station)",
            attribution="Waarnemingen: eigen weerstation via Weather Underground",
            license_url="https://www.wunderground.com/weather/api/d/terms.html",
            variables={
                "temperature_c",
                "dew_point_c",
                "humidity_pct",
                "wind_speed_ms",
                "pressure_hpa",
                "precip_rate_mm_h",
            },
            horizon_hours=0,
            commercial_use_ok=False,
            needs_credentials=True,
            configured=ok,
            status_detail=None if ok else "provider.missing_credentials",
        )

    def latest(self) -> list[Observation]:
        if not (self._station and self._key):
            raise ProviderNotConfigured("wunderground: station-ID of API-key ontbreekt")
        resp = http_get(
            self._client,
            URL,
            provider=self.id,
            params={
                "stationId": self._station,
                "format": "json",
                "units": "m",
                "numericPrecision": "decimal",
                "apiKey": self._key,
            },
            allow_status=(204,),
        )
        if resp.status_code == 204:
            return []
        body = json_body(resp, self.id)
        out = []
        try:
            for o in body.get("observations") or []:
                m = o.get("metric") or {}
                wind = num(m.get("windSpeed"))  # units=m: km/u
                out.append(
                    Observation(
                        provider=self.id,
                        station_id=str(o.get("stationID") or self._station),
                        latitude=num(o.get("lat")),
                        longitude=num(o.get("lon")),
                        observed_at=parse_iso_utc(o["obsTimeUtc"]),
                        temperature_c=num(m.get("temp")),
                        dew_point_c=num(m.get("dewpt")),
                        humidity_pct=num(o.get("humidity")),
                        precip_rate_mm_h=num(m.get("precipRate")),
                        wind_speed_ms=None if wind is None else wind * _KMH_TO_MS,
                        pressure_hpa=num(m.get("pressure")),
                    )
                )
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ProviderUnavailable("wunderground: onverwachte antwoordstructuur") from None
        return out
