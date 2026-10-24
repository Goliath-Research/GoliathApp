"""Core semantic catalog entries shipped with GoliathApp."""

from __future__ import annotations

from goliath_app.semantic.filters import FilterOp, FilterTemplate, Predicate
from goliath_app.semantic.models import (
    FilterOrganizationsParams,
    ListOrganizationsParams,
    OrganizationRow,
)
from goliath_app.semantic.spec import SemanticAttributeSpec, SemanticEntitySpec, SemanticRequestSpec

ORGANIZATION_ENTITY = SemanticEntitySpec(
    namespace="core",
    code="organization",
    display_name="Organization",
    description="Generic GoliathApp organization tenancy record.",
    schema_version="1",
    row_model=OrganizationRow,
    storage_relation='portal."Organizations"',
    attributes=(
        SemanticAttributeSpec("organization_id", "ID", "integer", "key", ()),
        SemanticAttributeSpec(
            "name",
            "Name",
            "string",
            "filter",
            (FilterOp.EQ.value, FilterOp.STARTS_WITH.value),
        ),
        SemanticAttributeSpec("active", "Active", "boolean", "list", ()),
    ),
)

SEMANTIC_CATALOG: list[SemanticEntitySpec] = [ORGANIZATION_ENTITY]

SEMANTIC_REQUESTS: list[SemanticRequestSpec] = [
    SemanticRequestSpec(
        request_code="core.list_organizations",
        version="1",
        namespace="core",
        entity_code="organization",
        target_kind="function",
        target_name="portal.fn_semantic_core_list_organizations",
        params_model=ListOrganizationsParams,
        result_row_model=OrganizationRow,
    ),
    SemanticRequestSpec(
        request_code="core.filter_organizations",
        version="1",
        namespace="core",
        entity_code="organization",
        target_kind="template",
        target_name="portal.fn_semantic_core_filter_organizations",
        params_model=FilterOrganizationsParams,
        result_row_model=OrganizationRow,
        filter_template=FilterTemplate(
            all_of=[Predicate(attribute="name", op=FilterOp.STARTS_WITH, param="name")]
        ),
    ),
    SemanticRequestSpec(
        request_code="core.restricted_probe",
        version="1",
        namespace="core",
        entity_code="organization",
        target_kind="function",
        target_name="portal.fn_semantic_core_list_organizations",
        params_model=ListOrganizationsParams,
        result_row_model=OrganizationRow,
        required_permission="semantic.restricted.probe",
    ),
]
