"""Core-namespace handlers (generic; apps may override via catalog entry points)."""

from __future__ import annotations

from goliath_app.core.models import PlanIterationsInput, PlanIterationsOutput


def handle_validation_plan_iterations(inp: PlanIterationsInput) -> PlanIterationsOutput:
    """Pass through caller-provided iteration rows without domain-specific planning."""
    return PlanIterationsOutput(
        projectPath=inp.project_path,
        iterations=list(inp.iterations),
        centroidSeedGroups=[],
    )
