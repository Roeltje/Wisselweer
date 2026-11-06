"""Demping van het landelijke advies: vasthouden van de vorige status en het statebestand.

De regio's worden gedempt door `core.stability.apply_hysteresis` (het vorige `Advice` per regio
gaat als `previous` mee naar de engine). Hier staat de demping van de samengevoegde landelijke
status, plus het (wegwerpbare) JSON-bestand waarmee de staat tussen twee berekeningen bewaard blijft.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from wisselweer.core import Advice
from wisselweer.publisher.public_schema import PublicPeriod, PublicStatus

log = logging.getLogger("wisselweer.publisher")

STATE_FILENAME = "national_state.json"
MAX_STATE_AGE = timedelta(hours=48)
# Rang van de statussen die onderling vergeleken worden; REGIONAL_DIFFERENCES en
# INSUFFICIENT_DATA staan er bewust niet in.
_RANK: dict[str, int] = {"KEEP_CURRENT": 0, "PREPARE_CHANGE": 1, "CHANGE_RECOMMENDED": 2}


class NationalHold(BaseModel):
    """Wat er van de vorige landelijke berekening onthouden wordt."""

    season: Literal["winter", "summer"]
    status: PublicStatus  # de getoonde (gedempte) status
    raw_status: PublicStatus  # de ruwe status van de vorige berekening
    streak: int = 0  # opeenvolgende berekeningen met dezelfde afwijkende ruwe status
    recommended_date: date | None = None
    recommended_period: PublicPeriod | None = None


class NationalDecision(BaseModel):
    status: PublicStatus
    raw_status: PublicStatus
    streak: int
    held: bool


def dampen_national_status(
    raw: PublicStatus,
    season: Literal["winter", "summer"],
    previous: NationalHold | None,
    confirmations: int,
) -> NationalDecision:
    """Demp de landelijke status.

    - INSUFFICIENT_DATA (nieuw of vorig), geen vorige staat of ander seizoen: direct.
    - Seizoen 'winter' en hogere rang (richting wisselen): direct.
    - Elke andere wijziging (lager, van/naar REGIONAL_DIFFERENCES, hoger in 'summer'): pas als
      dezelfde ruwe status `confirmations` berekeningen op rij voorkomt.
    """
    direct = NationalDecision(status=raw, raw_status=raw, streak=0, held=False)
    if (
        previous is None
        or previous.season != season
        or raw == "INSUFFICIENT_DATA"
        or previous.status == "INSUFFICIENT_DATA"
        or raw == previous.status
    ):
        return direct
    if season == "winter" and raw in _RANK and previous.status in _RANK:
        if _RANK[raw] > _RANK[previous.status]:
            return direct
    streak = previous.streak + 1 if previous.raw_status == raw else 1
    if streak >= confirmations:
        return direct
    return NationalDecision(status=previous.status, raw_status=raw, streak=streak, held=True)


class NationalState(BaseModel):
    regions: dict[str, Advice]
    national: NationalHold | None
    generated_at: datetime


def load_state(
    path: Path | None, now: datetime, season: Literal["winter", "summer"]
) -> NationalState | None:
    """Leest de staat; ontbrekend, kapot, oud (> 48 uur) of van een ander seizoen ⇒ None."""
    if path is None:
        return None
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        state = NationalState.model_validate(raw)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, ValidationError) as exc:
        log.warning("national_state_unreadable type=%s", type(exc).__name__)
        return None
    age = now - state.generated_at
    if age > MAX_STATE_AGE or age < -timedelta(hours=1):
        return None
    if state.national is None or state.national.season != season:
        return None
    return state


def save_state(path: Path, state: NationalState) -> None:
    """Schrijft atomisch (tmp in dezelfde map + os.replace), rechten 0640. Fouten worden gelogd."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = state.model_dump(mode="json")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o640)
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        log.warning("national_state_not_written type=%s", type(exc).__name__)
