"""Gedrag van POST /vehicles/{id}/odometer zoals docs/home-assistant.md het beschrijft."""

from __future__ import annotations

import re
from pathlib import Path

from tests.integration.api.conftest import vehicle_body

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[3]


def test_odometer_veldnamen_en_weigeringen(client):
    vid = client.post(f"{API}/vehicles", json=vehicle_body()).json()["id"]
    url = f"{API}/vehicles/{vid}/odometer"
    r = client.post(url, json={"reading_km": 12000, "note": "Home Assistant"})
    assert r.status_code == 201
    body = r.json()
    assert body["reading_km"] == 12000 and body["note"] == "Home Assistant"
    assert body["source"] == "manual"
    # Hoger mag; gelijk mag ook (maar levert een dubbele regel); lager wordt geweigerd.
    assert client.post(url, json={"reading_km": 12050}).status_code == 201
    assert client.post(url, json={"reading_km": 12050}).status_code == 201
    low = client.post(url, json={"reading_km": 11000})
    assert low.status_code == 409 and low.json()["detail"] == "invalid_operation"
    assert client.post(url, json={"reading_km": -1}).status_code == 422
    assert client.post(url, json={"reading_km": "abc"}).status_code == 422
    assert client.post(url, json={"km": 13000}).status_code == 422  # verkeerde veldnaam
    assert [r["reading_km"] for r in client.get(url).json()] == [12000, 12050, 12050]


def test_homeassistant_doc_is_gelinkt_en_bevat_alleen_voorbeeldadressen():
    doc = (ROOT / "docs" / "home-assistant.md").read_text(encoding="utf-8")
    assert "create-api-token --name homeassistant" in doc
    assert "/api/v1/vehicles/1/odometer" in doc and "reading_km" in doc
    assert "Bearer wwt_" in doc and "secrets.yaml" in doc and "rest_command" in doc
    for brand in ("Kia", "Hyundai", "Tesla", "Volkswagen", "BMW", "Renault"):
        assert brand in doc
    hosts = set(re.findall(r"https?://([\w.-]+)", doc))
    assert hosts == {"wisselweer.example.invalid"}
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", doc)  # geen e-mailadressen
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", doc)  # geen IP-adressen
    for name in ("README.md", "docs/api.md"):
        assert "home-assistant.md" in (ROOT / name).read_text(encoding="utf-8"), name
