"""Fouten van de servicelaag (geen persoonsgegevens in boodschappen)."""

from __future__ import annotations


class ServiceError(Exception):
    pass


class NotFoundError(ServiceError):
    pass


class InvalidOperation(ServiceError):
    """Ongeldige invoer of toestandsovergang."""
