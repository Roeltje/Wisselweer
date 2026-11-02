from __future__ import annotations

from datetime import UTC, date, datetime

from wisselweer.web.ical import advice_event


def test_event_is_valid_all_day_with_reminder_and_escaping():
    ics = advice_event(
        vehicle_id=3,
        direction="to_winter",
        day=date(2026, 11, 9),
        summary="Banden wisselen: Auto, de; rode\\one",
        description="Regel 1\nRegel 2",
        remind_days=7,
        now=datetime(2026, 11, 2, 12, tzinfo=UTC),
    )
    assert ics.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n") and ics.endswith(
        "END:VCALENDAR\r\n"
    )
    assert "\nDTSTART;VALUE=DATE:20261109\r\n" in ics and "\nDTEND;VALUE=DATE:20261110\r\n" in ics
    assert "SUMMARY:Banden wisselen: Auto\\, de\; rode\\\\one\r\n" in ics
    assert "DESCRIPTION:Regel 1\\nRegel 2\r\n" in ics
    assert "TRIGGER:-P6DT15H\r\n" in ics  # 7 dagen vooraf om 09:00
    assert "UID:wisselweer-vehicle-3-to_winter@wisselweer\r\n" in ics
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))


def test_long_lines_are_folded_without_splitting_characters():
    ics = advice_event(
        vehicle_id=1,
        direction="to_summer",
        day=date(2027, 4, 1),
        summary="é" * 100,
        description="x",
        remind_days=0,
    )
    raw = ics.split("\r\n")
    assert any(line.startswith(" ") for line in raw)
    unfolded = ics.replace("\r\n ", "")
    assert "SUMMARY:" + "é" * 100 in unfolded and "TRIGGER:-P0DT15H" in unfolded
