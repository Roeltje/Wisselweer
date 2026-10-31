"""Genereert de JSON-fixtures in tests/fixtures/weather/ (eenmalig; uitvoer is gecommit)."""

from datetime import date
from pathlib import Path

from tests.fixtures.builders import Day, make_forecast, repeat

OUT = Path(__file__).parent / "weather"
START = date(2026, 11, 2)

FIXTURES = {
    "mild_autumn": repeat(Day(8, 15), 14),
    "cold_snap": [*repeat(Day(7, 13), 2), *repeat(Day(1, 6), 12)],
    "persistent_frost": [Day(3, 9), *repeat(Day(-4, 1), 13)],
}

if __name__ == "__main__":
    for name, days in FIXTURES.items():
        fc = make_forecast(START, days)
        (OUT / f"{name}.json").write_text(fc.model_dump_json(indent=None) + "\n")
