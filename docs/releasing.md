# Een release maken

Een release is een tag `vX.Y.Z`. De workflow [release.yml](../.github/workflows/release.yml) bouwt dan het
Docker-image (amd64 en arm64), zet het op GHCR met herkomstverklaring en SBOM, en maakt een GitHub Release
met de installatiebestanden.

## Stappen

1. **Versie ophogen** in een PR: `pyproject.toml`, `src/wisselweer/__init__.py` en `uv.lock`
   (`uv lock`). De workflow weigert een tag die niet gelijk is aan `v` + deze versie.
2. **CHANGELOG.md** bijwerken: een kopje voor de nieuwe versie met de PR's sinds de vorige tag
   (`gh pr list --state merged`) en de vergelijkingslink onderaan.
3. **PR mergen** nadat de CI groen is.
4. **Taggen** op de merge-commit in `main`:

   ```sh
   git switch main && git pull
   git tag -a v0.2.0 -m "Wisselweer 0.2.0"
   git push origin v0.2.0
   ```

5. **Workflow volgen** onder *Actions → Release*. Bij een fout: los het op in een nieuwe PR, verwijder de
   tag (`git push --delete origin v0.2.0 && git tag -d v0.2.0`) en tag opnieuw.
6. **Alleen de eerste keer**: zet het pakket op GHCR op openbaar (GitHub → Packages → `wisselweer` →
   Package settings → Change visibility → Public). Anders kan `docker-install.sh` het image niet ophalen
   zonder in te loggen.
7. **Controleren**:

   ```sh
   docker pull ghcr.io/roeltje/wisselweer:0.2.0
   gh attestation verify oci://ghcr.io/roeltje/wisselweer:0.2.0 --owner Roeltje
   ```

   Probeer daarna `docker-install.sh` op een testhost (nieuw en bijwerken), zie
   [install-docker.md](install-docker.md).

## Bestaande LXC-installaties

Die werken met `update.sh`, vanuit een lokale checkout of een git-URL met een optionele ref
(`./deploy/update.sh [pad-of-git-URL [ref]]`). Wil je daar precies de release draaien, geef dan de tag als
ref mee, bijvoorbeeld `v0.2.0`. Het script maakt eerst een back-up van de database en de foto's.
