"""Portal direct SQL client (goliath_portal role, stored procedures only)."""

from goliath_app.portal.client import PortalClient
from goliath_app.portal.connection import (
    PortalConnectionConfig,
    build_portal_conninfo,
    resolve_portal_connection_config,
)
from goliath_app.portal.errors import PortalSemanticError
from goliath_app.portal.models import SemanticCatalogEntry, SessionOpenResult

__all__ = [
    "PortalClient",
    "PortalConnectionConfig",
    "PortalSemanticError",
    "SemanticCatalogEntry",
    "SessionOpenResult",
    "build_portal_conninfo",
    "resolve_portal_connection_config",
]
