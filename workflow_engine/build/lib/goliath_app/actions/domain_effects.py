"""Optional catalog metadata consumed by the DomainProgram compiler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class OutputBindingRule:
    scope_field: str
    output_json_path: str


@dataclass(frozen=True)
class TemplateDefaultRule:
    field: str
    scope_var: str
    only_if_absent: bool = True
    absent_also: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplateGroupSideRule:
    side: str
    field: str
    scope_var: str


@dataclass(frozen=True)
class DomainEffects:
    scope_bindings: Tuple[Tuple[str, str], ...] = ()
    output_bindings: Tuple[OutputBindingRule, ...] = ()
    template_defaults: Tuple[TemplateDefaultRule, ...] = ()
    template_group_side_defaults: Tuple[TemplateGroupSideRule, ...] = ()
