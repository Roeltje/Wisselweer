# Beveiliging

## Model

Wisselweer is bedoeld als privé-applicatie voor één beheerder.

- **Standaard alleen localhost.** De server bindt op `127.0.0.1` (Docker publiceert `127.0.0.1:8000`). Zet `WISSELWEER_HOST` niet op een extern adres zonder toegangscontrole.
- **VPN aanbevolen.** Wil je de app van buiten bereiken, gebruik dan een VPN (bijvoorbeeld WireGuard of Tailscale) of een reverse proxy met HTTPS. Zet daarbij `WISSELWEER_COOKIE_SECURE=true`.
- **Authenticatie.** Eén lokale beheerder (`wisselweer create-admin`), wachtwoord met scrypt (minimaal 10 tekens). Alle `/api/v1/*`-routes behalve `GET /api/v1/health`, plus `/docs` en `/openapi.json`, vereisen een sessie of een Bearer-token.
- **Sessies.** Cookie `ww_session`: `HttpOnly`, `SameSite=Strict`, 7 dagen, ondertekend met een geheime sleutel (`WISSELWEER_SECRET_KEY` of automatisch in `<data_dir>/secret_key`, rechten 600). Muterende requests met sessie vereisen een CSRF-token.
- **API-tokens.** Voor Home Assistant en scripts; alleen de SHA-256-hash wordt opgeslagen en tokens zijn intrekbaar.
- **Inlogpogingen.** Maximaal 5 mislukte pogingen per IP per 5 minuten (in geheugen). Achter een reverse proxy ziet de app het IP van de proxy; beperk dan ook toegang op de proxy.
- **Gegevens.** Geen debugmodus, generieke foutmeldingen, geen geheimen of persoonsgegevens in logs. Beveiligingsheaders (CSP, `X-Frame-Options`) staan standaard aan.
- **Back-ups.** De map `data/` bevat de database en de geheime sleutel; bescherm die als een wachtwoordbestand.

## Een kwetsbaarheid melden

Meld kwetsbaarheden vertrouwelijk via **GitHub Security Advisories** van deze repository (tabblad *Security* → *Report a vulnerability*). Maak geen openbaar issue aan voordat er een oplossing is.
