# Testen

```
uv sync --extra dev
uv run pytest -q            # alles
uv run ruff check src tests scripts
```

Per map:

```
uv run pytest tests/unit
uv run pytest tests/integration
uv run pytest tests/security
```

## Indeling

| Map | Inhoud |
|---|---|
| `tests/unit/` | engine (`core`), weerproviders (met `respx`), publisher, API-schema's, backtest |
| `tests/integration/` | SQLite-opslag, services, REST-API-flow, webinterface (echte tijdelijke database via `migrate`) |
| `tests/security/` | authenticatie, CSRF, en dat `advice.json` geen persoonsgegevens bevat |
| `tests/fixtures/` | hulpcode en data: `builders.py` bouwt uurlijkse forecasts uit dagprofielen, `weather/*.json` zijn vaste forecasts, `providers/` bevat opgeslagen providerresponses, `auth.py` levert een Bearer-header |

## Uitgangspunten

- **Geen netwerk.** Providers worden getest met opgeslagen responses en `respx`; API-tests gebruiken een fake provider. Er is geen test die internet nodig heeft.
- Persoonsgegevens in fixtures zijn fictief: kenteken `XX-000-X`, e-mail `garage@example.invalid`.
- Elke test gebruikt een eigen tijdelijke database (`tmp_path`).

## Live smoke-test (optioneel, handmatig)

Niet onderdeel van de testsuite. Met een draaiende server of direct tegen een provider, bijvoorbeeld MET Norway, is een contactadres verplicht:

```
export WISSELWEER_CONTACT="https://example.invalid/contact"   # vervang door je eigen contact
uv run wisselweer serve
```

Gebruik beleefd: respecteer de cache en limieten van de bronnen (zie [providers.md](providers.md)).
