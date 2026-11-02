"""Fouten van de servicelaag (geen persoonsgegevens in boodschappen)."""

from __future__ import annotations


class ServiceError(Exception):
    """Basisfout. `str(exc)` is de (Nederlandse) technische boodschap voor API en logs; `key` en
    `params` zijn een optionele i18n-sleutel voor de webinterface, die de melding in de taal van
    de gebruiker toont."""

    def __init__(self, message: str = "", *, key: str | None = None, **params: object) -> None:
        super().__init__(message)
        self.key = key
        self.params = params


class NotFoundError(ServiceError):
    pass


class InvalidOperation(ServiceError):
    """Ongeldige invoer of toestandsovergang."""
