"""Require PostgreSQL connections to verify the database server certificate."""

from __future__ import annotations

import os
from typing import Any

from psycopg.conninfo import conninfo_to_dict, make_conninfo

DEFAULT_SSLMODE = "verify-full"
VERIFYING_SSLMODES = frozenset({"verify-ca", "verify-full"})


class UnverifiedDatabaseTlsError(ValueError):
    """A PostgreSQL connection would not verify the server certificate."""


def _require_verifying(mode: str, source: str) -> str:
    if mode not in VERIFYING_SSLMODES:
        raise UnverifiedDatabaseTlsError(
            f"{source} sslmode={mode!r} does not verify the database server certificate; "
            "use sslmode=verify-full (or verify-ca) with PGSSLROOTCERT or sslrootcert"
        )
    return mode


def default_sslmode() -> str:
    """``PGSSLMODE`` when set, else ``verify-full``; refuse modes that skip verification."""
    mode = os.environ.get("PGSSLMODE", "").strip() or DEFAULT_SSLMODE
    return _require_verifying(mode, "PGSSLMODE")


def require_verified_tls(conninfo: str = "", **kwargs: Any) -> str:
    """Return ``conninfo`` merged with ``kwargs``, refusing it unless libpq will verify the server.

    The effective ``sslmode`` is read the way libpq parses the string (last value wins,
    ``ssl=true`` means ``require``). When the string sets none, the mode from
    :func:`default_sslmode` is written into the result so later environment changes
    cannot weaken it.
    """
    params = conninfo_to_dict(conninfo, **kwargs)
    mode = str(params.get("sslmode") or "")
    if mode:
        _require_verifying(mode, "connection")
        if not kwargs:
            return conninfo
    else:
        mode = default_sslmode()
    return make_conninfo(conninfo, **{**kwargs, "sslmode": mode})


__all__ = [
    "DEFAULT_SSLMODE",
    "UnverifiedDatabaseTlsError",
    "VERIFYING_SSLMODES",
    "default_sslmode",
    "require_verified_tls",
]
