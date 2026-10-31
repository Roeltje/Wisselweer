# Backtesten

`wisselweer backtest` speelt opgeslagen voorspellingen opnieuw af door de adviesengine. Het doel is om te zien hoe het advies zich in het verleden gedroeg, niet om het te "bewijzen".

> **De adviesregels zijn ongevalideerde heuristieken** (zie [advice-rules.md](advice-rules.md)). Een backtest levert getallen en datums, geen nauwkeurigheidspercentage, en is geen validatie.

## Waarnemingen versus voorspellingen

- **Historische waarnemingen** zeggen wat het weer *werkelijk* was.
- **Historische voorspellingen** zeggen wat op een bepaald moment *verwacht* werd. Alleen die kent de gebruiker op het beslismoment.

Een backtest die waarnemingen of een heranalyse (achteraf gemodelleerd weer) als "voorspelling" invoert, is vals-optimistisch: de toekomst is dan al bekend, en de echte onzekerheid van een 7-daagse verwachting verdwijnt. Daarom bewaart de app bij elke fetch een `forecast_snapshot` (provider, locatie, ophaalmoment, volledige forecast) en bij elk advies een `advice_snapshot`.

## Wat `replay` doet

Voor één locatie en provider, chronologisch:

1. beslismoment `now = snapshot.fetched_at`;
2. de engine krijgt alleen die snapshot en het vorige advies (zodat hysterese meeloopt);
3. nooit een latere snapshot en geen waarnemingen (afgedwongen met een assert; getest in `tests/unit/test_backtest.py`).

`evaluate_against_observations` legt de uitkomst naast waargenomen daggemiddelden en rapporteert alleen:

- datum waarop het advies voor het eerst `CHANGE_RECOMMENDED` werd en de toen geadviseerde datum;
- begin van de eerste waargenomen koude (naar winter) of warme (naar zomer) reeks met dezelfde drempels uit `EngineConfig` (daggemiddelde, niet gewogen naar rijmomenten) en het verschil in dagen;
- aantal statuswisselingen en flip-flops (status A, dan B, dan weer A).

## CLI

```
wisselweer backtest --latitude 52.0907 --longitude 5.1214 [--provider metno] [--mounted summer] [--since 2026-10-01]
```

Leest `forecast_snapshot` uit de lokale database (geen netwerk) en print per beslismoment datum, richting, status en datum of periode. De waarnemingsvergelijking is een Python-functie (`wisselweer.backtest`), nog niet in de CLI.

Snapshots ontstaan pas als de app draait en adviezen berekent; zonder verzamelde data is er niets af te spelen.

## Later valideren

Nodig, en nog niet gedaan:

- maanden tot jaren aan snapshots over meerdere winters en locaties verzamelen;
- vergelijken met waargenomen temperaturen (KNMI, eigen station) en met het werkelijke moment waarop gebruikers wisselden of banden-/weerinstanties adviseerden;
- drempels in `EngineConfig` pas aanpassen na zo'n vergelijking en `rules_version` verhogen;
- onderscheid maken tussen "te vroeg", "te laat" en "heen en weer"; het aantal flip-flops zegt iets over stabiliteit, niet over juistheid.
