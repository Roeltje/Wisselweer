#!/bin/sh
# Wisselweer-CLI voor een native installatie; deploy/install.sh zet dit neer als
# /usr/local/bin/wisselweer. Start het commando als servicegebruiker met het env-bestand,
# net als de systemd-units, zodat het dezelfde database en instellingen gebruikt als de app.
#   wisselweer create-admin --username <naam>
#   echo "$WACHTWOORD" | wisselweer create-admin --username <naam> --password-stdin
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Voer dit uit als root (op een systeem met sudo: sudo wisselweer ...)." >&2
  exit 1
fi

# Interactief (wachtwoordprompt) via een pty; anders stdin/stdout doorgeven (scripts, --password-stdin).
if [ -t 0 ] && [ -t 1 ]; then mode=--pty; else mode=--pipe; fi

exec systemd-run --quiet --wait --collect "$mode" \
  -p User=wisselweer -p Group=wisselweer \
  -p EnvironmentFile=/etc/wisselweer/wisselweer.env \
  -p WorkingDirectory=/var/lib/wisselweer \
  /opt/wisselweer/.venv/bin/wisselweer "$@"
