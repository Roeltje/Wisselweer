"""Geocoderen (adres/plaats -> coördinaten) via een Nominatim-compatibele API.

Houdt zich aan de Nominatim-gebruiksregels: herkenbare User-Agent, hooguit één upstream-verzoek
per seconde (proces-breed) en een cache van eerdere zoekopdrachten. De zoektekst wordt nooit
gelogd en foutmeldingen bevatten geen URL's of zoektekst. Alleen afgeronde coördinaten
(3 decimalen, ca. 100 m) verlaten deze module.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

import httpx
from pydantic import BaseModel

from wisselweer.weather._util import (
    build_user_agent,
    http_get,
    make_client,
    quiet_httpx_logging,
)
from wisselweer.weather.base import ProviderUnavailable

PROVIDER = "geocoder"
MAX_RESULTS = 5
COORD_DECIMALS = 3  # ca. 100 m: genoeg voor een weerlocatie, geen exact adres
MAX_LABEL_CHARS = 200
MIN_QUERY_CHARS = 2
MAX_QUERY_CHARS = 200
CACHE_TTL_S = 24 * 3600.0
CACHE_MAX_ITEMS = 500
MIN_INTERVAL_S = 1.0  # Nominatim: maximaal 1 verzoek per seconde
MAX_WAIT_S = 3.0  # langer wachten op een beurt dan dit: 429 teruggeven


def _now() -> float:
    return time.monotonic()


class GeocodeResult(BaseModel):
    label: str
    latitude: float
    longitude: float


class GeocoderError(Exception):
    """Basisfout; de boodschap bevat nooit de zoektekst of een URL."""


class GeocoderNotConfigured(GeocoderError):
    """Geocoderen staat uit of er is geen contactgegeven voor de User-Agent."""


class GeocoderUnavailable(GeocoderError):
    """Netwerkfout, time-out, onverwachte status of onbruikbaar antwoord van de dienst."""


class GeocoderRateLimited(GeocoderError):
    def __init__(self, retry_after_s: float) -> None:
        super().__init__("rate limited")
        self.retry_after_s = retry_after_s


class RateLimiter:
    """Dwingt een minimale tussentijd tussen upstream-verzoeken af (thread-safe).

    Wie te vroeg is, krijgt een beurt in de nabije toekomst en wacht; is de wachttijd langer
    dan `max_wait_s`, dan volgt `GeocoderRateLimited` zodat er geen threads opstapelen.
    """

    def __init__(
        self,
        interval_s: float = MIN_INTERVAL_S,
        max_wait_s: float = MAX_WAIT_S,
        clock: Callable[[], float] = _now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = interval_s
        self._max_wait = max_wait_s
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            start = max(now, self._next_slot)
            wait = start - now
            if wait > self._max_wait:
                raise GeocoderRateLimited(wait)
            self._next_slot = start + self._interval
        if wait > 0:
            self._sleep(wait)


# Proces-breed: ook bij meerdere Geocoder-instanties gaat er maximaal 1 verzoek per seconde uit.
UPSTREAM_LIMITER = RateLimiter()


def normalize_query(query: str) -> str:
    """Sleutel voor de cache: witruimte samengevoegd en hoofdletterongevoelig."""
    return " ".join(query.split()).casefold()


def _coord(value: object, limit: float) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]  # Nominatim levert strings
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or abs(number) > limit:
        return None
    return round(number, COORD_DECIMALS) + 0.0  # + 0.0: geen "-0.0"


def parse_results(data: object) -> list[GeocodeResult]:
    """Zet het Nominatim-antwoord (jsonv2) om; onbruikbare rijen worden overgeslagen."""
    if not isinstance(data, list):
        raise GeocoderUnavailable("onverwacht antwoordformaat")
    out: list[GeocodeResult] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        lat, lon = _coord(row.get("lat"), 90), _coord(row.get("lon"), 180)
        label = row.get("display_name")
        if lat is None or lon is None or not isinstance(label, str) or not label.strip():
            continue
        out.append(
            GeocodeResult(label=label.strip()[:MAX_LABEL_CHARS], latitude=lat, longitude=lon)
        )
        if len(out) >= MAX_RESULTS:
            break
    return out


class Geocoder:
    def __init__(
        self,
        base_url: str,
        contact: str | None,
        client: httpx.Client | None = None,
        *,
        limiter: RateLimiter | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._base_url = base_url.strip().rstrip("/")
        self._contact = (contact or "").strip() or None
        self._client = make_client(client)
        self._limiter = limiter or UPSTREAM_LIMITER
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple[str, str], tuple[float, list[GeocodeResult]]] = OrderedDict()
        # De zoektekst staat in de query-string; httpx logt die op INFO.
        quiet_httpx_logging()

    def _now(self) -> float:
        return self._clock() if self._clock is not None else _now()

    @property
    def enabled(self) -> bool:
        return bool(self._base_url) and self._contact is not None

    def search(self, query: str, locale: str) -> list[GeocodeResult]:
        if not self.enabled:
            raise GeocoderNotConfigured("geocoderen staat uit")
        key = (normalize_query(query), locale)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        self._limiter.acquire()
        try:
            resp = http_get(
                self._client,
                f"{self._base_url}/search",
                provider=PROVIDER,
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": MAX_RESULTS,
                    "addressdetails": 0,
                    "accept-language": locale,
                },
                headers={
                    "User-Agent": build_user_agent(self._contact),
                    "Accept": "application/json",
                },
            )
        except ProviderUnavailable as exc:  # ook 429 van de dienst zelf
            raise GeocoderUnavailable(str(exc)) from None
        try:
            results = parse_results(resp.json())
        except ValueError:
            raise GeocoderUnavailable("ongeldige JSON") from None
        self._cache_put(key, results)
        return results

    def _cache_get(self, key: tuple[str, str]) -> list[GeocodeResult] | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expires, results = entry
            if self._now() >= expires:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return list(results)

    def _cache_put(self, key: tuple[str, str], results: list[GeocodeResult]) -> None:
        with self._lock:
            self._cache[key] = (self._now() + CACHE_TTL_S, list(results))
            self._cache.move_to_end(key)
            while len(self._cache) > CACHE_MAX_ITEMS:
                self._cache.popitem(last=False)
