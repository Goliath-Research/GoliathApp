"""Meta-backed semantic export helpers."""

from __future__ import annotations

from goliath_app.semantic.meta_bridge import meta_class_schema_id
from goliath_app.semantic.models import OrganizationRow
from goliath_app.semantic.spec import SemanticEntitySpec


def test_meta_entity_export_schema_id() -> None:
    entity = SemanticEntitySpec(
        namespace="meta",
        code="sample",
        display_name="Sample",
        description="Meta-backed demo entity",
        schema_version="1.0",
        row_model=OrganizationRow,
        meta_class_name="Sample",
        meta_class_id=12,
    )
    from goliath_app.semantic.export import _schema_id

    assert _schema_id(entity) == meta_class_schema_id("Sample")
