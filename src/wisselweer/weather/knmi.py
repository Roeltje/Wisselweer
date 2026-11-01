"""KNMI Data Platform (EDR API). API-key verplicht (`Authorization`-header, zonder prefix).

Onzeker (niet tegen de live API geverifieerd): de parameternamen in de 10-minutencollectie.
De parser is daarom defensief: ontbrekende parameters worden None.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx

from wisselweer.observations.base import Observation
from wisselweer.weather._util import (
    http_get,
    json_body,
    make_client,
    num,
    parse_iso_utc,
)
from wisselweer.weather.base import (
    FetchResult,
    ProviderInfo,
    ProviderNotConfigured,
    ProviderUnavailable,
)

EDR_BASE = "https://api.dataplatform.knmi.nl/edr/v1"
COLLECTION = "10-minute-in-situ-meteorological-observations"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
ATTRIBUTION = "Weerdata: KNMI (CC BY 4.0)"
# Aanname op basis van KNMI-documentatie: ta=temperatuur, td=dauwpunt, rh=vochtigheid,
# ff=windsnelheid 10 m (m/s), pp=luchtdruk (hPa), rg=neerslagintensiteit (mm/u).
PARAMS = {
    "temperature_c": "ta",
    "dew_point_c": "td",
    "humidity_pct": "rh",
    "wind_speed_ms": "ff",
    "pressure_hpa": "pp",
    "precip_rate_mm_h": "rg",
}


def _last_value(values: object) -> tuple[int, float] | None:
    if not isinstance(values, list):
        return None
    for i in range(len(values) - 1, -1, -1):
        v = num(values[i])
        if v is not None:
            return i, v
    return None


def parse_coverage(doc: dict, station_id: str) -> Observation | None:
    """CoverageJSON (Coverage of CoverageCollection) -> laatste Observation, of None."""
    covs = doc.get("coverages") if isinstance(doc.get("coverages"), list) else [doc]
    best: Observation | None = None
    for cov in covs:
        if not isinstance(cov, dict):
            continue
        times = ((cov.get("domain") or {}).get("axes") or {}).get("t", {}).get("values") or []
        ranges = cov.get("ranges") or {}
        fields: dict[str, float | None] = {}
        t_idx = -1
        for field, pname in PARAMS.items():
            last = _last_value((ranges.get(pname) or {}).get("values"))
            fields[field] = last[1] if last else None
            if last:
                t_idx = max(t_idx, last[0])
        if t_idx < 0 or t_idx >= len(times):
            continue
        obs = Observation(
            provider="knmi",
            station_id=station_id,
            observed_at=parse_iso_utc(times[t_idx]),
            **fields,
        )
        if best is None or obs.observed_at > best.observed_at:
            best = obs
    return best


class KnmiObservationProvider:
    id = "knmi"

    def __init__(
        self, api_key: str | None, station_id: str | None, client: httpx.Client | None = None
    ) -> None:
        self._key = api_key or None
        self._station = station_id or None
        self._client = make_client(client)

    def info(self) -> ProviderInfo:
        detail = None
        if not self._key:
            detail = "provider.missing_credentials"
        elif not self._station:
            detail = "provider.knmi_missing_station"
        return ProviderInfo(
            id=self.id,
            name="KNMI waarnemingen (10 min)",
            attribution=ATTRIBUTION,
            license_url=LICENSE_URL,
            variables=set(PARAMS),
            horizon_hours=0,
            commercial_use_ok=True,
            needs_credentials=True,
            configured=detail is None,
            status_detail=detail,
        )

    def latest(self) -> list[Observation]:
        if not self._key or not self._station:
            raise ProviderNotConfigured("knmi: API-key of station ontbreekt")
        now = datetime.now(UTC)
        start = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = http_get(
            self._client,
            f"{EDR_BASE}/collections/{COLLECTION}/locations/{quote(self._station, safe='')}",
            provider=self.id,
            params={
                "datetime": f"{start}/{end}",
                "parameter-name": ",".join(PARAMS.values()),
            },
            headers={"Authorization": self._key},
        )
        doc = json_body(resp, self.id)
        try:
            obs = parse_coverage(doc, self._station)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ProviderUnavailable("knmi: onverwachte antwoordstructuur") from None
        return [obs] if obs else []


class KnmiForecastProvider:
    """Plaatshouder: KNMI HARMONIE-modeldata is niet als JSON/EDR beschikbaar (zie docs/providers.md)."""

    id = "knmi_forecast"

    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self._key = api_key or None
        self._client = client

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.id,
            name="KNMI HARMONIE",
            attribution=ATTRIBUTION,
            license_url=LICENSE_URL,
            variables=set(),
            horizon_hours=60,
            commercial_use_ok=True,
            needs_credentials=True,
            configured=False,
            status_detail="provider.knmi_forecast_not_available",
        )

    def fetch(
        self, latitude: float, longitude: float, *, if_modified_since: str | None = None
    ) -> FetchResult:
        raise ProviderNotConfigured("knmi_forecast: modeldata niet beschikbaar via JSON/EDR")
