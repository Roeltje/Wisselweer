"""Kenteken -> voertuiggegevens en openstaande terugroepacties (RDW Open Data) onder /api/v1/rdw."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from wisselweer.api.deps import get_rdw
from wisselweer.rdw import (
    RdwClient,
    RdwDisabled,
    RdwNotFound,
    RdwUnavailable,
    RdwVehicle,
    normalize_plate,
)

log = logging.getLogger("wisselweer.api")

router = APIRouter(prefix="/api/v1")

RdwDep = Annotated[RdwClient, Depends(get_rdw)]


@router.get("/rdw", response_model=RdwVehicle)
def rdw_lookup(rdw: RdwDep, kenteken: Annotated[str, Query(max_length=20)]) -> RdwVehicle:
    """Merk, type, bouwjaar en openstaande terugroepacties bij een Nederlands kenteken.

    Het kenteken wordt bewust niet gelogd.
    """
    plate = normalize_plate(kenteken)
    if plate is None:
        raise HTTPException(status_code=422, detail="rdw_invalid_plate")
    try:
        return rdw.lookup(plate)
    except RdwDisabled:
        raise HTTPException(status_code=503, detail="rdw_disabled") from None
    except RdwNotFound:
        raise HTTPException(status_code=404, detail="rdw_not_found") from None
    except RdwUnavailable:
        log.warning("rdw_unavailable")
        raise HTTPException(status_code=502, detail="rdw_unavailable") from None
