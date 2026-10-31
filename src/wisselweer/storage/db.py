"""Engine, sessies en migraties (SQLite, WAL, foreign keys aan)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from wisselweer.settings import get_settings

_default_factory: sessionmaker[Session] | None = None


def default_url() -> str:
    data_dir = Path(get_settings().data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'wisselweer.db').resolve()}"


def make_engine(url: str | None = None) -> Engine:
    url = url or default_url()
    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn: Any, _record: Any) -> None:
            # Zelf transacties beheren, zodat SAVEPOINTs correct werken (SQLAlchemy-recept).
            dbapi_conn.isolation_level = None
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        @event.listens_for(engine, "begin")
        def _on_begin(conn: Any) -> None:
            conn.exec_driver_sql("BEGIN")

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    """Commit bij succes, rollback bij een uitzondering."""
    global _default_factory
    if factory is None:
        if _default_factory is None:
            _default_factory = make_session_factory(make_engine())
        factory = _default_factory
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def migrate(url: str | None = None) -> None:
    """`alembic upgrade head`, programmatisch."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.attributes["url"] = url or default_url()
    command.upgrade(cfg, "head")
