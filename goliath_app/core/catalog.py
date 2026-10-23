"""Core-namespace platform actions."""

from __future__ import annotations

from goliath_app.actions.spec import ActionLevel, ActionSpec
from goliath_app.core.models import PlanIterationsInput, PlanIterationsOutput

ACTION_CATALOG = [
    ActionSpec(
        action_name="validation.plan_iterations",
        namespace="core",
        level=ActionLevel.CORE,
        entity_code="validation",
        display_name="Plan validation iterations",
        description=(
            "Generic validation iteration planner hook. Descendant apps override "
            "with domain-specific Monte Carlo / stratified planning."
        ),
        required_permission="workflow.validation.plan",
        input_model=PlanIterationsInput,
        output_model=PlanIterationsOutput,
        schema_version="1",
        capability="validation.plan-iterations",
        tool="validation.plan-iterations",
        in_process_handler="goliath_app.core.handlers:handle_validation_plan_iterations",
    ),
]
