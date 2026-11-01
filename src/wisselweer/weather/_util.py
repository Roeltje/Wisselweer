"""Gedeelde HTTP- en normalisatiehulpen voor providers.

Foutboodschappen bevatten bewust nooit URL's, query-strings of headers (API-keys).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

from wisselweer import __version__
from wisselweer.core.models import Forecast, HourlyPoint
from wisselweer.weather.base import ProviderRateLimited, ProviderUnavailable

TIMEOUT_S = 15.0
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # een weerbron levert hooguit enkele honderden kB
DEFAULT_TZ = "Europe/Amsterdam"

_HOURLY_FIELDS = tuple(f for f in HourlyPoint.model_fields if f != "time")


def build_user_agent(contact: str | None) -> str:
    """Herkenbare User-Agent met contactgegeven (verplicht bij MET Norway en Nominatim)."""
    return f"Wisselweer/{__version__} (+https://wisselweer.nl; {contact})"


def round_coord(value: float) -> float:
    return round(float(value), 4)


def quiet_httpx_logging() -> None:
    """httpx logt volledige URL's op INFO; bij keys in de query-string zetten we dat uit."""
    logging.getLogger("httpx").setLevel(logging.WARNING)


def parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def parse_retry_after(value: str | None, now: datetime | None = None) -> datetime | None:
    if not value:
        return None
    now = now or datetime.now(UTC)
    value = value.strip()
    if value.isdigit():
        return now + timedelta(seconds=int(value))
    return parse_http_date(value)


def parse_iso_utc(value: str, *, assume_utc: bool = True) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        if not assume_utc:
            raise ValueError("naieve tijd")
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def make_client(client: httpx.Client | None) -> httpx.Client:
    return client if client is not None else httpx.Client(timeout=TIMEOUT_S)


def http_get(
    client: httpx.Client,
    url: str,
    *,
    provider: str,
    params: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    allow_status: tuple[int, ...] = (),
) -> httpx.Response:
    """GET met uniforme foutmapping. 2xx en `allow_status` komen terug; de rest raised.

    De body wordt gestreamd gelezen en afgebroken bij meer dan `MAX_RESPONSE_BYTES` (na
    decompressie), zodat een foute of kwaadwillende bron het geheugen niet kan vullen.
    """
    try:
        with client.stream("GET", url, params=params, headers=headers, timeout=TIMEOUT_S) as resp:
            code = resp.status_code
            if not (code in allow_status or 200 <= code < 300):
                if code == 429:
                    raise ProviderRateLimited(parse_retry_after(resp.headers.get("Retry-After")))
                if code in (401, 403):
                    raise ProviderUnavailable(f"{provider}: toegang geweigerd (HTTP {code})")
                raise ProviderUnavailable(f"{provider}: onverwachte HTTP-status {code}")
            declared = resp.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
                raise ProviderUnavailable(f"{provider}: antwoord te groot")
            body = bytearray()
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ProviderUnavailable(f"{provider}: antwoord te groot")
            # De inhoud is al gedecodeerd: kopieer de headers zonder codering/lengte.
            headers_out = [
                (k, v)
                for k, v in resp.headers.multi_items()
                if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
            ]
            return httpx.Response(
                code, headers=headers_out, content=bytes(body), request=resp.request
            )
    except httpx.HTTPError as exc:  # geen str(exc): kan URL bevatten
        raise ProviderUnavailable(f"{provider}: netwerkfout ({type(exc).__name__})") from None


def json_body(resp: httpx.Response, provider: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise ProviderUnavailable(f"{provider}: ongeldige JSON") from None
    if not isinstance(data, dict):
        raise ProviderUnavailable(f"{provider}: onverwacht antwoordformaat")
    return data


def num(value: object) -> float | None:
    """Getal of None; bool en niet-numeriek tellen als ontbrekend."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def build_forecast(
    provider: str,
    latitude: float,
    longitude: float,
    hourly: list[HourlyPoint],
    *,
    fetched_at: datetime | None = None,
    valid_until: datetime | None = None,
    timezone: str = DEFAULT_TZ,
) -> Forecast:
    hourly = sorted(hourly, key=lambda p: p.time)
    available = {f for f in _HOURLY_FIELDS if any(getattr(p, f) is not None for p in hourly)}
    return Forecast(
        provider=provider,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        fetched_at=fetched_at or datetime.now(UTC),
        valid_until=valid_until,
        hourly=hourly,
        available_variables=available,
    )
