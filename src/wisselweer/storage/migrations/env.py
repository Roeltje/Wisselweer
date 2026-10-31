"""Alembic-omgeving: URL uit `config.attributes['url']` of de instellingen."""

from __future__ import annotations

from alembic import context

from wisselweer.storage.db import default_url, make_engine
from wisselweer.storage.orm import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.attributes.get("url") or default_url()


def run_migrations_online() -> None:
    engine = make_engine(_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
