"""Advies per voertuig: forecast per locatie, engine, snapshots."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from wisselweer.core import (
    Advice,
    AdviceInput,
    DrivingProfile,
    EngineConfig,
    Forecast,
    TireType,
    evaluate,
)
from wisselweer.storage.db import session_scope
from wisselweer.storage.enums import ChangeMethod, TireStatus
from wisselweer.storage.errors import NotFoundError
from wisselweer.storage.orm import (
    AdviceSnapshot,
    ForecastSnapshot,
    Garage,
    Location,
    TireSet,
    Vehicle,
)
from wisselweer.weather.base import ProviderError
from wisselweer.weather.service import ForecastService


class VehicleAdviceService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        forecast_service: ForecastService,
        engine_config: EngineConfig | None = None,
    ) -> None:
        self._factory = session_factory
        self._forecasts = forecast_service
        self._config = engine_config or EngineConfig()

    def advice_for_vehicle(self, vehicle_id: int, now: datetime) -> Advice:
        # Eerst lezen en de forecast ophalen buiten de schrijftransactie: een SQLite-cache schrijft
        # via een eigen sessie, en dat geeft "database is locked" als wij al een leessnapshot hebben.
        with session_scope(self._factory) as s0:
            v0 = s0.get(Vehicle, vehicle_id)
            if v0 is None:
                raise NotFoundError("voertuig niet gevonden")
            loc0 = s0.get(Location, v0.location_id)
            assert loc0 is not None
            lat, lon = loc0.latitude, loc0.longitude
        try:
            forecast: Forecast | None = self._forecasts.get_forecast(lat, lon)
        except ProviderError:
            forecast = None

        with session_scope(self._factory) as s:
            v = s.get(Vehicle, vehicle_id)
            if v is None:
                raise NotFoundError("voertuig niet gevonden")
            loc = s.get(Location, v.location_id)
            assert loc is not None

            mounted_set = s.scalar(
                select(TireSet).where(
                    TireSet.vehicle_id == v.id, TireSet.status == TireStatus.MOUNTED
                )
            )
            mounted = TireType(mounted_set.type) if mounted_set else None

            lead = v.prep_days
            if v.change_method == ChangeMethod.GARAGE and v.preferred_garage_id is not None:
                garage = s.get(Garage, v.preferred_garage_id)
                if garage is not None:
                    lead = garage.lead_time_days

            prev_row = s.scalar(
                select(AdviceSnapshot)
                .where(
                    AdviceSnapshot.vehicle_id == v.id,
                    AdviceSnapshot.invalidated_at.is_(None),
                )
                .order_by(AdviceSnapshot.evaluated_at.desc(), AdviceSnapshot.id.desc())
                .limit(1)
            )
            previous = Advice.model_validate(prev_row.advice) if prev_row else None

            advice = evaluate(
                AdviceInput(
                    forecast=forecast,
                    mounted=mounted,
                    profile=DrivingProfile.model_validate(v.driving_profile),
                    now=now,
                    previous=previous,
                    lead_time_days=lead,
                    config=self._config,
                )
            )

            fs_id = self._store_forecast(s, forecast) if forecast else None
            s.add(
                AdviceSnapshot(
                    vehicle_id=v.id,
                    location_id=loc.id,
                    evaluated_at=advice.evaluated_at,
                    advice=advice.model_dump(mode="json"),
                    forecast_snapshot_id=fs_id,
                    rules_version=advice.rules_version,
                )
            )
            return advice

    @staticmethod
    def _store_forecast(s: Session, fc: Forecast) -> int:
        """Eén snapshot per (provider, locatie, fetch)."""
        existing = s.scalar(
            select(ForecastSnapshot).where(
                ForecastSnapshot.provider == fc.provider,
                ForecastSnapshot.latitude == fc.latitude,
                ForecastSnapshot.longitude == fc.longitude,
                ForecastSnapshot.fetched_at == fc.fetched_at,
            )
        )
        if existing:
            return existing.id
        row = ForecastSnapshot(
            provider=fc.provider,
            latitude=fc.latitude,
            longitude=fc.longitude,
            fetched_at=fc.fetched_at,
            forecast=fc.model_dump(mode="json"),
        )
        s.add(row)
        s.flush()
        return row.id
