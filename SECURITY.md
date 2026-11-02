# Beveiliging

## Model

Wisselweer is bedoeld als privé-applicatie voor één beheerder.

- **Standaard alleen localhost.** De server bindt op `127.0.0.1` (Docker publiceert `127.0.0.1:8000`). Zet `WISSELWEER_HOST` niet op een extern adres zonder toegangscontrole.
- **VPN aanbevolen.** Wil je de app van buiten bereiken, gebruik dan een VPN (bijvoorbeeld WireGuard of Tailscale) of een reverse proxy met HTTPS. Zet daarbij `WISSELWEER_COOKIE_SECURE=true`.
- **Authenticatie.** Eén lokale beheerder (`wisselweer create-admin`), wachtwoord met scrypt (N=2^16, r=8, p=2; minimaal 10 tekens; oudere hashes worden bij een geslaagde login automatisch vernieuwd). Alle `/api/v1/*`-routes behalve `GET /api/v1/health`, plus `/docs` en `/openapi.json`, vereisen een sessie of een Bearer-token. `WISSELWEER_ENABLE_DOCS=false` zet `/docs` en `/openapi.json` helemaal uit.
- **Sessies.** Cookie `ww_session`: `HttpOnly`, `SameSite=Strict`, 7 dagen, ondertekend met een geheime sleutel (`WISSELWEER_SECRET_KEY`, minimaal 32 tekens, of automatisch in `<data_dir>/secret_key`, rechten 600). Achter een https-proxy hoort `WISSELWEER_COOKIE_SECURE=true` te staan; de app waarschuwt bij het opstarten als `WISSELWEER_HOST` niet loopback is en dit uit staat. Muterende requests met sessie vereisen een CSRF-token.
- **API-tokens.** Voor Home Assistant en scripts; alleen de SHA-256-hash wordt opgeslagen en tokens zijn intrekbaar.
- **Inlogpogingen.** Maximaal 5 mislukte pogingen per IP per 5 minuten (in geheugen). Achter een reverse proxy ziet de app het IP van de proxy; beperk dan ook toegang op de proxy.
- **Gegevens.** Geen debugmodus, generieke foutmeldingen, geen geheimen of persoonsgegevens in logs. Coördinaten komen niet in de logs (httpx/httpcore staan op WARNING, de querystring ontbreekt in de accesslog). Beveiligingsheaders (CSP met `form-action` en `object-src`, `X-Frame-Options`, `Permissions-Policy`) staan standaard aan en alle responses behalve `/static/*`, de healthcheck en de voertuigfoto's krijgen `Cache-Control: no-store`.
- **Externe bronnen.** Open-Meteo alleen via https (loopback-http uitgezonderd), antwoorden van weerbronnen zijn begrensd op 5 MB, station-ID's worden in het pad gequote.
- **Systemd.** De units draaien met een strak sandbox-profiel (o.a. syscall-filter, `MemoryMax`, `TasksMax`). De webapp kan `/var/lib/wisselweer/.ssh` (SFTP-sleutel) niet lezen; publiceren via SFTP loopt alleen via `wisselweer-publish.timer`, zie `docs/publishing.md`.
- **Docker.** Het image draait als niet-root (UID 10001) met read-only root-bestandssysteem, `no-new-privileges`, zonder capabilities en alleen op `127.0.0.1`. De webapp-container krijgt de SFTP-sleutel niet: alleen de optionele service `publisher` (profiel `publish`) mount `./secrets`, het equivalent van `wisselweer-publish.timer`. Release-images worden gebouwd door GitHub Actions met SLSA build provenance en SBOM en zijn te controleren met `gh attestation verify` (zie `docs/install-docker.md`). `docker-install.sh` haalt alleen via https van de release, maakt `.env` met rechten 600 en overschrijft een bestaand `.env` nooit.
- **Voertuigfoto's.** Maximaal 2 MB, alleen JPEG, PNG of WebP (bepaald op de inhoud, niet op naam of Content-Type); de server haalt EXIF, GPS en andere metadata er zelf uit en bewaart de foto onder een willekeurige naam in `<data_dir>/photos/` (map 0700, bestanden 0600). De foto's worden alleen aan ingelogde gebruikers geserveerd, met `nosniff` en een eigen strikte CSP, en komen nooit in de publicatie; `wisselweer-publish.service` ziet de map niet.
- **Back-ups.** De map `data/` bevat de database, de geheime sleutel en de voertuigfoto's (`photos/`); bescherm die als een wachtwoordbestand.

## Een kwetsbaarheid melden

Meld kwetsbaarheden vertrouwelijk via **GitHub Security Advisories** van deze repository (tabblad *Security* → *Report a vulnerability*). Maak geen openbaar issue aan voordat er een oplossing is.
