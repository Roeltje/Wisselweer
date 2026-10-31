"""MET Norway Locationforecast 2.0 (complete)."""

from __future__ import annotations

import httpx

from wisselweer import __version__
from wisselweer.core.models import HourlyPoint, PrecipType
from wisselweer.weather._util import (
    build_forecast,
    http_get,
    json_body,
    make_client,
    num,
    parse_http_date,
    parse_iso_utc,
    round_coord,
)
from wisselweer.weather.base import (
    FetchResult,
    ProviderInfo,
    ProviderNotConfigured,
    ProviderUnavailable,
)

URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
LICENSE_URL = "https://api.met.no/doc/License"
_VARS = {
    "temperature_c",
    "dew_point_c",
    "humidity_pct",
    "precip_mm",
    "precip_type",
    "wind_speed_ms",
}


def precip_type_from_symbol(symbol: str | None) -> PrecipType | None:
    """Leidt neerslagtype af uit een MET-symbol_code (bv. 'lightrain_day'). None = geen symbool."""
    if not symbol:
        return None
    s = symbol.lower()
    for suffix in ("_day", "_night", "_polartwilight"):
        s = s.removesuffix(suffix)
    if "sleet" in s:
        return PrecipType.SLEET
    if "snow" in s:
        return PrecipType.SNOW
    if "rain" in s or "drizzle" in s:
        return PrecipType.RAIN
    if s in {"clearsky", "fair", "partlycloudy", "cloudy", "fog"}:
        return PrecipType.NONE
    return PrecipType.UNKNOWN


class MetNoProvider:
    id = "metno"

    def __init__(self, contact: str | None, client: httpx.Client | None = None) -> None:
        self._contact = (contact or "").strip() or None
        self._client = make_client(client)

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.id,
            name="MET Norway",
            attribution="Weerdata: MET Norway (CC BY 4.0)",
            license_url=LICENSE_URL,
            variables=set(_VARS),
            horizon_hours=240,
            commercial_use_ok=True,
            needs_credentials=False,
            configured=self._contact is not None,
            status_detail=None if self._contact else "provider.missing_contact",
        )

    def _user_agent(self) -> str:
        return f"Wisselweer/{__version__} (+https://wisselweer.nl; {self._contact})"

    def fetch(
        self, latitude: float, longitude: float, *, if_modified_since: str | None = None
    ) -> FetchResult:
        if self._contact is None:
            raise ProviderNotConfigured("metno: contact ontbreekt")
        lat, lon = round_coord(latitude), round_coord(longitude)
        headers = {"User-Agent": self._user_agent()}
        if if_modified_since:
            headers["If-Modified-Since"] = if_modified_since
        resp = http_get(
            self._client,
            URL,
            provider=self.id,
            params={"lat": lat, "lon": lon},
            headers=headers,
            allow_status=(304,),
        )
        expires = parse_http_date(resp.headers.get("Expires"))
        last_modified = resp.headers.get("Last-Modified")
        if resp.status_code == 304:
            return FetchResult(
                forecast=None, not_modified=True, expires=expires, last_modified=last_modified
            )
        body = json_body(resp, self.id)
        try:
            series = body["properties"]["timeseries"]
            hourly = [self._point(e) for e in series]
        except (KeyError, TypeError, ValueError):
            raise ProviderUnavailable("metno: onverwachte antwoordstructuur") from None
        forecast = build_forecast(self.id, lat, lon, hourly, valid_until=expires)
        return FetchResult(forecast=forecast, expires=expires, last_modified=last_modified)

    @staticmethod
    def _point(entry: dict) -> HourlyPoint:
        data = entry["data"]
        det = data.get("instant", {}).get("details", {})
        n1 = data.get("next_1_hours") or {}
        # Na ~60 uur levert MET alleen stappen van 6 uur; neerslag per uur is dan niet bekend.
        symbol = (
            (n1.get("summary") or {}).get("symbol_code")
            or ((data.get("next_6_hours") or {}).get("summary") or {}).get("symbol_code")
            or ((data.get("next_12_hours") or {}).get("summary") or {}).get("symbol_code")
        )
        return HourlyPoint(
            time=parse_iso_utc(entry["time"]),
            temperature_c=num(det.get("air_temperature")),
            dew_point_c=num(det.get("dew_point_temperature")),
            humidity_pct=num(det.get("relative_humidity")),
            wind_speed_ms=num(det.get("wind_speed")),
            precip_mm=num((n1.get("details") or {}).get("precipitation_amount")),
            precip_type=precip_type_from_symbol(symbol),
        )
