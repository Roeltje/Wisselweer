# Changelog

Alle noemenswaardige wijzigingen per versie. Nummering volgens [Semantic Versioning](https://semver.org/lang/nl/);
zolang de versie onder 1.0 is, kan een minor-versie nog wijzigingen bevatten die niet terugwaarts compatibel zijn.
Hoe een release gemaakt wordt: [docs/releasing.md](docs/releasing.md).

## [Unreleased]

### Nieuw
- **Sneeuw of ijzel op korte termijn**: met zomerbanden gemonteerd geeft sneeuw of ijzelneerslag (minimaal 2 uur, parameter `short_term_wintry_min_hours`) binnen 72 uur direct "Tijd om te wisselen" met datum vandaag, ook buiten het winterseizoen. Gladheid alleen door dauwpunt blijft een waarschuwing. `rules_version` is nu `0.2.0`.

### Opgelost
- **Landelijk advies sprong heen en weer** binnen een dag: de hysterese werkte landelijk nooit. Regio's en de landelijke status worden nu gedempt via `<DATA_DIR>/national_state.json` (wegwerpbaar, geen back-up nodig); verlagingen en wijzigingen van/naar "regionale verschillen" vergen twee opeenvolgende berekeningen, verhogingen richting winter blijven direct.

### Gewijzigd
- **Landelijk advies**: gebruikt een landelijk rijprofiel (werkdagen 07:00–09:00 en 16:00–19:00, za/zo 10:00–18:00, gebaseerd op CBS ODiN; ongevalideerde heuristiek) in plaats van "overdag" 09:00–17:00.
- **`advice.json`**: de vooruitblik heeft een optioneel veld `temp_drive_c` (gemiddelde temperatuur op de rijmomenten, 1 decimaal); terugwaarts compatibel.

## [0.2.0] - 2026-11

Eerste release met een Docker-image op GHCR.

### Nieuw
- **Docker**: image `ghcr.io/roeltje/wisselweer` (amd64 en arm64) met herkomstverklaring en SBOM, installatiescript `docker-install.sh` en een aparte publisher-service (#20).
- **Kenteken opzoeken bij de RDW**: merk, type en bouwjaar vooraf invullen en openstaande terugroepacties tonen; het kentekenveld staat bovenaan het voertuigformulier (#26).
- **Zet in agenda**: een `.ics`-bestand per voertuig met de wisseldag en een herinnering, voorbereidingstijd vooraf (#29).
- **Talen**: de interface is volledig beschikbaar in het Nederlands, Vlaams, Engels en Duits; de taal volgt de browser tot je zelf kiest (#22).
- **Banden per groep**, merk- en typesuggesties, 3PMSF per band en een handleiding voor Home Assistant (#17).
- **Winterbandenregels voor 16 landen** (DE, AT, FR, CH, IT, BE, LU, CZ, SI, HR, DK, SE, NO, FI, ES, PL) met bronnen en weercheck, plus een 14-daagse vooruitblik in `advice.json` (#10, #28).
- **Foto per voertuig**: verkleind in de browser, metadata gestript, nooit gepubliceerd (#18, #19).
- **Locatie zoeken** op adres of plaats (Nominatim) en "Gebruik mijn locatie" (#16).
- Symbool achter 3PMSF en M+S in de teksten (#23).

### Gewijzigd
- **Nieuwe huisstijl**, gelijk aan wisselweer.nl: nieuw logo (band met sneeuwvlok en zon), seizoensfoto op dashboard en login, tabbalk onderaan op mobiel, themaknop met drie standen (#15, #24, #25).
- Icoon en naam op het beginscherm van iOS en Android (#21).
- Bij zelf wisselen "Plan het wisselen vóór …" in plaats van een garageafspraak; ligt die datum vandaag of eerder, dan "zo snel mogelijk". Op de voertuigpagina staat waarom het advies per auto kan afwijken van het landelijke advies (#29).
- Het commando `wisselweer` werkt direct na de installatie (#14).

### Beveiliging en onderhoud
- Hardening na een audit van de app en de documentatie (#12, #13).
- CI, issue-templates, CONTRIBUTING en Dependabot (#7, #8, #9).

## [0.1.0] - 2026-10-31

Eerste versie (MVP): advies per voertuig op basis van meerdere weerbronnen, voertuigen, bandensets,
garages en afspraken, privé-webinterface met login, REST-API, publicatie van een landelijk
`advice.json` en installatie op Debian/Ubuntu (LXC).

[0.2.0]: https://github.com/Roeltje/Wisselweer/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Roeltje/Wisselweer/releases/tag/v0.1.0
