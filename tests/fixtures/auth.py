"""Hulpfuncties om testclients te authenticeren."""

from __future__ import annotations

from fastapi import FastAPI

from wisselweer.api import auth
from wisselweer.api.deps import ensure_db

ADMIN_USER = "beheerder"
ADMIN_PASSWORD = "correct-horse-battery"


def make_admin(app: FastAPI) -> None:
    with ensure_db(app)() as s:
        auth.create_admin(s, ADMIN_USER, ADMIN_PASSWORD)
        s.commit()


def make_token(app: FastAPI, name: str = "test") -> str:
    with ensure_db(app)() as s:
        token = auth.create_api_token(s, name)
        s.commit()
    return token


def bearer(app: FastAPI) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(app)}"}
