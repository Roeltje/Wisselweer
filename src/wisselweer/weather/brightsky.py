"""Bright Sky (DWD open data): MOSMIX-verwachting en actuele waarneming."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from wisselweer.core.models import HourlyPoint, PrecipType
from wisselweer.observations.base import Observation
from wisselweer.weather._util import (
    build_forecast,
    http_get,
    json_body,
    make_client,
    num,
    parse_iso_utc,
    round_coord,
)
from wisselweer.weather.base import FetchResult, ProviderInfo, ProviderUnavailable

BASE = "https://api.brightsky.dev"
LICENSE_URL = "https://www.dwd.de/DE/service/rechtliche_hinweise/rechtliche_hinweise_node.html"
ATTRIBUTION = "Weerdata: Deutscher Wetterdienst (DWD), via Bright Sky"
_KMH_TO_MS = 1 / 3.6
_VARS = {
    "temperature_c",
    "dew_point_c",
    "humidity_pct",
    "precip_mm",
    "precip_probability_pct",
    "precip_type",
    "wind_speed_ms",
}


def precip_type_from_condition(condition: object) -> PrecipType | None:
    if not isinstance(condition, str):
        return None
    c = condition.lower()
    if c in ("dry", "fog"):
        return PrecipType.NONE
    if c in ("rain", "hail", "thunderstorm"):
        return PrecipType.RAIN
    if c == "sleet":
        return PrecipType.SLEET
    if c == "snow":
        return PrecipType.SNOW
    return PrecipType.UNKNOWN


def _ms(kmh: object) -> float | None:
    v = num(kmh)
    return None if v is None else v * _KMH_TO_MS


class BrightSkyProvider:
    id = "brightsky"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = make_client(client)

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.id,
            name="Bright Sky (DWD)",
            attribution=ATTRIBUTION,
            license_url=LICENSE_URL,
            variables=set(_VARS),
            horizon_hours=240,
            # De publieke Bright Sky-instantie is bedoeld voor niet-commercieel gebruik.
            commercial_use_ok=False,
        )

    def fetch(
        self, latitude: float, longitude: float, *, if_modified_since: str | None = None
    ) -> FetchResult:
        lat, lon = round_coord(latitude), round_coord(longitude)
        today = datetime.now(UTC).date()
        resp = http_get(
            self._client,
            f"{BASE}/weather",
            provider=self.id,
            params={
                "lat": lat,
                "lon": lon,
                "date": today.isoformat(),
                "last_date": (today + timedelta(days=10)).isoformat(),
                "units": "dwd",
                "tz": "UTC",
            },
        )
        body = json_body(resp, self.id)
        try:
            hourly = [self._point(w) for w in body["weather"]]
        except (KeyError, TypeError, ValueError):
            raise ProviderUnavailable("brightsky: onverwachte antwoordstructuur") from None
        return FetchResult(forecast=build_forecast(self.id, lat, lon, hourly))

    @staticmethod
    def _point(w: dict) -> HourlyPoint:
        return HourlyPoint(
            time=parse_iso_utc(w["timestamp"]),
            temperature_c=num(w.get("temperature")),
            dew_point_c=num(w.get("dew_point")),
            humidity_pct=num(w.get("relative_humidity")),
            precip_mm=num(w.get("precipitation")),
            precip_probability_pct=num(w.get("precipitation_probability")),
            precip_type=precip_type_from_condition(w.get("condition")),
            wind_speed_ms=_ms(w.get("wind_speed")),
        )


class BrightSkyObservationProvider:
    id = "brightsky_obs"

    def __init__(
        self, latitude: float, longitude: float, client: httpx.Client | None = None
    ) -> None:
        self._lat, self._lon = round_coord(latitude), round_coord(longitude)
        self._client = make_client(client)

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.id,
            name="Bright Sky (DWD) waarnemingen",
            attribution=ATTRIBUTION,
            license_url=LICENSE_URL,
            variables={"temperature_c", "dew_point_c", "humidity_pct", "wind_speed_ms"},
            horizon_hours=0,
            commercial_use_ok=False,
        )

    def latest(self) -> list[Observation]:
        resp = http_get(
            self._client,
            f"{BASE}/current_weather",
            provider=self.id,
            params={"lat": self._lat, "lon": self._lon, "units": "dwd", "tz": "UTC"},
        )
        body = json_body(resp, self.id)
        try:
            w = body["weather"]
            observed = parse_iso_utc(w["timestamp"])
            sources = body.get("sources") or []
            src = next((s for s in sources if s.get("id") == w.get("source_id")), None)
            src = src or (sources[0] if sources else {})
            station = str(w.get("source_id", src.get("id", "unknown")))
            p10 = num(w.get("precipitation_10"))
            wind = (
                w.get("wind_speed_10")
                if w.get("wind_speed_10") is not None
                else w.get("wind_speed")
            )
            return [
                Observation(
                    provider=self.id,
                    station_id=station,
                    latitude=num(src.get("lat")),
                    longitude=num(src.get("lon")),
                    observed_at=observed,
                    temperature_c=num(w.get("temperature")),
                    dew_point_c=num(w.get("dew_point")),
                    humidity_pct=num(w.get("relative_humidity")),
                    precip_rate_mm_h=None if p10 is None else p10 * 6.0,  # mm per 10 min -> mm/u
                    wind_speed_ms=_ms(wind),
                    pressure_hpa=num(w.get("pressure_msl")),
                )
            ]
        except (KeyError, TypeError, ValueError):
            raise ProviderUnavailable("brightsky_obs: onverwachte antwoordstructuur") from None
