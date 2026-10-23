"""Azure Entra ID access tokens for PostgreSQL managed-identity connections."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

# Resource for Azure Database for PostgreSQL Entra authentication.
_POSTGRES_RESOURCE = "https://ossrdbms-aad.database.windows.net/.default"

# Refresh before expiry (Azure tokens are typically ~1 hour).
_REFRESH_MARGIN_SECONDS = 300


@dataclass
class _CachedToken:
    token: str
    expires_on: float


_lock = threading.Lock()
_cache: Optional[_CachedToken] = None


def _fetch_access_token() -> _CachedToken:
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError(
            "azure-identity is required when WF_USE_MANAGED_IDENTITY=1 "
            "(pip install methyl-gateway with azure-identity)"
        ) from exc

    client_id = os.environ.get("AZURE_CLIENT_ID", "").strip() or None
    credential = DefaultAzureCredential(
        managed_identity_client_id=client_id,
        exclude_interactive_browser_credential=True,
    )
    result = credential.get_token(_POSTGRES_RESOURCE)
    expires_on = float(getattr(result, "expires_on", time.time() + 3600))
    return _CachedToken(token=result.token, expires_on=expires_on)


def get_database_access_token() -> str:
    """Return a cached Azure AD access token for PostgreSQL Entra auth."""
    global _cache
    now = time.time()
    with _lock:
        if _cache is not None and _cache.expires_on - now > _REFRESH_MARGIN_SECONDS:
            return _cache.token
        fresh = _fetch_access_token()
        _cache = fresh
        return fresh.token


def clear_token_cache() -> None:
    """Clear cached tokens (for tests)."""
    global _cache
    with _lock:
        _cache = None
