# Landenregels voor winterbanden

**Dit is geen juridisch advies.** De gegevens zijn een informatieve samenvatting van openbare bronnen (autoclubs, overheden, kwaliteitspers) en kunnen onvolledig of verouderd zijn. Controleer vóór vertrek altijd de officiële bron of de ANWB.

Regelgeving staat los van het meteorologische advies: het wisseladvies (engine) kent geen landenregels en wordt er nooit door beïnvloed.

## Wat is gedekt

Eerste acht landen, peildatum 2026-11-01: Duitsland (DE), Oostenrijk (AT), Frankrijk (FR), Zwitserland (CH), Italië (IT), België (BE), Luxemburg (LU) en Tsjechië (CZ). De overige acht (SI, HR, DK, SE, NO, FI, ES, PL) staan op de [roadmap](../ROADMAP.md).

## Gegevensstructuur

Bestand: `src/wisselweer/i18n/regulations/winter_tires.json` (package data), `{"schema": 1, "disclaimer_nl": ..., "countries": [...]}`. Model: `src/wisselweer/regulations/models.py` (pydantic, `extra="forbid"`). Per land:

- `rule_types` (een of meer): `situational` (hangt af van de werkelijke weg-/weersomstandigheden), `period` (datumvenster), `area_or_signage` (aangewezen wegen/gebieden of borden), `none` (geen plicht).
- `period` (start/eind maand+dag, mag over de jaarwisseling lopen), `conditions_nl`, `tires_nl`, `min_tread_mm`, `alternatives_nl` (kettingen/sneeuwsokken), `notes_nl`.
- `sources` (minimaal één, alleen https), `checked_on`, `confidence` (`high`/`medium`/`low`).
- `reference_locations` (2-6 plaatsen, met `elevation_m` en `mountain`): verplicht als en alleen als `situational` een van de `rule_types` is. Ze dienen voor de weercheck.

Boetebedragen zijn **bewust weggelaten**: bronnen botsen (Luxemburg, Frankrijk, Italië) en bedragen veranderen vaak. Een test bewaakt dat er geen bedragen in de data staan.

## Bijwerken

1. Controleer de regel bij de officiële bron en minimaal één tweede bron.
2. Pas de tekst aan, voeg bronnen toe (https) en zet `checked_on` op de datum van controle.
3. Wat onzeker of tegenstrijdig is hoort in `notes_nl`; verlaag dan `confidence`. Schrijf niets als zeker op dat niet is geverifieerd.
4. Noem geen bedragen en formuleer nooit dat een plicht "nu geldt".
5. Draai `uv run pytest -q`; de datatests valideren schema, bronnen, locatieregel en afwezigheid van bedragen.

Referentiecoördinaten komen uit het onderzoek (uit het geheugen) en zijn **benaderd**; maximaal 4 decimalen. Controleer ze bij het toevoegen van landen.

## Weercheck en de grenzen ervan

Voor landen met `situational` kijkt `regulations/conditions.py` naar de komende 72 uur voor elke referentieplaats, met dezelfde detectie als de engine (`POSSIBLE_FROST`, `POSSIBLE_SNOW`, `POSSIBLE_ICY_CONDITIONS`). Per land: `winter_conditions_expected` (sneeuw of gladheid ergens verwacht), `frost_possible` (alleen vorst), `none_expected` of `unknown` (geen bruikbare verwachting). Ontbreekt data voor een deel van de plaatsen, dan wordt de rest beoordeeld en is `partial` waar.

Let op:
- Een situationele plicht geldt voor de werkelijke weg- en weersomstandigheid ter plaatse en op dat moment. Een verwachting is geen juridische vaststelling en zegt nooit "je bent verplicht".
- Temperatuur alleen (bijvoorbeeld onder 7 graden) is geen wettelijk criterium.
- Bij landen met een periode of borden hangt de plicht van datum of wegvak af, niet van het weer.
- `in_period` zegt alleen of de datum binnen het venster valt.

## Publiceren

Standaard uit. Met `WISSELWEER_PUBLISH_COUNTRIES=true` krijgt `advice.json` de optionele velden `countries` en `countries_disclaimer` (contract: [public-advice-contract.md](public-advice-contract.md)). Dat kost per publicatie ca. 18 extra verwachtingsverzoeken (via dezelfde cache en weerbron). Uit = geen extra verzoeken en geen veld.
