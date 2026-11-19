"""AuthProvider protocol and default identity-provider registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Mapping, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class AuthSubject:
    """Stable subject within an identity provider."""

    provider_name: str
    subject: str


@dataclass(frozen=True)
class AuthClaims:
    """Claims returned after provider authentication."""

    subject: AuthSubject
    email: Optional[str] = None
    display_name: Optional[str] = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class AuthProvider(Protocol):
    """Authenticate external credentials into a subject + claims."""

    name: str

    def authenticate(self, credentials: Mapping[str, Any]) -> AuthClaims:
        """Return subject and claims or raise ValueError on failure."""


def default_rbac_identity_provider() -> AuthProvider:
    return RbacIdentityProvider()


class RbacIdentityProvider:
    """Placeholder that defers to RBAC.IdentityProviders rows in the database."""

    name = "rbac_identity_providers"

    def authenticate(self, credentials: Mapping[str, Any]) -> AuthClaims:
        provider = str(credentials.get("provider") or credentials.get("provider_name") or "")
        subject = str(credentials.get("subject") or "")
        if not provider or not subject:
            raise ValueError("provider and subject are required")
        return AuthClaims(
            subject=AuthSubject(provider_name=provider, subject=subject),
            email=str(credentials.get("email") or "") or None,
            display_name=str(credentials.get("display_name") or "") or None,
        )


def load_auth_providers() -> dict[str, AuthProvider]:
    """Load providers from the ``goliath.auth_providers`` entry-point group."""
    providers: dict[str, AuthProvider] = {"rbac_identity_providers": RbacIdentityProvider()}
    eps = entry_points()
    if hasattr(eps, "select"):
        selected = eps.select(group="goliath.auth_providers")
    else:
        selected = eps.get("goliath.auth_providers", [])  # type: ignore[union-attr]
    for ep in selected:
        loaded = ep.load()
        if isinstance(loaded, AuthProvider):
            providers[loaded.name] = loaded
        elif callable(loaded):
            instance = loaded()
            if isinstance(instance, AuthProvider):
                providers[instance.name] = instance
    return providers
