"""Datamodellen voor landspecifieke winterbandenregels (geen juridisch advies)."""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_STRICT = ConfigDict(extra="forbid")


class RuleType(StrEnum):
    SITUATIONAL = "situational"  # afhankelijk van de werkelijke weg-/weersomstandigheden
    PERIOD = "period"  # datumvenster
    AREA_OR_SIGNAGE = "area_or_signage"  # aangewezen gebieden/wegen of borden
    NONE = "none"  # geen winterbandenplicht


class Period(BaseModel):
    """Datumvenster per jaar; mag over de jaarwisseling lopen (bv. 15 nov - 15 apr)."""

    model_config = _STRICT

    start_month: int = Field(ge=1, le=12)
    start_day: int = Field(ge=1, le=31)
    end_month: int = Field(ge=1, le=12)
    end_day: int = Field(ge=1, le=31)

    @model_validator(mode="after")
    def _valid_dates(self) -> Period:
        # 2024 is een schrikkeljaar: valideert ook 29 februari.
        date(2024, self.start_month, self.start_day)
        date(2024, self.end_month, self.end_day)
        return self


class ReferenceLocation(BaseModel):
    """Benaderde referentieplaats voor de weercheck (coördinaten op 4 decimalen)."""

    model_config = _STRICT

    name: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation_m: int | None = None
    mountain: bool = False

    @field_validator("latitude", "longitude")
    @classmethod
    def _max_four_decimals(cls, v: float) -> float:
        if abs(v * 10_000 - round(v * 10_000)) > 1e-6:
            raise ValueError("maximaal 4 decimalen")
        return v


class Source(BaseModel):
    model_config = _STRICT

    title: str = Field(min_length=1)
    url: str

    @field_validator("url")
    @classmethod
    def _https_only(cls, v: str) -> str:
        if not v.startswith("https://") or " " in v:
            raise ValueError("alleen https-URL's zijn toegestaan")
        return v


class CountryRule(BaseModel):
    model_config = _STRICT

    code: str
    name_nl: str = Field(min_length=1)
    rule_types: list[RuleType] = Field(min_length=1)
    period: Period | None = None
    conditions_nl: str | None = None
    tires_nl: str = Field(min_length=1)
    min_tread_mm: float | None = Field(default=None, gt=0)
    alternatives_nl: str | None = None
    notes_nl: str | None = None
    sources: list[Source] = Field(min_length=1)
    checked_on: date
    confidence: Literal["high", "medium", "low"]
    reference_locations: list[ReferenceLocation] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def _iso_alpha2(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Z]{2}", v):
            raise ValueError("verwacht ISO-3166 alpha-2 in hoofdletters")
        return v

    @property
    def is_situational(self) -> bool:
        return RuleType.SITUATIONAL in self.rule_types

    @model_validator(mode="after")
    def _locations_iff_situational(self) -> CountryRule:
        n = len(self.reference_locations)
        if self.is_situational:
            if not 2 <= n <= 6:
                raise ValueError("situationele regels vereisen 2-6 referentielocaties")
        elif n:
            raise ValueError("referentielocaties alleen bij situationele regels")
        return self


class RulesFile(BaseModel):
    model_config = _STRICT

    schema_version: int = Field(alias="schema")
    disclaimer_nl: str = Field(min_length=1)
    countries: list[CountryRule]

    @model_validator(mode="after")
    def _unique_codes(self) -> RulesFile:
        codes = [c.code for c in self.countries]
        if len(codes) != len(set(codes)):
            raise ValueError("dubbele landcode")
        return self
