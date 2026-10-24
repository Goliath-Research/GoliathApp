"""Resolve portal direct-connect PostgreSQL settings (goliath_portal role)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PortalConnectionConfig:
    conninfo: str
    use_managed_identity: bool = False


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_flag(name: str) -> bool:
    value = _env(name).lower()
    return value in ("1", "true", "yes")


def build_portal_conninfo(*, use_managed_identity: bool = False) -> str:
    """Build a libpq URL for the least-privilege ``goliath_portal`` login."""
    from urllib.parse import quote

    override = _env("GOLIATH_PORTAL_DB")
    if override:
        return override

    host = _env("PGHOST") or _env("POSTGRES_HOST", "localhost")
    port = _env("PGPORT") or _env("POSTGRES_PORT", "5432")
    db = _env("PGDATABASE") or _env("POSTGRES_DB", "goliath")
    user = quote(_env("GOLIATH_PORTAL_USER", "goliath_portal"), safe="")
    sslmode = _env("PGSSLMODE", "prefer")
    if use_managed_identity:
        return f"postgresql://{user}@{host}:{port}/{db}?sslmode={sslmode}"
    password = quote(
        _env("GOLIATH_PORTAL_PASSWORD")
        or _env("PGPASSWORD")
        or _env("POSTGRES_PASSWORD"),
        safe="",
    )
    return f"postgresql://{user}:{password}@{host}:{port}/{db}?sslmode={sslmode}"


def resolve_portal_connection_config(
    *,
    conninfo: Optional[str] = None,
) -> PortalConnectionConfig:
    use_mi = _env_flag("GOLIATH_PORTAL_USE_MANAGED_IDENTITY")
    resolved = conninfo or _env("GOLIATH_PORTAL_DB")
    if not resolved:
        resolved = build_portal_conninfo(use_managed_identity=use_mi)
    return PortalConnectionConfig(conninfo=resolved, use_managed_identity=use_mi)
