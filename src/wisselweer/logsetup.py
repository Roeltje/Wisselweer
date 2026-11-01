"""Logging-opzet voor de CLI: geen coördinaten of querystrings in logs (ARCHITECTURE §7)."""

from __future__ import annotations

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
# httpx/httpcore loggen op INFO/DEBUG de volledige request-URL, inclusief `lat=..&lon=..`.
_QUIET_LOGGERS = ("httpx", "httpcore")


class StripQueryFilter(logging.Filter):
    """Haalt de querystring uit het request-pad van de uvicorn-accesslog.

    Uvicorn logt `client - "GET /pad?lat=..&lon=.. HTTP/1.1" 200`; het pad zit in `record.args[2]`.
    Alleen het pad blijft staan; de verzoekregel is voor de rest ongewijzigd.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2].partition("?")[0]
            record.args = (*args[:2], path, *args[3:])
        return True


def configure_logging(level: str) -> None:
    """Basisconfiguratie plus onvoorwaardelijk stil houden van httpx/httpcore en accesslog-query."""
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, StripQueryFilter) for f in access.filters):
        access.addFilter(StripQueryFilter())
