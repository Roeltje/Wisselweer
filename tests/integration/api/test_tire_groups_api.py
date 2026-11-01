"""API: banden per groep, vervangen en leeftijd."""

from __future__ import annotations

from tests.integration.api.conftest import vehicle_body

API = "/api/v1"


def _ok(r, status=200):
    assert r.status_code == status, r.text
    return r.json()


def _vehicle(client) -> dict:
    return _ok(client.post(f"{API}/vehicles", json=vehicle_body()), 201)


def _set(client, vid: int, **body) -> dict:
    return _ok(client.post(f"{API}/vehicles/{vid}/tire-sets", json={"type": "winter", **body}), 201)


def test_set_zonder_groepen_krijgt_een_groep_van_vier(client):
    v = _vehicle(client)
    s = _set(client, v["id"])
    assert "dot_code" not in s and "purchase_date" not in s  # nu per groep
    assert [(g["quantity"], g["dot_code"], g["removed_on"]) for g in s["tire_groups"]] == [
        (4, None, None)
    ]
    assert s["tire_count"] == 4
    assert s["oldest_tire_age_years"] is None
    assert s["all_3pmsf"] is False


def test_set_met_groepen_en_leeftijd(client):
    v = _vehicle(client)
    s = _set(
        client,
        v["id"],
        tire_groups=[
            {
                "quantity": 2,
                "dot_code": "DOT AB 2319",
                "purchase_date": "2020-10-01",
                "has_3pmsf": True,
            },
            {"quantity": 2, "dot_code": "1222", "brand": "Dunlop", "has_3pmsf": True},
        ],
    )
    g = s["tire_groups"]
    assert g[0]["produced_on"] == "2019-06-03"
    assert g[0]["age_years"] > 7 and s["oldest_tire_age_years"] == g[0]["age_years"]
    assert g[1]["brand"] == "Dunlop" and g[1]["age_years"] < g[0]["age_years"]
    assert s["all_3pmsf"] is True
    again = _ok(client.get(f"{API}/tire-sets/{s['id']}"))
    assert again["tire_groups"] == g
    listed = _ok(client.get(f"{API}/vehicles/{v['id']}/tire-sets"))
    assert listed[0]["oldest_tire_age_years"] == s["oldest_tire_age_years"]


def test_oude_velden_en_ongeldige_groepen_geven_422(client):
    v = _vehicle(client)
    url = f"{API}/vehicles/{v['id']}/tire-sets"
    for body in (
        {"type": "winter", "dot_code": "2319"},
        {"type": "winter", "purchase_date": "2020-01-01"},
        {"type": "winter", "tire_groups": [{"quantity": 5}]},
        {"type": "winter", "tire_groups": [{"quantity": 0}]},
        {"type": "winter", "tire_groups": [{"positions": "XX"}]},
        {"type": "winter", "tire_groups": [{}] * 5},
    ):
        assert client.post(url, json=body).status_code == 422, body
    # De som boven 4 of onder 1 is een inhoudelijke weigering (409).
    for groups in ([{"quantity": 3}, {"quantity": 2}], []):
        r = client.post(url, json={"type": "winter", "tire_groups": groups})
        assert r.status_code == 409 and r.json()["detail"] == "invalid_operation", groups


def test_groepen_toevoegen_wijzigen_verwijderen(client):
    v = _vehicle(client)
    s = _set(client, v["id"], tire_groups=[{"quantity": 2, "dot_code": "2319"}])
    g1 = s["tire_groups"][0]
    g2 = _ok(
        client.post(
            f"{API}/tire-sets/{s['id']}/tire-groups", json={"quantity": 2, "brand": "Dunlop"}
        ),
        201,
    )
    assert g2["tire_set_id"] == s["id"] and g2["brand"] == "Dunlop"
    assert (
        client.post(f"{API}/tire-sets/{s['id']}/tire-groups", json={"quantity": 1}).status_code
        == 409
    )
    patched = _ok(
        client.patch(f"{API}/tire-groups/{g2['id']}", json={"quantity": 1, "dot_code": "1224"})
    )
    assert patched["quantity"] == 1 and patched["dot_code"] == "1224"
    assert client.patch(f"{API}/tire-groups/{g2['id']}", json={"quantity": 3}).status_code == 409
    assert client.patch(f"{API}/tire-groups/{g2['id']}", json={"quantity": 9}).status_code == 422
    assert client.patch(f"{API}/tire-groups/9999", json={"quantity": 1}).status_code == 404
    assert client.delete(f"{API}/tire-groups/{g2['id']}").status_code == 204
    # De laatste actieve groep blijft staan.
    r = client.delete(f"{API}/tire-groups/{g1['id']}")
    assert r.status_code == 409 and r.json()["detail"] == "invalid_operation"
    assert client.delete(f"{API}/tire-groups/9999").status_code == 404
    assert client.post(f"{API}/tire-sets/9999/tire-groups", json={}).status_code == 404


def test_vervangen_en_geschiedenis(client):
    v = _vehicle(client)
    s = _set(client, v["id"], tire_groups=[{"quantity": 4, "dot_code": "2319", "brand": "Oud"}])
    old = s["tire_groups"][0]
    r = _ok(
        client.post(
            f"{API}/tire-sets/{s['id']}/replace",
            json={
                "group_id": old["id"],
                "quantity": 1,
                "dot_code": "1224",
                "brand": "Nieuw",
                "replaced_on": "2026-10-01",
                "note": "lek",
            },
        )
    )
    assert r["tire_count"] == 4
    assert sorted((g["quantity"], g["dot_code"]) for g in r["tire_groups"]) == [
        (1, "1224"),
        (3, "2319"),
    ]
    assert all(g["removed_on"] is None for g in r["tire_groups"])
    full = _ok(client.get(f"{API}/tire-sets/{s['id']}?include_removed=true"))
    closed = [g for g in full["tire_groups"] if g["removed_on"]]
    assert [(g["quantity"], g["removed_on"], g["removed_note"]) for g in closed] == [
        (1, "2026-10-01", "lek")
    ]
    full_list = _ok(client.get(f"{API}/vehicles/{v['id']}/tire-sets?include_removed=true"))
    assert len(full_list[0]["tire_groups"]) == 3
    assert len(_ok(client.get(f"{API}/vehicles/{v['id']}/tire-sets"))[0]["tire_groups"]) == 2
    # Fouten
    url = f"{API}/tire-sets/{s['id']}/replace"
    assert client.post(url, json={"group_id": old["id"], "quantity": 9}).status_code == 422
    assert client.post(url, json={"group_id": old["id"], "quantity": 4}).status_code == 409
    assert client.post(url, json={"group_id": 9999}).status_code == 404
    assert client.post(url, json={}).status_code == 422
    assert client.post(f"{API}/tire-sets/9999/replace", json={"group_id": 1}).status_code == 404
