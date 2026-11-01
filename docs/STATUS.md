# Status

| Fase | Onderdeel | Status |
|---|---|---|
| 0 | Architectuur, logo, bouw-skill | klaar |
| 1 | Core-engine + tests | klaar |
| 2 | Weerproviders, cache, API-basis (103 tests totaal; live getest) | klaar — SQLite-cache volgt in fase 3; KNMI-veldnamen en Bright Sky/WU-licentie nog verifiëren |
| 3 | Database, voertuigen, banden, garages, REST-API (154 tests) | klaar — auth volgt in fase 4 |
| 4 | Privé-webinterface + auth (incl. i18n-basis, providerkeuze, modelvergelijking) | klaar |
| 5 | Landelijk advies, publisher (lokaal + SFTP), publicatie van `advice.json` | klaar |
| 6 | Docker, Debian/Ubuntu-LXC (app), backtest, docs | klaar — native LXC-installatie (Debian 13) en SFTP-publicatie naar een aparte server in de praktijk getest; Docker nog niet getest |
