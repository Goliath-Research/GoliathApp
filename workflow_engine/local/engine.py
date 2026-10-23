"""LocalWorkflowEngine — run WorkflowDefinitionSpec in-process."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from pydantic import BaseModel, ConfigDict

from contract.workflow_definition_spec import WorkflowDefinitionSpec
from domain.compiler import compile_domain_program_file
from domain.workflow_context import finalize_instance_context
from goliath_app.actions.registry import find_action as _find_catalog_action
from goliath_app.execution.local import (
    execute_action as _execute_platform_action,
    normalize_action_input as _normalize_platform_input,
    validate_action_output as _validate_platform_output,
)

from .scheduler import ExecutionTrace, SchedulerConfig, WorkflowScheduler
from .scope import ScopeFrame, resolve_collection_bindings

logger = logging.getLogger(__name__)

ActionHandler = Callable[[str, str, Dict[str, Any]], BaseModel]


class StubActionOutput(BaseModel):
    """Result of a locally stubbed action (``--stub-external``)."""

    model_config = ConfigDict(extra="allow")

    status: str = "ok"
    value: bool = True
    result_code: int = 1


def stub_action(capability: str, action_name: str, input_json: Dict[str, Any]) -> StubActionOutput:
    """Return a successful stub payload without a product worker."""
    return StubActionOutput(action=action_name, capability=capability, echoed=dict(input_json))


@dataclass
class RunResult:
    status: str
    trace: ExecutionTrace
    scope: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class LocalWorkflowEngine:
    """Execute a workflow definition locally without gateway or database."""

    def __init__(
        self,
        *,
        handler: Optional[ActionHandler] = None,
        config: Optional[SchedulerConfig] = None,
    ) -> None:
        self.config = config or SchedulerConfig()
        self._handler = handler

    def _default_handler(self) -> ActionHandler:
        if os.environ.get("WORKER_STUB_EXTERNAL") == "1":
            return stub_action
        def _run(capability: str, action_name: str, input_json: Dict[str, Any]) -> BaseModel:
            if _find_catalog_action(action_name) is not None:
                _normalize_platform_input(action_name, capability, input_json)
                result = _execute_platform_action(capability, action_name, input_json)
                return _validate_platform_output(action_name, capability, result)

            raise RuntimeError(
                f"local execution has no registered handler for action {action_name!r}; "
                "install a descendant app catalog or use --stub-external"
            )

        return _run

    def run_spec(
        self,
        spec: WorkflowDefinitionSpec,
        context_json: Dict[str, Any],
        *,
        enrich_context: bool = True,
    ) -> RunResult:
        context = dict(context_json)
        if enrich_context:
            try:
                context = finalize_instance_context(context)
            except (FileNotFoundError, ValueError, ImportError) as exc:
                logger.warning("context enrichment skipped: %s", exc)

        scope_data = resolve_collection_bindings(spec.collection_bindings, context)
        scope = ScopeFrame(scope_data)
        handler = self._handler or self._default_handler()
        os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")
        force_rerun = bool(context.get("forceRerun")) or self.config.force_rerun
        run_config = SchedulerConfig(
            parallel_workers=self.config.parallel_workers,
            dry_run=self.config.dry_run,
            force_rerun=force_rerun,
        )

        try:
            scheduler = WorkflowScheduler(
                spec, scope, handler=handler, config=run_config
            )
            trace = scheduler.run()
            return RunResult(status="COMPLETED", trace=trace, scope=scope.as_flat_dict())
        except Exception as exc:
            logger.exception("workflow run failed")
            return RunResult(
                status="FAILED",
                trace=ExecutionTrace(),
                scope=scope.as_flat_dict(),
                error=str(exc),
            )

    def run_program(
        self,
        program_path: Path,
        context_json: Dict[str, Any],
        *,
        enrich_context: bool = True,
    ) -> RunResult:
        result = compile_domain_program_file(program_path, enrich_context=False)
        merged = {**result.context_json, **context_json}
        merged.setdefault("program_path", str(program_path))
        merged.setdefault("programPath", str(program_path))
        return self.run_spec(result.workflow, merged, enrich_context=enrich_context)

    @staticmethod
    def load_spec(path: Path) -> WorkflowDefinitionSpec:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WorkflowDefinitionSpec.model_validate(data)
