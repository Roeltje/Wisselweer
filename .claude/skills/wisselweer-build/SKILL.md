---
name: wisselweer-build
description: Bouwwerkwijze voor Wisselweer — architect (Opus) delegeert hapklare fases aan Sonnet/Haiku-subagenten, controleert, test en pusht. Gebruik bij elke nieuwe bouwfase of uitbreiding van Wisselweer.
---

# Wisselweer bouwen

## Rollen
- **Architect (hoofdsessie)**: bewaakt `ARCHITECTURE.md`, splitst werk, reviewt, draait tests, commit/pusht. Schrijft zelf geen grote hoeveelheden code.
- **Bouwer (subagent, `model: sonnet`)**: implementeert één fase of deelmodule. Gebruik **haiku** voor mechanisch werk (docs, fixtures, vertalingen, configbestanden).

## Per fase
1. Controleer `docs/STATUS.md` (wat staat, wat niet).
2. Geef de bouwer een brief met: doel, exacte bestanden/modules, contract uit `ARCHITECTURE.md`, "klaar = `uv run pytest <pad>` groen + ruff schoon", en de harde regels hieronder. Laat de bouwer een korte samenvatting (≤15 regels) teruggeven, geen code-dumps.
3. Review: `git diff --stat`, steekproef van kernbestanden, zelf `uv run pytest -q` en `uv run ruff check`.
4. Werk `docs/STATUS.md` bij, commit (`feat(<module>): …`), push. Vóór de eerste werkende release direct naar `main`; daarna alleen via PR.

## Harde regels
- Python 3.12+ via [`uv`](https://docs.astral.sh/uv/) (`uv sync --extra dev`, daarna `uv run pytest`). Zorg dat `uv` op je PATH staat.
- `wisselweer.core` importeert nooit FastAPI, SQLAlchemy, httpx of IO.
- Tests zonder netwerk (fixtures, `respx`). Nooit testresultaten verzinnen.
- Geen e-mailadressen, API-keys, kentekens of andere persoonsgegevens in de repo (ook niet in fixtures: gebruik `XX-000-X`, `garage@example.invalid`).
- Geen ongevraagde features, geen onnodige abstracties. Nederlandse UI-teksten via i18n-bestanden.
- Drempels zijn heuristieken: configureerbaar en als ongevalideerd gedocumenteerd.

## Fases
1. Core-engine + fixtures + tests  2. Weerproviders + cache + API-basis  3. Database + voertuigen/banden/garages
4. Privé-webinterface + auth  5. Publisher  6. Deployment + docs + security-review
