# API v1

Basis-URL: `http://127.0.0.1:8000/api/v1`. Alle bodies en responses zijn JSON.

## Authenticatie

Alle `/api/v1/*`-routes vereisen authenticatie, behalve `GET /health`. Zonder geldige inlog antwoordt de API `401 {"detail":"unauthorized"}`. `/docs` en `/openapi.json` zijn alleen na login bereikbaar.

**Beheerder aanmaken (CLI, op de server):**

```
wisselweer create-admin --username beheerder   # wachtwoord via prompt (min. 10 tekens)
wisselweer reset-password --username beheerder # sessies worden daarmee ongeldig
echo "$WACHTWOORD" | wisselweer create-admin --username beheerder --password-stdin
```

Wachtwoorden gaan nooit als argument mee. Er is één beheerder; registratie via het web bestaat niet.

**Sessie + CSRF (webinterface):** `POST /login` (formulier met `username`, `password`, `csrf_token`, optioneel `next`) zet cookie `ww_session` (`HttpOnly`, `SameSite=Strict`, `Secure` via `WISSELWEER_COOKIE_SECURE=true`, 7 dagen). Muterende requests (POST/PATCH/PUT/DELETE) met sessie moeten het CSRF-token meesturen in header `X-CSRF-Token` of formveld `csrf_token`; anders `403 {"detail":"csrf_failed"}`. Templates gebruiken `{{ csrf_token() }}`. `POST /logout` beëindigt de sessie. Na 5 mislukte pogingen per IP binnen 5 minuten volgt `429`.

**Bearer-token (Home Assistant, scripts):**

```
wisselweer create-api-token --name ha     # token wordt één keer getoond
wisselweer revoke-api-token --name ha
```

```
curl -H "Authorization: Bearer wwt_..." http://127.0.0.1:8000/api/v1/vehicles
```

Requests met een Bearer-token zijn vrij van CSRF-controle. Alleen de SHA-256-hash van het token wordt opgeslagen.

**Secret key:** `WISSELWEER_SECRET_KEY`, of automatisch gegenereerd in `<data_dir>/secret_key` (rechten 600). Zie ook `SECURITY.md`.

De database (SQLite) staat in `WISSELWEER_DATA_DIR` (standaard `./data`); de map wordt aangemaakt en de migraties draaien bij het opstarten. De weerscache staat in dezelfde database, zodat meerdere voertuigen op dezelfde locatie één provider-fetch delen.

## Endpoints

| Methode | Pad | Doel | Succes |
|---|---|---|---|
| GET | `/health` | Status, versie, regelversie | 200 |
| GET | `/providers` | Weerproviders en bronvermelding | 200 |
| GET | `/public-preview` | Landelijk publiek advies berekenen zonder te publiceren (zie [publishing.md](publishing.md)) | 200 |
| GET | `/advice` | Advies voor een locatie (`mounted`, `latitude`, `longitude`, `provider`) | 200 |
| POST | `/advice/calculate` | Advies uit een meegegeven forecast of locatie | 200 |
| GET | `/vehicles` | Alle voertuigen | 200 |
| POST | `/vehicles` | Voertuig aanmaken | 201 |
| GET | `/vehicles/{id}` | Eén voertuig | 200 |
| PATCH | `/vehicles/{id}` | Voertuig deels wijzigen (alleen meegegeven velden) | 200 |
| DELETE | `/vehicles/{id}` | Voertuig met sets, wissels, standen, afspraken en snapshots verwijderen | 204 |
| GET | `/vehicles/{id}/advice` | Wisseladvies voor dit voertuig, incl. `plan_appointment_by` en `mailto` | 200 |
| GET | `/vehicles/{id}/tire-sets` | Bandensets van het voertuig | 200 |
| POST | `/vehicles/{id}/tire-sets` | Bandenset toevoegen | 201 |
| GET | `/tire-sets/{id}` | Eén set | 200 |
| PATCH | `/tire-sets/{id}` | Set wijzigen (monteren kan alleen via een wissel) | 200 |
| DELETE | `/tire-sets/{id}` | Set verwijderen (niet als gemonteerd of in de wisselhistorie) | 204 |
| POST | `/tire-sets/{id}/tread-measurements` | Profieldiepte registreren | 201 |
| GET | `/tire-sets/{id}/km` | Gereden kilometers per montageperiode | 200 |
| GET | `/vehicles/{id}/tire-changes` | Wisselhistorie | 200 |
| POST | `/vehicles/{id}/tire-changes` | Transactionele wissel (stand, historie, setstatussen, advies-reset) | 201 |
| GET | `/vehicles/{id}/odometer` | Geldige kilometerstanden (`?include_superseded=true` voor alles) | 200 |
| POST | `/vehicles/{id}/odometer` | Handmatige kilometerstand (`reading_km`, optioneel `recorded_at`, `note`) | 201 |
| POST | `/odometer/{id}/correct` | Stand corrigeren (nieuwe rij, oude verwijst ernaar) | 200 |
| GET | `/garages` | Alle garages | 200 |
| POST | `/garages` | Garage aanmaken | 201 |
| GET | `/garages/{id}` | Eén garage | 200 |
| PATCH | `/garages/{id}` | Garage deels wijzigen | 200 |
| DELETE | `/garages/{id}` | Garage verwijderen (409 bij bestaande afspraken) | 204 |
| GET | `/vehicles/{id}/appointments` | Afspraken van het voertuig | 200 |
| POST | `/vehicles/{id}/appointments` | Afspraak aanmaken (status `not_planned`) | 201 |
| PATCH | `/appointments/{id}` | Statusovergang (`status`, optioneel `appointment_at`) | 200 |
| GET | `/appointments/{id}/mailto` | `mailto:`-link voor de garage (er wordt niets verzonden) | 200 |

## Foutresponses

Alle fouten hebben de vorm `{"detail": "<code>"}` en bevatten nooit invoerwaarden, stacktraces of persoonsgegevens.

| Status | `detail` | Betekenis |
|---|---|---|
| 404 | `not_found` | Voertuig, set, garage, afspraak of stand bestaat niet |
| 409 | `invalid_operation` | Niet toegestaan in de huidige toestand; korte Nederlandse `reason` erbij (bv. tweede gemonteerde set, lagere kilometerstand, ongeldige statusovergang) |
| 409 | `conflict` | Databasebeperking geschonden |
| 422 | `validation_error` | Ongeldige invoer; `errors` bevat per fout alleen `loc` en `type` |
| 503 | `provider_unavailable` / `provider_not_configured` | Weerprovider niet bereikbaar of niet ingesteld |

## Voorbeelden

### Advies per voertuig: `GET /vehicles/1/advice`

```json
{
  "api_version": "v1",
  "advice": {
    "direction": "to_winter",
    "heading": "heading.to_winter.change_recommended",
    "status": "change_recommended",
    "warnings": [
      {"code": "possible_frost", "start": "2026-10-31T16:00:00Z", "end": "2026-11-03T17:00:00Z",
       "detail_key": "warning.frost.summer_tires"}
    ],
    "recommended_date": "2026-10-31",
    "recommended_period": null,
    "plan_appointment_by": "2026-10-31",
    "horizon_until": "2026-11-09",
    "reasons": [
      {"key": "reason.persistent_frost", "params": {"start": "2026-10-31", "days": 3}},
      {"key": "reason.appointment_urgent", "params": {"days_late": 7}}
    ],
    "uncertainties": [],
    "rules_version": "0.1.0",
    "evaluated_at": "2026-10-31T16:53:43Z",
    "forecast_provider": "metno",
    "raw_status": "change_recommended",
    "confirm_streak": 0
  },
  "messages_nl": {
    "heading.to_winter.change_recommended": "Tijd voor winterbanden",
    "reason.persistent_frost": "Vanaf 2026-10-31 wordt aanhoudende vorst verwacht (3 dagen).",
    "reason.appointment_urgent": "Plan zo snel mogelijk: de gewenste afspraakdatum is al verstreken.",
    "warning.frost.summer_tires": "Vorst mogelijk: let op, je rijdt op zomerbanden."
  },
  "source": {"provider": "metno", "name": "MET Norway", "attribution": "...", "license_url": "..."},
  "plan_appointment_by": "2026-10-31",
  "mailto": "mailto:garage@example.invalid?subject=...&body=..."
}
```

`mailto` is alleen gevuld als het voertuig `change_method: "garage"` heeft en de gekoppelde garage een e-mailadres heeft; anders `null`. Is het weer niet op te halen, dan komt er een advies met status `insufficient_data` (geen foutcode).

### Voertuig: `POST /vehicles` (201)

Request:

```json
{"name": "Testauto", "license_plate": "XX-000-X",
 "location": {"name": "Utrecht", "latitude": 52.0907, "longitude": 5.1214}}
```

Response (profiel ingekort):

```json
{
  "id": 1, "name": "Testauto", "make": null, "model": null,
  "license_plate": "XX-000-X", "license_plate_normalized": "XX000X", "build_year": null,
  "location": {"id": 1, "name": "Utrecht", "latitude": 52.0907, "longitude": 5.1214,
               "timezone": "Europe/Amsterdam"},
  "timezone": "Europe/Amsterdam",
  "driving_profile": {"kind": "commute", "slots": ["..."]},
  "change_method": "self", "preferred_garage_id": null, "prep_days": 7,
  "notes": null, "countries_of_use": ["NL"], "plate_lookup_data": null,
  "created_at": "2026-10-31T16:53:35Z", "updated_at": "2026-10-31T16:53:35Z"
}
```

Voertuigen met (afgerond op 4 decimalen) dezelfde coördinaten delen één locatie en dus één forecast-fetch.

### Wissel: `POST /vehicles/1/tire-changes` (201)

Request (`odometer_km`, `performed_by`, `garage_id`, `cost_cents`, `notes` en `allow_lower_odometer` zijn optioneel):

```json
{"to_set_id": 2, "changed_at": "2026-10-30", "odometer_km": 42000}
```

Response:

```json
{"id": 1, "vehicle_id": 1, "changed_at": "2026-10-30", "odometer_reading_id": 1,
 "from_set_id": 1, "to_set_id": 2, "performed_by": "self", "garage_id": null,
 "cost_cents": null, "notes": null}
```

De vorige gemonteerde set wordt `stored`, de nieuwe `mounted`, de kilometerstand wordt vastgelegd en bestaande advies-snapshots worden ongeldig (hysterese-reset). Bij een fout wordt niets half opgeslagen. Een lagere kilometerstand dan een eerdere stand geeft 409 `invalid_operation`.
