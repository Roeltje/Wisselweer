# Testen

```
uv sync --extra dev
uv run pytest -q            # alles
uv run ruff check .
uv run ruff format --check .
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

## Docker

De pytest-suite test de Docker-bestanden statisch (`tests/unit/test_docker_files.py`: hardening, localhost-binding, geen SFTP-sleutel in de webapp) en `deploy/docker-install.sh` met een nep-`docker` en nep-`curl` (`tests/unit/test_docker_install.py`). Het echte image wordt alleen in CI gebouwd en gestart: de job `docker` in `.github/workflows/ci.yml` draait het installatiescript (nieuwe installatie en update) en controleert health, UID, read-only root-fs, `.env`-rechten, `create-admin`, de back-up en het stoppen van de publisher. Lokaal kun je hetzelfde doen met `docker build -t ghcr.io/roeltje/wisselweer:ci .` en daarna `IMAGE_TAG=ci WISSELWEER_ASSETS_DIR=$PWD WISSELWEER_SKIP_PULL=1 WISSELWEER_CONTACT=https://example.invalid/contact bash deploy/docker-install.sh /tmp/ww-test`.

## Live smoke-test (optioneel, handmatig)

Niet onderdeel van de testsuite. Met een draaiende server of direct tegen een provider, bijvoorbeeld MET Norway, is een contactadres verplicht:

```
export WISSELWEER_CONTACT="https://example.invalid/contact"   # vervang door je eigen contact
uv run wisselweer serve
```

Gebruik beleefd: respecteer de cache en limieten van de bronnen (zie [providers.md](providers.md)).
