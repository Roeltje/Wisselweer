"""Open-Meteo forecast API."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from wisselweer.core.models import HourlyPoint, PrecipType
from wisselweer.weather._util import (
    build_forecast,
    http_get,
    json_body,
    make_client,
    num,
    parse_iso_utc,
    quiet_httpx_logging,
    round_coord,
)
from wisselweer.weather.base import (
    FetchResult,
    ProviderInfo,
    ProviderNotConfigured,
    ProviderUnavailable,
)

FREE_HOST = "api.open-meteo.com"
LICENSE_URL = "https://open-meteo.com/en/license"
_HOURLY = (
    "temperature_2m,dew_point_2m,relative_humidity_2m,precipitation,"
    "precipitation_probability,snowfall,snow_depth,weather_code,wind_speed_10m"
)
_VARS = {
    "temperature_c",
    "dew_point_c",
    "humidity_pct",
    "precip_mm",
    "precip_probability_pct",
    "precip_type",
    "snow_cm",
    "snow_depth_cm",
    "wind_speed_ms",
}


def precip_type_from_wmo(code: object) -> PrecipType | None:
    n = num(code)
    if n is None:
        return None
    c = int(n)
    if c in (0, 1, 2, 3, 45, 48):
        return PrecipType.NONE
    if c in (56, 57, 66, 67):
        return PrecipType.FREEZING_RAIN
    if c in (51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99):
        return PrecipType.RAIN
    if c in (71, 73, 75, 77, 85, 86):
        return PrecipType.SNOW
    return PrecipType.UNKNOWN


class OpenMeteoProvider:
    id = "openmeteo"

    def __init__(
        self,
        base_url: str = "https://api.open-meteo.com",
        api_key: str | None = None,
        commercial: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = (api_key or None) or None
        self._commercial = commercial
        self._client = make_client(client)
        if self._api_key:
            quiet_httpx_logging()  # apikey staat in de query-string

    @property
    def _is_free_host(self) -> bool:
        return (urlparse(self._base_url).hostname or "") == FREE_HOST

    @property
    def _commercial_ok(self) -> bool:
        return (not self._is_free_host) or bool(self._api_key)

    def info(self) -> ProviderInfo:
        blocked = self._commercial and not self._commercial_ok
        return ProviderInfo(
            id=self.id,
            name="Open-Meteo",
            attribution="Weerdata: Open-Meteo.com (CC BY 4.0)",
            license_url=LICENSE_URL,
            variables=set(_VARS),
            horizon_hours=16 * 24,
            commercial_use_ok=self._commercial_ok,
            needs_credentials=False,
            configured=not blocked,
            status_detail="provider.openmeteo_noncommercial" if blocked else None,
        )

    def fetch(
        self, latitude: float, longitude: float, *, if_modified_since: str | None = None
    ) -> FetchResult:
        if not self.info().configured:
            raise ProviderNotConfigured(
                "openmeteo: gratis host niet toegestaan bij commercieel gebruik"
            )
        lat, lon = round_coord(latitude), round_coord(longitude)
        params: dict[str, object] = {
            "latitude": lat,
            "longitude": lon,
            "hourly": _HOURLY,
            "wind_speed_unit": "ms",
            "forecast_days": 16,
            "timezone": "UTC",
        }
        if self._api_key:
            params["apikey"] = self._api_key
        resp = http_get(
            self._client, f"{self._base_url}/v1/forecast", provider=self.id, params=params
        )
        body = json_body(resp, self.id)
        try:
            hourly = self._parse(body["hourly"])
        except (KeyError, TypeError, ValueError):
            raise ProviderUnavailable("openmeteo: onverwachte antwoordstructuur") from None
        return FetchResult(forecast=build_forecast(self.id, lat, lon, hourly))

    @staticmethod
    def _parse(h: dict) -> list[HourlyPoint]:
        times = h["time"]

        def col(name: str) -> list:
            v = h.get(name)
            return v if isinstance(v, list) else [None] * len(times)

        temp, dew, rh = col("temperature_2m"), col("dew_point_2m"), col("relative_humidity_2m")
        pr, prob, snow = col("precipitation"), col("precipitation_probability"), col("snowfall")
        depth, wcode, wind = col("snow_depth"), col("weather_code"), col("wind_speed_10m")
        out = []
        for i, t in enumerate(times):
            d = num(depth[i])
            out.append(
                HourlyPoint(
                    time=parse_iso_utc(t),
                    temperature_c=num(temp[i]),
                    dew_point_c=num(dew[i]),
                    humidity_pct=num(rh[i]),
                    precip_mm=num(pr[i]),
                    precip_probability_pct=num(prob[i]),
                    precip_type=precip_type_from_wmo(wcode[i]),
                    snow_cm=num(snow[i]),
                    snow_depth_cm=None if d is None else d * 100.0,  # API levert meters
                    wind_speed_ms=num(wind[i]),
                )
            )
        return out
