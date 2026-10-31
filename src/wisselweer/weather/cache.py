"""Forecast-cache met If-Modified-Since, stale-fallback en per-key locking."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel

from wisselweer.core.models import Forecast
from wisselweer.weather.base import FetchResult, ProviderRateLimited, ProviderUnavailable


class CacheEntry(BaseModel):
    forecast: Forecast
    fetched_at: datetime
    expires: datetime | None = None
    last_modified: str | None = None


class CacheBackend(Protocol):
    def get(self, key: str) -> CacheEntry | None: ...

    def put(self, key: str, entry: CacheEntry) -> None: ...


class InMemoryBackend:
    def __init__(self) -> None:
        self._data: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, entry: CacheEntry) -> None:
        with self._lock:
            self._data[key] = entry


def cache_key(provider_id: str, latitude: float, longitude: float) -> str:
    return f"{provider_id}:{latitude:.4f}:{longitude:.4f}"


class ForecastCache:
    def __init__(
        self,
        backend: CacheBackend,
        max_stale_hours: float = 24,
        min_refresh_minutes: float = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._backend = backend
        self._max_stale = timedelta(hours=max_stale_hours)
        self._min_refresh = timedelta(minutes=min_refresh_minutes)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._blocked_until: dict[str, datetime] = {}

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def _is_fresh(self, entry: CacheEntry, now: datetime) -> bool:
        if entry.expires is not None:
            return now < entry.expires
        return now < entry.fetched_at + self._min_refresh

    def _stale_copy(self, entry: CacheEntry, now: datetime) -> Forecast | None:
        if now - entry.fetched_at <= self._max_stale:
            return entry.forecast.model_copy(update={"is_stale": True})
        return None

    def get_or_fetch(self, key: str, fetch: Callable[[str | None], FetchResult]) -> Forecast:
        """`fetch(if_modified_since)` haalt vers op; fouten ProviderUnavailable vallen terug op cache."""
        with self._lock_for(key):
            now = self._clock()
            entry = self._backend.get(key)
            if entry and self._is_fresh(entry, now):
                return entry.forecast
            blocked = self._blocked_until.get(key)
            if blocked and now < blocked:
                if entry and (stale := self._stale_copy(entry, now)):
                    return stale
                raise ProviderRateLimited(blocked)
            try:
                result = fetch(entry.last_modified if entry else None)
                if result.not_modified:
                    if entry is None:
                        raise ProviderUnavailable("304 zonder cache-inhoud")
                    return self._store_revalidated(key, entry, result, now)
                if result.forecast is None:
                    raise ProviderUnavailable("lege fetch")
            except ProviderUnavailable as exc:
                if isinstance(exc, ProviderRateLimited) and exc.retry_after:
                    self._blocked_until[key] = exc.retry_after
                if entry and (stale := self._stale_copy(entry, now)):
                    return stale
                raise
            self._blocked_until.pop(key, None)
            expires = result.expires if result.expires and result.expires > now else None
            self._backend.put(
                key,
                CacheEntry(
                    forecast=result.forecast,
                    fetched_at=now,
                    expires=expires,
                    last_modified=result.last_modified,
                ),
            )
            return result.forecast

    def _store_revalidated(
        self, key: str, entry: CacheEntry, result: FetchResult, now: datetime
    ) -> Forecast:
        expires = result.expires if result.expires and result.expires > now else None
        forecast = entry.forecast.model_copy(update={"valid_until": expires})
        self._backend.put(
            key,
            CacheEntry(
                forecast=forecast,
                fetched_at=now,
                expires=expires,
                last_modified=result.last_modified or entry.last_modified,
            ),
        )
        return forecast
