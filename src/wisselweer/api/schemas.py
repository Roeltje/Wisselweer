"""Request/response-schema's van API v1."""

from __future__ import annotations

from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from wisselweer.core.messages import DEFAULT_NL
from wisselweer.core.models import (
    Advice,
    Direction,
    DrivingProfile,
    Forecast,
    ReasonItem,
    TireType,
    heading_key,
)
from wisselweer.storage.enums import AppointmentStatus, ChangeMethod
from wisselweer.weather.base import ProviderInfo


class CalculateRequest(BaseModel):
    forecast: Forecast | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    provider: str | None = Field(default=None, max_length=32)
    mounted: TireType
    profile: DrivingProfile | None = None
    lead_time_days: int = Field(default=7, ge=0, le=60)

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        has_loc = self.latitude is not None or self.longitude is not None
        if self.forecast is not None:
            if has_loc or self.provider is not None:
                raise ValueError("geef óf 'forecast' óf latitude/longitude (+provider), niet beide")
        elif self.latitude is None or self.longitude is None:
            raise ValueError("geef 'forecast' of latitude én longitude")
        return self


class SourceInfo(BaseModel):
    provider: str
    name: str
    attribution: str
    license_url: str


class AdviceResponse(BaseModel):
    api_version: str = "v1"
    advice: Advice
    messages_nl: dict[str, str] = Field(
        default_factory=dict, description="i18n-sleutel -> uitgeschreven Nederlandse tekst"
    )
    source: SourceInfo | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    rules_version: str


class ProvidersResponse(BaseModel):
    providers: list[ProviderInfo]


class _SafeDict(dict[str, object]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_nl(item: ReasonItem) -> str:
    template = DEFAULT_NL.get(item.key, item.key)
    try:
        return template.format_map(_SafeDict(item.params))
    except (ValueError, IndexError, AttributeError):
        return template


def build_messages(advice: Advice) -> dict[str, str]:
    """Teksten per sleutel; bij dezelfde sleutel met andere parameters wint de eerste."""
    items: list[ReasonItem] = [ReasonItem(key=heading_key(advice.direction, advice.status))]
    items += advice.reasons + advice.uncertainties
    items += [ReasonItem(key=w.detail_key) for w in advice.warnings]
    out: dict[str, str] = {}
    for it in items:
        out.setdefault(it.key, render_nl(it))
    return out


def build_source(forecast_provider: str | None, infos: list[ProviderInfo]) -> SourceInfo | None:
    if forecast_provider is None:
        return None
    for info in infos:
        if info.id == forecast_provider:
            return SourceInfo(
                provider=info.id,
                name=info.name,
                attribution=info.attribution,
                license_url=info.license_url,
            )
    return None


class VehicleAdviceResponse(AdviceResponse):
    plan_appointment_by: date | None = None
    mailto: str | None = Field(
        default=None, description="mailto-link naar de gekoppelde garage (alleen bij garagewissel)"
    )


class TireChangeIn(BaseModel):
    to_set_id: int
    changed_at: date
    odometer_km: int | None = Field(default=None, ge=0)
    performed_by: ChangeMethod = ChangeMethod.SELF
    garage_id: int | None = None
    cost_cents: int | None = Field(default=None, ge=0)
    notes: str | None = None
    allow_lower_odometer: bool = False


class OdometerCorrectionIn(BaseModel):
    new_km: int = Field(ge=0)
    note: str | None = None


class OdometerIn(BaseModel):
    reading_km: int = Field(ge=0)
    recorded_at: datetime | None = None
    note: str | None = None


class AppointmentCreate(BaseModel):
    garage_id: int
    target_direction: Direction
    target_period_start: date | None = None
    target_period_end: date | None = None
    notes: str | None = None


class AppointmentStatusIn(BaseModel):
    status: AppointmentStatus
    appointment_at: datetime | None = None


class MailtoResponse(BaseModel):
    mailto: str
