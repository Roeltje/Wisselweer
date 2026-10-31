"""Hysterese tussen opeenvolgende adviezen."""

from __future__ import annotations

from wisselweer.core.config import EngineConfig
from wisselweer.core.models import Advice, AdviceStatus, Direction, ReasonItem, heading_key

_RANK = {
    AdviceStatus.KEEP_CURRENT: 0,
    AdviceStatus.PREPARE_CHANGE: 1,
    AdviceStatus.CHANGE_RECOMMENDED: 2,
}


def apply_hysteresis(new: Advice, previous: Advice | None, cfg: EngineConfig) -> Advice:
    """Demp statuswisselingen. Waarschuwingen komen altijd ongewijzigd uit `new`.

    - Verhoging richting winter: direct. Verhoging richting zomer: na `hysteresis_confirmations`.
    - Verlaging: na `hysteresis_confirmations` opeenvolgende evaluaties.
    - Richtingswissel (andere gemonteerde set), ontbrekende of onvoldoende data: reset.
    """
    raw = new.raw_status or new.status
    fresh = new.model_copy(update={"raw_status": raw, "confirm_streak": 0})

    if (
        previous is None
        or previous.direction != new.direction
        or new.status == AdviceStatus.INSUFFICIENT_DATA
        or previous.status == AdviceStatus.INSUFFICIENT_DATA
    ):
        return fresh

    held = previous.status
    if raw == held:
        return fresh

    rising = _RANK[raw] > _RANK[held]
    if rising and new.direction == Direction.TO_WINTER:
        return fresh

    streak = previous.confirm_streak + 1 if previous.raw_status == raw else 1
    needed = cfg.hysteresis_confirmations
    if streak >= needed:
        return fresh

    reasons = [
        *new.reasons,
        ReasonItem(
            key="reason.status_held", params={"streak": streak, "needed": needed, "raw": raw.value}
        ),
    ]
    return new.model_copy(
        update={
            "status": held,
            "heading": heading_key(new.direction, held),
            "recommended_date": previous.recommended_date,
            "recommended_period": previous.recommended_period,
            "plan_appointment_by": previous.plan_appointment_by,
            "reasons": reasons,
            "raw_status": raw,
            "confirm_streak": streak,
        }
    )
