"""Helpers for Meta-backed semantic entities."""

from __future__ import annotations


def meta_class_schema_id(class_name: str) -> str:
    return f"goliath:meta/class/{class_name}"


def meta_class_storage_relation(class_name: str, table_name: str | None = None) -> str:
    view_suffix = table_name or class_name
    return f'"Meta"."V{view_suffix}"'


def meta_class_catalog_type_name(class_name: str) -> str:
    return f"meta/class/{class_name}"
