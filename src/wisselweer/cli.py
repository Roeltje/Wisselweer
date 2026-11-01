"""Command-line-ingang: `wisselweer serve|version|migrate|create-admin|…`."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys

from wisselweer import __version__
from wisselweer.logsetup import configure_logging

log = logging.getLogger("wisselweer.cli")


def _serve() -> int:
    import uvicorn

    from wisselweer.api.app import create_app
    from wisselweer.settings import get_settings

    settings = get_settings()
    configure_logging(settings.log_level)
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


def _publish() -> int:
    from wisselweer.publisher.publish import PublishError, run_publish
    from wisselweer.settings import get_settings

    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        advice = run_publish(settings)
    except PublishError as exc:
        print(f"Fout: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - geen details (kunnen paden/secrets bevatten)
        print(f"Fout: publiceren mislukt ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(f"Gepubliceerd: {advice.next_season} / {advice.status} -> {settings.publish_dir}")
    return 0


def _backtest(args: argparse.Namespace) -> int:
    from datetime import UTC, date, datetime

    from sqlalchemy import select

    from wisselweer.backtest import ForecastSnapshotData, replay
    from wisselweer.core import DrivingProfile, EngineConfig, Forecast, TireType
    from wisselweer.storage.db import migrate, session_scope
    from wisselweer.storage.orm import ForecastSnapshot

    try:
        since = datetime.combine(date.fromisoformat(args.since), datetime.min.time(), tzinfo=UTC)
    except ValueError:
        print("Fout: --since moet YYYY-MM-DD zijn", file=sys.stderr)
        return 1
    migrate()
    with session_scope() as session:
        rows = session.scalars(
            select(ForecastSnapshot)
            .where(
                ForecastSnapshot.provider == args.provider,
                ForecastSnapshot.latitude.between(args.latitude - 5e-5, args.latitude + 5e-5),
                ForecastSnapshot.longitude.between(args.longitude - 5e-5, args.longitude + 5e-5),
                ForecastSnapshot.fetched_at >= since,
            )
            .order_by(ForecastSnapshot.fetched_at)
        ).all()
        snaps = [
            ForecastSnapshotData(r.fetched_at, Forecast.model_validate(r.forecast)) for r in rows
        ]
    if not snaps:
        print("Geen forecast-snapshots gevonden voor deze locatie/provider.")
        return 0
    steps = replay(snaps, TireType(args.mounted), DrivingProfile.commute(), EngineConfig())
    print(f"{'beslismoment':<17} {'richting':<10} {'status':<20} datum/periode")
    for st in steps:
        if st.recommended_date:
            when = st.recommended_date.isoformat()
        elif st.recommended_period:
            when = f"{st.recommended_period[0]} .. {st.recommended_period[1]}"
        else:
            when = "-"
        stamp = st.decided_at.strftime("%Y-%m-%d %H:%M")
        print(f"{stamp:<17} {st.direction.value:<10} {st.status.value:<20} {when}")
    print("Let op: adviesregels zijn ongevalideerde heuristieken; zie docs/backtesting.md.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wisselweer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="Start de webserver")
    sub.add_parser("version", help="Toon de versie")
    sub.add_parser("publish", help="Bereken en publiceer het landelijke advies (advice.json)")
    sub.add_parser("migrate", help="Werk de database bij (alembic upgrade head)")
    bt = sub.add_parser(
        "backtest", help="Speel opgeslagen forecast-snapshots opnieuw af (geen netwerk)"
    )
    bt.add_argument("--latitude", type=float, required=True)
    bt.add_argument("--longitude", type=float, required=True)
    bt.add_argument("--provider", default="metno")
    bt.add_argument("--mounted", choices=["summer", "winter", "all_season"], default="summer")
    bt.add_argument("--since", default="1970-01-01", help="Vanaf datum (YYYY-MM-DD)")
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
    if args.command == "publish":
        return _publish()
    if args.command == "backtest":
        return _backtest(args)
    if args.command in {"create-admin", "reset-password", "create-api-token", "revoke-api-token"}:
        return _admin_command(args)
    return _serve()


if __name__ == "__main__":
    sys.exit(main())
