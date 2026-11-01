"""Pydantic-schema's voor voertuigen (nooit ORM-objecten naar buiten)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from wisselweer.core.models import DrivingProfile
from wisselweer.storage.enums import ChangeMethod


def _tz_ok(v: str) -> str:
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(v)
    except (KeyError, ValueError, OSError):  # ZoneInfoNotFoundError is een KeyError
        raise ValueError("onbekende tijdzone") from None
    return v


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = "Europe/Amsterdam"

    _tz = field_validator("timezone")(_tz_ok)


class LocationOut(LocationIn):
    id: int


class VehicleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    make: str | None = None
    model: str | None = None
    license_plate: str | None = Field(default=None, max_length=20)
    build_year: int | None = Field(default=None, ge=1900, le=2100)
    location: LocationIn
    timezone: str = "Europe/Amsterdam"
    driving_profile: DrivingProfile = Field(default_factory=DrivingProfile.commute)
    change_method: ChangeMethod = ChangeMethod.SELF
    preferred_garage_id: int | None = None
    prep_days: int = Field(default=7, ge=0)
    notes: str | None = None
    countries_of_use: list[str] = Field(default_factory=lambda: ["NL"])
    plate_lookup_data: dict[str, Any] | None = None

    _tz = field_validator("timezone")(_tz_ok)


class VehiclePatch(BaseModel):
    """Alleen meegegeven velden worden gewijzigd (model_fields_set)."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    make: str | None = None
    model: str | None = None
    license_plate: str | None = Field(default=None, max_length=20)
    build_year: int | None = Field(default=None, ge=1900, le=2100)
    location: LocationIn | None = None
    timezone: str | None = None
    driving_profile: DrivingProfile | None = None
    change_method: ChangeMethod | None = None
    preferred_garage_id: int | None = None
    prep_days: int | None = Field(default=None, ge=0)
    notes: str | None = None
    countries_of_use: list[str] | None = None
    plate_lookup_data: dict[str, Any] | None = None


class VehicleOut(BaseModel):
    id: int
    name: str
    make: str | None
    model: str | None
    license_plate: str | None  # weergavevorm
    license_plate_normalized: str | None
    build_year: int | None
    location: LocationOut
    timezone: str
    driving_profile: DrivingProfile
    change_method: ChangeMethod
    preferred_garage_id: int | None
    prep_days: int
    notes: str | None
    countries_of_use: list[str]
    plate_lookup_data: dict[str, Any] | None
    has_photo: bool
    # Alleen voor de webpagina's (cache-buster in de foto-URL); staat bewust niet in de API-uitvoer.
    photo_version: str | None = Field(default=None, exclude=True)
    created_at: datetime
    updated_at: datetime
