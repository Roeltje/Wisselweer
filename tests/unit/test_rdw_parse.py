from __future__ import annotations

import pytest

from wisselweer.rdw import (
    RdwNotFound,
    RdwUnavailable,
    normalize_plate,
    parse_open_references,
    parse_vehicle,
)


@pytest.mark.parametrize(
    ("raw", "plate"),
    [
        ("ab-123-c", "AB123C"),
        (" 7-XZN-21 ", "7XZN21"),
        ("12.AB.34", "12AB34"),
        ("", None),
        ("AB", None),
        ("AB-123-CDEFG", None),
        ("AB'1;--", None),
        ("ÄB-12-CD", None),
    ],
)
def test_normalize_plate(raw, plate):
    assert normalize_plate(raw) == plate


def test_parse_vehicle_titels_en_bouwjaar():
    v = parse_vehicle(
        "X",
        [{"merk": "BMW", "handelsbenaming": "X5 XDRIVE40E", "datum_eerste_toelating": "20190101"}],
    )
    assert (v.make, v.model, v.build_year, v.open_recall) == ("BMW", "X5 XDRIVE40E", 2019, None)


def test_parse_vehicle_fouten():
    with pytest.raises(RdwNotFound):
        parse_vehicle("X", [])
    with pytest.raises(RdwUnavailable):
        parse_vehicle("X", {"error": True})


def test_open_references_alleen_openstaand_gevalideerd_en_begrensd():
    rows = [{"referentiecode_rdw": f"MGP{i:06d}", "code_status": "O"} for i in range(8)]
    rows += [
        {"referentiecode_rdw": "MGP999999", "code_status": "P"},
        {"referentiecode_rdw": "x') or (1=1", "code_status": "O"},
    ]
    refs = parse_open_references(rows)
    assert len(refs) == 5 and "MGP999999" not in refs and all(r.startswith("MGP") for r in refs)
