"""`PublicAdvice`: het enige datamodel dat naar buiten gaat (docs/public-advice-contract.md).

Bewust een allowlist: `extra="forbid"` en `frozen=True`. Dit model wordt uitsluitend gebouwd uit
berekende landelijke waarden, nooit uit ORM-objecten of gebruikersdata.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator, model_validator

PublicStatus = Literal[
    "KEEP_CURRENT",
    "PREPARE_CHANGE",
    "CHANGE_RECOMMENDED",
    "REGIONAL_DIFFERENCES",
    "INSUFFICIENT_DATA",
]
# Per regio kan de status nooit "regionale verschillen" zijn.
RegionStatus = Literal["KEEP_CURRENT", "PREPARE_CHANGE", "CHANGE_RECOMMENDED", "INSUFFICIENT_DATA"]

_STRICT = ConfigDict(extra="forbid", frozen=True)


class PublicPeriod(BaseModel):
    model_config = _STRICT

    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> PublicPeriod:
        if self.end < self.start:
            raise ValueError("periode-einde ligt voor het begin")
        return self


class PublicRegion(BaseModel):
    model_config = _STRICT

    name: str
    status: RegionStatus


class PublicSource(BaseModel):
    model_config = _STRICT

    name: str
    attribution: str
    license_url: str


def _utc(v: datetime) -> datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("datetime moet tijdzone-bewust zijn")
    return v.astimezone(UTC)


def _z(v: datetime) -> str:
    return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class PublicAdvice(BaseModel):
    model_config = _STRICT

    schema_version: Literal[1] = 1
    country: Literal["NL"] = "NL"
    locale: Literal["nl-NL"] = "nl-NL"
    next_season: Literal["winter", "summer"]
    heading: str
    status: PublicStatus
    status_label: str
    summary: str
    recommended_date: date | None = None
    recommended_period: PublicPeriod | None = None
    regional_variation: bool
    regions: list[PublicRegion]
    forecast_until: date | None = None
    generated_at: datetime
    stale_after: datetime
    source: PublicSource
    rules_version: str

    @field_validator("generated_at", "stale_after")
    @classmethod
    def _aware_utc(cls, v: datetime) -> datetime:
        return _utc(v)

    @field_serializer("generated_at", "stale_after")
    def _ser_z(self, v: datetime) -> str:
        return _z(v)

    @model_validator(mode="after")
    def _date_xor_period(self) -> PublicAdvice:
        if self.recommended_date is not None and self.recommended_period is not None:
            raise ValueError("recommended_date en recommended_period sluiten elkaar uit")
        return self
