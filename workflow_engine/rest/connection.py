"""Resolve workflow gateway PostgreSQL connection settings from environment."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from goliath_worker.platform_env import resolve_database_url_override  # noqa: E402


@dataclass(frozen=True)
class GatewayConnectionConfig:
    schema_name: str
    connection_string: str
    use_managed_identity: bool = False

    @property
    def schema_dot(self) -> str:
        return f"{self.schema_name}."


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_flag(name: str) -> bool:
    value = _env(name).lower()
    return value in ("1", "true", "yes")


def resolve_schema_name() -> str:
    schema = _env("WF_SCHEMA")
    return schema or "wf"


def build_postgres_conninfo(*, use_managed_identity: bool = False) -> str:
    from urllib.parse import quote

    override = resolve_database_url_override()
    if override:
        return override

    host = _env("PGHOST") or _env("POSTGRES_HOST", "localhost")
    port = _env("PGPORT") or _env("POSTGRES_PORT", "5432")
    db = _env("PGDATABASE") or _env("POSTGRES_DB", "goliath")
    user = quote(_env("PGUSER") or _env("POSTGRES_USER", "postgres"), safe="")
    sslmode = _env("PGSSLMODE", "prefer")
    if use_managed_identity:
        # Password is supplied at connect time via Entra token.
        return f"postgresql://{user}@{host}:{port}/{db}?sslmode={sslmode}"
    password = quote(_env("PGPASSWORD") or _env("POSTGRES_PASSWORD"), safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}?sslmode={sslmode}"


def resolve_connection_config(
    *,
    connection_string: Optional[str] = None,
) -> GatewayConnectionConfig:
    use_mi = _env_flag("WF_USE_MANAGED_IDENTITY")
    conn = connection_string or resolve_database_url_override()
    if not conn:
        conn = build_postgres_conninfo(use_managed_identity=use_mi)
    return GatewayConnectionConfig(
        schema_name=resolve_schema_name(),
        connection_string=conn,
        use_managed_identity=use_mi,
    )
