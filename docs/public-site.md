# Publieke site (`public-site/`)

Volledig statische site (geen build-stap, geen frameworks, geen externe fonts/CDN/analytics). Ze leest uitsluitend `advice.json` (zie `docs/public-advice-contract.md`) en heeft geen netwerkpad naar de privé-app.

## Bestanden
- `index.html`, `404.html`, `style.css`, `app.js` (render met `textContent`, tijden in Europe/Amsterdam)
- `advice.json`: voorbeeldbestand; wordt in productie door `wisselweer publish` overschreven
- `manifest.webmanifest`, `robots.txt`, `sitemap.xml`
- `favicon.svg`, `logo.svg`, `icon-192.png`, `icon-512.png`, `apple-touch-icon.png`, `og-image.png` (kopieën uit `branding/`)

Gedrag: ontbrekend/ongeldig bestand of `schema_version` ≠ 1 geeft "Het actuele advies is tijdelijk niet beschikbaar."; na `stale_after` verschijnt een "verouderd"-melding en wordt de oude inhoud gedimd. Zonder JavaScript staat er een `<noscript>`-uitleg met link naar `advice.json`. De pagina bevat een leeg, verborgen `<aside id="partners">` voor eventuele affiliate-links (`rel="sponsored noopener"`).

## Lokaal bekijken
`python3 -m http.server 8766 -d public-site`

## Deployen
Kopieer de inhoud van `public-site/` naar de document root van een eigen webserver (of via SFTP). `wisselweer publish` kan daarna met een beperkte deploy-user alleen `advice.json` bijwerken. Alle bestanden behalve `advice.json` wijzigen zelden.

## Caching
- `advice.json`: `Cache-Control: max-age=300` (max. 5 minuten) of `no-cache`; de site haalt het bestand zelf met `cache: 'no-cache'` op.
- Overige assets: lang cachen (bv. `max-age=86400`), herlaad bij wijziging.

## CSP (response-header)
```
Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'
```
De site gebruikt geen inline script, stijl of event-handlers, dus deze policy volstaat. Voeg gangbare headers toe (`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`) en serveer `404.html` als foutpagina.

## Vertalingen later
Teksten staan in HTML (NL) met schone structuur. Een Engelse versie kan als `/en/` met eigen `index.html` (`lang="en"`, `hreflang`-links in beide pagina's) die `../style.css` hergebruikt. `app.js` heeft NL-teksten en statuslabels in één map bovenin; maak die per taal te kiezen (bv. via `document.documentElement.lang`) en gebruik `advice.json` per `locale` (bv. `advice.en.json`).
