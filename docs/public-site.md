# Publieke site (`public-site/`)

Volledig statische site (geen build-stap, geen frameworks, geen externe fonts/CDN; analytics is optioneel en standaard uit, zie "Analytics"). Ze leest uitsluitend `advice.json` (zie `docs/public-advice-contract.md`) en heeft geen netwerkpad naar de privé-app.

## Bestanden
- `index.html`, `404.html`, `style.css`, `app.js` (render met `textContent`, tijden in Europe/Amsterdam)
- `advice.json`: voorbeeldbestand; wordt in productie door `wisselweer publish` overschreven
- `analytics.js` (laadt optioneel Umami, zie "Analytics"), `analytics.example.json`
- `privacy.html`, `contact.js`, `contact.example.json` (zie "Privacyverklaring en contact")
- `manifest.webmanifest`, `robots.txt`, `sitemap.xml`
- `favicon.svg`, `logo.svg`, `icon-192.png`, `icon-512.png`, `apple-touch-icon.png`, `og-image.png` (kopieën uit `branding/`)

Gedrag: ontbrekend/ongeldig bestand of `schema_version` ≠ 1 geeft "Het actuele advies is tijdelijk niet beschikbaar."; na `stale_after` verschijnt een "verouderd"-melding en wordt de oude inhoud gedimd. Zonder JavaScript staat er een `<noscript>`-uitleg met link naar `advice.json`. De pagina bevat een leeg, verborgen `<aside id="partners">` voor eventuele affiliate-links (`rel="sponsored noopener"`).

## Analytics (optioneel, Umami)
Standaard staat analytics uit en doet de site geen extra verzoeken, behalve één same-origin `fetch` naar `analytics.json` die stil mag 404'en. Er staan geen hostnaam of website-ID in de repo.

1. Maak op de server `/srv/wisselweer/site/analytics.json` (staat in `.gitignore`, niet in git; zie `public-site/analytics.example.json`):
   ```json
   {"src": "https://umami.example.org/script.js", "websiteId": "<uuid>", "domains": "wisselweer.nl"}
   ```
   `src` moet een absolute `https:`-URL zijn en `websiteId` een UUID; `domains` is optioneel. Ongeldige config wordt genegeerd.
2. Draai `deploy/install-public-site.sh` opnieuw met `--analytics-origin https://umami.example.org` (of `WW_ANALYTICS_ORIGIN`). Dat zet de origin in `script-src` en `connect-src` van de CSP; zonder deze optie blijft de CSP ongewijzigd. Opnieuw draaien is nodig om de CSP te wijzigen.
3. Umami is cookieloos en het script wordt geladen met `data-do-not-track="true"`. Zodra analytics actief is, verandert de voettekst automatisch in "geen cookies; anonieme bezoekersstatistieken via eigen Umami."

## Privacyverklaring en contact
`privacy.html` is de Nederlandse privacyverklaring (gelinkt vanuit de voettekst). Het contactadres staat bewust niet in git: zonder config toont de pagina "via een issue op GitHub". Wil je een e-mailadres tonen, maak dan op de server `/srv/wisselweer/site/contact.json` (staat in `.gitignore`; voorbeeld: `public-site/contact.example.json`):
```json
{"email": "privacy@example.org"}
```
`contact.js` valideert het adres en zet het als `mailto:`-link; ongeldig of ontbrekend wordt stil genegeerd. De privacyverklaring belooft dat webserverlogs maximaal 7 dagen bewaard worden: `deploy/install-public-site.sh` zet daarom `rotate 7` in `/etc/logrotate.d/nginx` (met backup). Pas de tekst aan als je dit wijzigt.

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

## Installatie op een eigen LXC
Het script `deploy/install-public-site.sh` richt een kale container in als statische webserver (nginx, SFTP-only deploy-gebruiker in een chroot, nftables-firewall, automatische beveiligingsupdates). Het is idempotent: opnieuw draaien is veilig en bestaande configs worden eerst gebackupt (`<bestand>.bak.<datum>`).

**Container**: Debian 13 (trixie) aanbevolen (Ubuntu 24.04+ werkt ook), unprivileged LXC, 1 vCPU, 256–512 MB RAM, 2 GB schijf, vast intern IP, geen gedeelde mounts.

**Aanroep** (als root in de container; de IP's hieronder zijn voorbeelden uit de documentatierange):
```bash
./install-public-site.sh \
  --domain wisselweer.nl \
  --proxy-ip 192.0.2.10 \
  --ssh-allow 192.0.2.20,192.0.2.5 \
  --deny-out 192.0.2.20 \
  --deploy-key-file /root/deploy.pub \
  --site-src /root/Wisselweer/public-site
```
- `--proxy-ip` (verplicht): alleen dit IP mag poort 80 (en is `set_real_ip_from`).
- `--ssh-allow`: wie poort 22 mag. Is dit leeg, dan wordt de firewall bewust niet geactiveerd, om uitsluiting te voorkomen; staat je huidige SSH-adres er niet in, dan ook niet (tenzij `--force-firewall`).
- `--deny-out` (optioneel): blokkeert nieuwe uitgaande verbindingen naar deze IP's, bv. de privé-app.
- `--deploy-key "<ssh-ed25519 …>"` of `--deploy-key-file` (herhaalbaar): publieke sleutel(s) van de privé-app en eventueel je beheer-pc.
- `--site-src`: map (`public-site/`) of git-URL om de initiële sitebestanden te kopiëren; een bestaande `advice.json` blijft behouden. Zonder krijg je een minimale placeholder.
- Alle opties kunnen ook als omgevingsvariabele (`WW_DOMAIN`, `WW_PROXY_IP`, …); zie `--help`.

Let op: wachtwoordlogin via SSH wordt uitgezet. Zorg dat je een sleutel hebt, of gebruik de container-console (`pct enter`). Het script herstart sshd (`systemctl restart ssh`); lopende sessies blijven open. De installatie is in de praktijk getest op Debian 13.

**Nginx Proxy Manager**: Proxy Host voor `wisselweer.nl` en `www.wisselweer.nl` naar `http://<ip-van-de-container>:80`; SSL via Let's Encrypt met DNS-challenge (Cloudflare) en een API-token met alleen `Zone → DNS → Edit` voor de zone; Force SSL aan; HSTS pas aanzetten als alles werkt.

**Cloudflare**: DNS-records proxied, SSL/TLS op *Full (strict)*, en een cache-regel voor het pad `/advice.json` met Edge TTL "respect origin" (maximaal 5 minuten).

**Privé-app**: maak eerst de sleutel op de app-LXC (stap 1-2 onder "Publiceren" in [install-lxc.md](install-lxc.md)) en geef de volledige publieke sleutelregel mee aan `--deploy-key`. Zet daarna de hostkey in de `known_hosts` van de servicegebruiker, stel de `WISSELWEER_PUBLISH_SFTP_*`-variabelen in (`PATH=/site`, zie [publishing.md](publishing.md)) en test met `systemctl start wisselweer-publish.service` en `journalctl -u wisselweer-publish`. Bij SFTP-fouten: zie de tabel in publishing.md.
