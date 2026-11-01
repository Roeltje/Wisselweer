"""Datumvensters (met jaarwisseling) en Nederlandse weergave."""

from __future__ import annotations

from datetime import date

from wisselweer.regulations.models import Period

_MONTHS = (
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
)  # fmt: skip


def in_period(period: Period, today: date) -> bool:
    """True als `today` binnen het venster valt (grenzen inclusief; jaarwisseling ondersteund)."""
    md = (today.month, today.day)
    start = (period.start_month, period.start_day)
    end = (period.end_month, period.end_day)
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end


def period_label_nl(period: Period) -> str:
    return (
        f"{period.start_day} {_MONTHS[period.start_month - 1]} – "
        f"{period.end_day} {_MONTHS[period.end_month - 1]}"
    )
