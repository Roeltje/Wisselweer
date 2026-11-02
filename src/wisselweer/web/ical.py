"""Agenda-item (iCalendar, RFC 5545) voor het wisseladvies van een voertuig.

Eén hele-dag-afspraak op de aanbevolen wisseldatum (of het begin van de periode) met een
herinnering zoveel dagen vooraf als de voorbereidingstijd van het voertuig. Geen externe dienst:
de gebruiker downloadt het bestand en opent het in de eigen agenda. De UID is per voertuig en
richting vast, zodat agenda's die dat ondersteunen een nieuwere versie als update zien.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from wisselweer import __version__

_MAX_LINE = 75  # octetten per regel, daarna vouwen


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Vouwt een regel op maximaal 75 octetten (UTF-8), zonder een teken te splitsen."""
    out: list[str] = []
    current, size = "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        limit = _MAX_LINE if not out else _MAX_LINE - 1  # vervolgregels beginnen met een spatie
        if size + n > limit:
            out.append(current)
            current, size = "", 0
        current += ch
        size += n
    out.append(current)
    return "\r\n ".join(out)


def advice_event(
    *,
    vehicle_id: int,
    direction: str,
    day: date,
    summary: str,
    description: str,
    remind_days: int,
    now: datetime | None = None,
) -> str:
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    days = max(1, remind_days)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//Wisselweer//Wisselweer {__version__}//NL",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:wisselweer-vehicle-{vehicle_id}-{direction}@wisselweer",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
        f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{_escape(description)}",
        "TRANSP:TRANSPARENT",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escape(summary)}",
        # Om 09:00, `days` dagen vóór de wisseldag (een hele-dag-afspraak begint om 00:00).
        f"TRIGGER:-P{days - 1}DT15H",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "".join(_fold(line) + "\r\n" for line in lines)
