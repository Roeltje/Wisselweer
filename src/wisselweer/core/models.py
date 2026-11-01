"""Datamodellen van de adviesengine (alleen pydantic + stdlib)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from wisselweer.core.config import EngineConfig
from wisselweer.core.rules_version import RULES_VERSION


class TireType(StrEnum):
    SUMMER = "summer"
    WINTER = "winter"
    ALL_SEASON = "all_season"


class Direction(StrEnum):
    TO_WINTER = "to_winter"
    TO_SUMMER = "to_summer"
    NONE = "none"


class AdviceStatus(StrEnum):
    KEEP_CURRENT = "keep_current"
    PREPARE_CHANGE = "prepare_change"
    CHANGE_RECOMMENDED = "change_recommended"
    INSUFFICIENT_DATA = "insufficient_data"


class WarningCode(StrEnum):
    POSSIBLE_FROST = "possible_frost"
    POSSIBLE_SNOW = "possible_snow"
    POSSIBLE_ICY_CONDITIONS = "possible_icy_conditions"
    FORECAST_UNAVAILABLE = "forecast_unavailable"
    FORECAST_STALE = "forecast_stale"


class PrecipType(StrEnum):
    RAIN = "rain"
    SNOW = "snow"
    SLEET = "sleet"
    FREEZING_RAIN = "freezing_rain"
    NONE = "none"
    UNKNOWN = "unknown"


def _aware_utc(v: datetime) -> datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("datetime moet tijdzone-bewust zijn")
    return v.astimezone(UTC)


class HourlyPoint(BaseModel):
    """Eén uur. None betekent: niet geleverd door de provider (nooit invullen)."""

    time: datetime
    temperature_c: float | None = None
    dew_point_c: float | None = None
    humidity_pct: float | None = None
    precip_mm: float | None = None
    precip_probability_pct: float | None = None
    precip_type: PrecipType | None = None
    snow_cm: float | None = None
    snow_depth_cm: float | None = None
    wind_speed_ms: float | None = None

    _utc = field_validator("time")(_aware_utc)


class Forecast(BaseModel):
    provider: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = Field(description="IANA-tijdzone, bv. Europe/Amsterdam")
    fetched_at: datetime
    valid_until: datetime | None = None
    is_stale: bool = False
    hourly: list[HourlyPoint] = Field(default_factory=list)
    available_variables: set[str] = Field(default_factory=set)

    _utc_fetched = field_validator("fetched_at")(_aware_utc)

    @field_validator("valid_until")
    @classmethod
    def _utc_valid(cls, v: datetime | None) -> datetime | None:
        return None if v is None else _aware_utc(v)

    @field_validator("timezone")
    @classmethod
    def _tz_ok(cls, v: str) -> str:
        from zoneinfo import ZoneInfo

        ZoneInfo(v)
        return v

    def horizon_end(self) -> datetime | None:
        """Einde van de laatste geleverde uur (None zonder data)."""
        if not self.hourly:
            return None
        return max(p.time for p in self.hourly) + timedelta(hours=1)


class ProfileKind(StrEnum):
    COMMUTE = "commute"
    DAYTIME = "daytime"
    WEEKEND = "weekend"
    CUSTOM = "custom"


class DriveSlot(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0 = maandag")
    start: time
    end: time

    @model_validator(mode="after")
    def _order(self) -> DriveSlot:
        if self.end <= self.start:
            raise ValueError("slot-einde moet na slot-begin liggen (lokale tijd, binnen één dag)")
        return self


class DrivingProfile(BaseModel):
    kind: ProfileKind = ProfileKind.COMMUTE
    slots: list[DriveSlot] = Field(default_factory=list)

    @classmethod
    def commute(cls) -> DrivingProfile:
        """Ma–vr 07:00–09:00 en 16:00–19:00."""
        slots = [
            DriveSlot(weekday=d, start=time(*s), end=time(*e))
            for d in range(5)
            for s, e in (((7, 0), (9, 0)), ((16, 0), (19, 0)))
        ]
        return cls(kind=ProfileKind.COMMUTE, slots=slots)

    @classmethod
    def daytime(cls) -> DrivingProfile:
        """Alle dagen 09:00–17:00."""
        return cls(
            kind=ProfileKind.DAYTIME,
            slots=[DriveSlot(weekday=d, start=time(9), end=time(17)) for d in range(7)],
        )

    @classmethod
    def weekend(cls) -> DrivingProfile:
        """Za en zo 09:00–18:00."""
        return cls(
            kind=ProfileKind.WEEKEND,
            slots=[DriveSlot(weekday=d, start=time(9), end=time(18)) for d in (5, 6)],
        )

    @classmethod
    def custom(cls, slots: list[DriveSlot]) -> DrivingProfile:
        return cls(kind=ProfileKind.CUSTOM, slots=slots)


class ReasonItem(BaseModel):
    """i18n-sleutel + parameters (JSON-serialiseerbaar). Geen hardcoded zinnen."""

    key: str
    params: dict[str, Any] = Field(default_factory=dict)


class AdviceWarning(BaseModel):
    code: WarningCode
    start: datetime
    end: datetime
    detail_key: str


class Advice(BaseModel):
    direction: Direction
    heading: str
    status: AdviceStatus
    warnings: list[AdviceWarning] = Field(default_factory=list)
    recommended_date: date | None = None
    recommended_period: tuple[date, date] | None = None
    plan_appointment_by: date | None = None
    horizon_until: date | None = None
    reasons: list[ReasonItem] = Field(default_factory=list)
    uncertainties: list[ReasonItem] = Field(default_factory=list)
    rules_version: str = RULES_VERSION
    evaluated_at: datetime
    forecast_provider: str | None = None
    # Hysterese-administratie: `status` is de gestabiliseerde status; `raw_status` de
    # ongedempte uitkomst van deze evaluatie; `confirm_streak` het aantal opeenvolgende
    # evaluaties waarin raw_status afweek van status in dezelfde richting.
    raw_status: AdviceStatus | None = None
    confirm_streak: int = 0


class AdviceInput(BaseModel):
    forecast: Forecast | None
    mounted: TireType | None
    profile: DrivingProfile = Field(default_factory=DrivingProfile.commute)
    now: datetime
    previous: Advice | None = None
    lead_time_days: int = Field(default=7, ge=0)
    config: EngineConfig = Field(default_factory=EngineConfig)

    _utc_now = field_validator("now")(_aware_utc)


def heading_key(direction: Direction, status: AdviceStatus) -> str:
    return f"heading.{direction.value}.{status.value}"
