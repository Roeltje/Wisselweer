"""Pydantic-schema's voor banden, metingen en wissels."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from wisselweer.core.models import TireType
from wisselweer.storage.enums import ChangeMethod, OdometerSource, Position, TireStatus


class TireSetIn(BaseModel):
    type: TireType
    brand: str | None = None
    model: str | None = None
    size: str | None = None
    purchase_date: date | None = None
    purchase_price_cents: int | None = Field(default=None, ge=0)
    dot_code: str | None = None
    notes: str | None = None
    status: TireStatus = TireStatus.STORED


class TireSetPatch(BaseModel):
    type: TireType | None = None
    brand: str | None = None
    model: str | None = None
    size: str | None = None
    purchase_date: date | None = None
    purchase_price_cents: int | None = Field(default=None, ge=0)
    dot_code: str | None = None
    notes: str | None = None
    status: TireStatus | None = None


class TireSetOut(TireSetIn):
    id: int
    vehicle_id: int
    created_at: datetime


class TreadMeasurementIn(BaseModel):
    measured_at: date
    position: Position
    depth_mm: float = Field(ge=0, le=20)


class TreadMeasurementOut(TreadMeasurementIn):
    id: int
    tire_set_id: int


class OdometerOut(BaseModel):
    id: int
    vehicle_id: int
    reading_km: int
    recorded_at: datetime
    source: OdometerSource
    superseded_by_id: int | None
    note: str | None


class TireChangeOut(BaseModel):
    id: int
    vehicle_id: int
    changed_at: date
    odometer_reading_id: int | None
    from_set_id: int | None
    to_set_id: int
    performed_by: ChangeMethod
    garage_id: int | None
    cost_cents: int | None
    notes: str | None


class KmInterval(BaseModel):
    """Eén montageperiode van een set; km is None als niet betrouwbaar te bepalen."""

    start_change_id: int | None
    end_change_id: int | None
    start_date: date | None
    end_date: date | None
    start_km: int | None
    end_km: int | None
    km: int | None


class KmSummary(BaseModel):
    known_km: int | None
    complete: bool
    intervals: list[KmInterval]
