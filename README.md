<p align="center"><img src="branding/logo.svg" alt="Wisselweer-logo" width="120"></p>

# Wisselweer

*Het juiste moment om te wisselen.*

Wisselweer adviseert wanneer je van zomer- naar winterbanden wisselt (en terug), op basis van de weersverwachting voor jouw locatie en jouw rijmomenten.

> **Status: MVP, in ontwikkeling.** De adviesregels zijn ongevalideerde heuristieken: niet gekalibreerd aan bandenprestaties, ongevallen of klimaatdata. Zie [docs/advice-rules.md](docs/advice-rules.md). Het advies is indicatief en geen veiligheidsgarantie.

## Wat is het

- **Engine** (`wisselweer.core`): pure, uitlegbare adviesberekening. Geen percentages of gladheidskansen; elke uitkomst heeft redenen en onzekerheden.
- **Self-hosted app** (`wisselweer.api` + `wisselweer.web`): beheer van voertuigen, bandensets, garages en advies, met lokale SQLite-database en privé webinterface.
- **Landelijk `advice.json`**: een anoniem landelijk advies volgens [docs/public-advice-contract.md](docs/public-advice-contract.md). De privé-app duwt dat bestand naar een map of via SFTP naar een server. De publieke site van wisselweer.nl wordt apart onderhouden; iedereen kan het bestand gebruiken (eigen site, Home Assistant). De app heeft geen verbinding met zo'n site.

## Functies

- Wisseladvies per voertuig: richting volgt de gemonteerde set, met waarschuwingen (vorst, sneeuw, gladheid), datum of periode, stabiliteit (hysterese) en "plan een afspraak uiterlijk"-datum.
- Meerdere voertuigen en bandensets, profieldiepte- en kilometerregistratie, wisselhistorie.
- Garages en afspraken; een `mailto:`-link voor de garage (de app verstuurt zelf niets).
- REST API (`/api/v1`) met sessie of Bearer-token, bijvoorbeeld voor Home Assistant: [docs/api.md](docs/api.md).
- Landelijk advies en publicatie van `advice.json`: [docs/publishing.md](docs/publishing.md).
- Vergelijking van weerbronnen (diagnostisch, er wordt niets gecombineerd) en een backtest-commando: [docs/backtesting.md](docs/backtesting.md).
- Nederlandse interface via i18n-bestanden; er zijn ook `nl-BE`, `en` en `de-DE`-bestanden aanwezig, maar de interface is nog niet volledig meertalig.

## Snelle start (lokaal)

Vereist Python 3.12+ en [uv](https://docs.astral.sh/uv/).

```
uv sync
cp .env.example .env            # zet minstens WISSELWEER_CONTACT
uv run wisselweer create-admin --username jouwnaam
uv run wisselweer serve         # http://127.0.0.1:8000
```

De server luistert standaard alleen lokaal. Zie [SECURITY.md](SECURITY.md) voor toegang van buitenaf.

Installeren als dienst: [Debian/Ubuntu-LXC](docs/install-lxc.md) (in de praktijk getest op Debian 13) of [Docker](docs/install-docker.md) (nog niet getest).

## Configuratie

Alle instellingen staan als `WISSELWEER_*`-variabelen in [`.env.example`](.env.example) (host, poort, data-map, weerbron, API-keys, publicatie). Secrets horen alleen in `.env` of de omgeving, nooit in de repository.

## Weerbronnen en bronvermelding

| Bron | Gebruik | Licentie/bronvermelding |
|---|---|---|
| MET Norway (standaard) | verwachting | CC BY 4.0, "Weerdata: MET Norway" |
| Open-Meteo | verwachting | CC BY 4.0; de gratis host is niet-commercieel |
| Bright Sky (DWD) | verwachting en waarnemingen | DWD open data; publieke instantie niet-commercieel |
| KNMI Data Platform | waarnemingen (API-key nodig); verwachting niet beschikbaar | CC BY 4.0 |
| Weather Underground PWS | eigen station, waarnemingen (adapter; nog niet in het advies gebruikt) | voorwaarden van Weather Underground |

Details, variabelen en beperkingen: [docs/providers.md](docs/providers.md). Gebruik van MET Norway vereist een contactadres in de User-Agent (`WISSELWEER_CONTACT`).

## Privacy

Voertuig-, band-, garage- en locatiegegevens blijven in je eigen database. Naar weerbronnen gaan alleen afgeronde coördinaten (4 decimalen) en, bij MET Norway, je contactgegeven in de User-Agent. Het gepubliceerde `advice.json` bevat uitsluitend een anoniem landelijk advies, gebouwd uit een allowlist; er gaan geen kentekens, namen of e-mailadressen in en geen eigen locaties.

## Documentatie

- [ARCHITECTURE.md](ARCHITECTURE.md): ontwerp en contract
- [docs/STATUS.md](docs/STATUS.md): voortgang
- [ROADMAP.md](ROADMAP.md)
- [docs/advice-rules.md](docs/advice-rules.md), [docs/providers.md](docs/providers.md), [docs/api.md](docs/api.md)
- [docs/publishing.md](docs/publishing.md), [docs/public-advice-contract.md](docs/public-advice-contract.md)
- [docs/backtesting.md](docs/backtesting.md), [docs/testing.md](docs/testing.md), [docs/examples/](docs/examples)
- [docs/install-docker.md](docs/install-docker.md), [docs/install-lxc.md](docs/install-lxc.md)
- [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md)

## Hoe Wisselweer gebouwd is

Wisselweer is ontwikkeld met [Claude Code](https://claude.com/claude-code). De maker schreef de projectopdracht, nam de product- en ontwerpbeslissingen en beoordeelde het resultaat. De AI deed het ontwerp- en programmeerwerk in vaste rollen:

- **Architect** (Claude Opus): legde het ontwerp vast in [ARCHITECTURE.md](ARCHITECTURE.md), knipte het werk in fases, controleerde elk resultaat, draaide de tests en deed de commits.
- **Bouwers** (Claude Sonnet): implementeerden per fase één afgebakend deel, zoals de advies-engine, de weerbronnen, de database of de webinterface, met tests.

Elke fase eindigde pas als de tests slaagden en de architect het werk had nagekeken. De werkwijze en de vaste regels staan in [`.claude/skills/wisselweer-build/SKILL.md`](.claude/skills/wisselweer-build/SKILL.md). Commits van de AI zijn herkenbaar aan de regel `Co-Authored-By: Claude`.

## Licentie

Wisselweer is vrije software onder de [GNU Affero General Public License v3.0](LICENSE).
Je mag het gebruiken, aanpassen en verspreiden. Wie een aangepaste versie verspreidt of als online dienst aanbiedt, moet de broncode daarvan onder dezelfde licentie beschikbaar stellen.
Naam en logo vallen hier niet onder, zie [TRADEMARKS.md](TRADEMARKS.md).
