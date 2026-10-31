"""CacheBackend (zie weather.cache) op SQLite."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from wisselweer.core.models import Forecast
from wisselweer.storage.db import session_scope
from wisselweer.storage.orm import ForecastCache
from wisselweer.weather.cache import CacheEntry


class SqliteCacheBackend:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def get(self, key: str) -> CacheEntry | None:
        with session_scope(self._factory) as s:
            row = s.get(ForecastCache, key)
            if row is None:
                return None
            return CacheEntry(
                forecast=Forecast.model_validate(row.forecast),
                fetched_at=row.fetched_at,
                expires=row.expires,
                last_modified=row.last_modified,
            )

    def put(self, key: str, entry: CacheEntry) -> None:
        fc = entry.forecast
        with session_scope(self._factory) as s:
            row = s.get(ForecastCache, key) or ForecastCache(key=key)
            row.provider = fc.provider
            row.latitude = fc.latitude
            row.longitude = fc.longitude
            row.forecast = fc.model_dump(mode="json")
            row.fetched_at = entry.fetched_at
            row.expires = entry.expires
            row.last_modified = entry.last_modified
            s.add(row)
