"""Static typing guardrails for the portal client."""

from __future__ import annotations

import inspect
from typing import Any, get_type_hints

from pydantic import BaseModel

from goliath_app.portal.client import PortalClient
from goliath_app.portal.models import SemanticCatalogEntry, SessionOpenResult
from goliath_app.semantic.models import FilterOrganizationsParams, ListOrganizationsParams, OrganizationRow


def _field_types(model: type[BaseModel]) -> list[object]:
    return [field.annotation for field in model.model_fields.values()]


def _contains_any(annotation: object) -> bool:
    if annotation is Any:
        return True
    if getattr(annotation, "__name__", "") == "Any":
        return True
    return False


def test_portal_models_have_no_any_in_fields() -> None:
    for model in (
        SessionOpenResult,
        SemanticCatalogEntry,
        ListOrganizationsParams,
        FilterOrganizationsParams,
        OrganizationRow,
    ):
        for annotation in _field_types(model):
            assert not _contains_any(annotation), f"Any field in {model.__name__}"


def test_portal_client_public_methods_avoid_any_return() -> None:
    for name, method in inspect.getmembers(PortalClient, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        hints = get_type_hints(method)
        ret = hints.get("return")
        if ret is not None:
            assert not _contains_any(ret), f"Any return on PortalClient.{name}"
