"""Pydantic-schema's voor garages en afspraken."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from wisselweer.core.models import Direction
from wisselweer.storage.enums import AppointmentStatus


class GarageIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    notes: str | None = None
    lead_time_days: int = Field(default=14, ge=0)


class GaragePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    notes: str | None = None
    lead_time_days: int | None = Field(default=None, ge=0)


class GarageOut(GarageIn):
    id: int


class AppointmentIn(BaseModel):
    vehicle_id: int
    garage_id: int
    target_direction: Direction
    target_period_start: date | None = None
    target_period_end: date | None = None
    notes: str | None = None


class AppointmentOut(AppointmentIn):
    id: int
    status: AppointmentStatus
    appointment_at: datetime | None
    created_at: datetime
    updated_at: datetime
