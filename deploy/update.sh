#!/usr/bin/env bash
# Update een bestaande native installatie: maakt eerst een back-up, installeert daarna de nieuwe
# code (zelfde parameters als install.sh) en herstart. Migraties draaien bij het opstarten.
#   ./deploy/update.sh [pad-of-git-URL [ref]]   (uitvoeren als root)
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Voer dit script uit als root." >&2
  exit 1
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR=/var/lib/wisselweer
BACKUP_DIR="${BACKUP_DIR:-/var/backups/wisselweer}"
STAMP="$(date +%Y%m%d-%H%M%S)"

install -d -m 0700 "$BACKUP_DIR"
if [[ -f "$DATA_DIR/wisselweer.db" ]]; then
  # Online back-up: veilig terwijl de service draait.
  sqlite3 "$DATA_DIR/wisselweer.db" ".backup '$BACKUP_DIR/wisselweer-$STAMP.db'"
  chmod 0600 "$BACKUP_DIR/wisselweer-$STAMP.db"
  echo "Database-back-up: $BACKUP_DIR/wisselweer-$STAMP.db"
fi
if [[ -f /etc/wisselweer/wisselweer.env ]]; then
  install -m 0600 /etc/wisselweer/wisselweer.env "$BACKUP_DIR/wisselweer-$STAMP.env"
fi

"$HERE/install.sh" "$@"
systemctl is-active --quiet wisselweer.service && echo "Service draait." || {
  echo "Service draait niet; zie journalctl -u wisselweer" >&2; exit 1; }
