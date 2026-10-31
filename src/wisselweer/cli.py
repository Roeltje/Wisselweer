"""Command-line-ingang: `wisselweer serve|version|migrate`."""

from __future__ import annotations

import argparse
import ipaddress
import logging
import sys

from wisselweer import __version__

log = logging.getLogger("wisselweer.cli")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _serve() -> int:
    import uvicorn

    from wisselweer.api.app import create_app
    from wisselweer.settings import get_settings

    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    if not _is_loopback(settings.host):
        log.warning(
            "Server luistert op %s (niet loopback): er is nog geen authenticatie; "
            "plaats een reverse proxy met toegangscontrole ervoor.",
            settings.host,
        )
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wisselweer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="Start de webserver")
    sub.add_parser("version", help="Toon de versie")
    sub.add_parser("migrate", help="Werk de database bij (alembic upgrade head)")
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "migrate":
        from wisselweer.storage.db import migrate

        migrate()
        return 0
    return _serve()


if __name__ == "__main__":
    sys.exit(main())
