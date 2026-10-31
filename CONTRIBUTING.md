# Bijdragen aan Wisselweer

Bedankt dat je wilt bijdragen. Lees eerst [SECURITY.md](SECURITY.md) voor beveiligingsproblemen: die meld je vertrouwelijk, niet als openbaar issue.

## Opzetten

Vereist Python 3.12+ en [uv](https://docs.astral.sh/uv/).

```
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Zie [docs/testing.md](docs/testing.md) voor de details van de tests.

## Werkwijze

1. Maak een branch vanaf `main`, bijvoorbeeld `fix/...` of `feat/...`.
2. Maak je wijziging, met tests waar het kan.
3. Draai `uv run pytest` en `uv run ruff check .` en `uv run ruff format --check .`.
4. Open een pull request. Vul de checklist in de PR-template in.

## Ontwerpuitgangspunten

- **Pure engine.** `wisselweer.core` bevat de adviesberekening zonder I/O, zodat die los test- en uitlegbaar blijft.
- **Geen persoonsgegevens in publieke output.** Het landelijke `advice.json` bevat alleen anoniem advies; geen kentekens, namen, e-mailadressen of locaties.
- **Geen secrets in de repository.** Sleutels en tokens horen in `.env` of de omgeving, nooit in code, tests of voorbeelden.
- **Heuristieken zijn ongevalideerd en gedocumenteerd.** Adviesregels staan beschreven in [docs/advice-rules.md](docs/advice-rules.md), inclusief wat ze niet zijn.

## Licentie

Wisselweer valt onder de [GNU Affero General Public License v3.0](LICENSE). Door een bijdrage in te dienen ga je akkoord dat die onder dezelfde licentie valt.

## Documentatie

Overzicht van de documentatie staat in de [README](README.md) en in de map [docs/](docs/).
