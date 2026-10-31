"""Command-line-ingang: `wisselweer serve|version|migrate|create-admin|…`."""

from __future__ import annotations

import argparse
import getpass
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
            "Server luistert op %s (niet loopback): gebruik HTTPS (reverse proxy of VPN) en "
            "zet WISSELWEER_COOKIE_SECURE=true.",
            settings.host,
        )
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
    return 0


def _read_password(from_stdin: bool, confirm: bool = True) -> str:
    """Wachtwoord via stdin of getpass; nooit als argument."""
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Wachtwoord: ")
    if confirm and getpass.getpass("Herhaal wachtwoord: ") != first:
        raise ValueError("Wachtwoorden komen niet overeen")
    return first


def _admin_command(args: argparse.Namespace) -> int:
    from wisselweer.api import auth
    from wisselweer.storage.db import migrate, session_scope

    migrate()
    try:
        with session_scope() as session:
            if args.command == "create-api-token":
                token = auth.create_api_token(session, args.name)
                print("Token (wordt maar één keer getoond, bewaar het veilig):")
                print(token)
            elif args.command == "revoke-api-token":
                auth.revoke_api_token(session, args.name)
                print("Token ingetrokken.")
            else:
                password = _read_password(args.password_stdin)
                if args.command == "create-admin":
                    auth.create_admin(session, args.username, password)
                    print("Beheerder aangemaakt.")
                else:
                    auth.reset_password(session, args.username, password)
                    print("Wachtwoord gewijzigd; bestaande sessies zijn ongeldig.")
    except (auth.AuthError, ValueError) as exc:
        print(f"Fout: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wisselweer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="Start de webserver")
    sub.add_parser("version", help="Toon de versie")
    sub.add_parser("migrate", help="Werk de database bij (alembic upgrade head)")
    for name, help_ in (
        ("create-admin", "Maak de beheerder aan"),
        ("reset-password", "Wijzig het wachtwoord van de beheerder"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--username", required=True)
        p.add_argument("--password-stdin", action="store_true", help="Lees wachtwoord van stdin")
    for name, help_ in (
        ("create-api-token", "Maak een API-token (Bearer) aan"),
        ("revoke-api-token", "Trek een API-token in"),
    ):
        sub.add_parser(name, help=help_).add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "migrate":
        from wisselweer.storage.db import migrate

        migrate()
        return 0
    if args.command in {"create-admin", "reset-password", "create-api-token", "revoke-api-token"}:
        return _admin_command(args)
    return _serve()


if __name__ == "__main__":
    sys.exit(main())
