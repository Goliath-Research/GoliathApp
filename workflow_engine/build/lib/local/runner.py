#!/usr/bin/env python3
"""CLI: compile a DomainProgram and, unless --compile-only, execute it locally."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from domain.compiler import compile_domain_program_file

from .engine import LocalWorkflowEngine
from .scheduler import SchedulerConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--program", type=Path, help="DomainProgram JSON path")
    src.add_argument("--workflow", type=Path, help="Compiled WorkflowDefinitionSpec JSON path")
    parser.add_argument(
        "--compile-only",
        action="store_true",
        help="Compile --program to WorkflowDefinitionSpec JSON and exit (no execution)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write the compiled spec here (with --compile-only). Default: stdout",
    )
    parser.add_argument(
        "--context",
        type=str,
        default=None,
        help="Instance context_json as inline JSON string",
    )
    parser.add_argument("--context-file", type=Path, default=None, help="context_json file")
    parser.add_argument("--dry-run", action="store_true", help="Resolve templates only; do not execute")
    parser.add_argument(
        "--parallel-workers",
        type=int,
        default=1,
        help="Thread pool size for PARALLEL / parallel FOREACH (use 1 on NFS/GPU to avoid lock/OOM races)",
    )
    parser.add_argument(
        "--stub-external",
        action="store_true",
        help="Stub action handlers (WORKER_STUB_EXTERNAL=1) instead of calling the product worker",
    )
    parser.add_argument(
        "--force-rerun",
        action="store_true",
        help="Disable signature-based action skip and re-execute all actions",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.compile_only and args.program is None:
        parser.error("--compile-only requires --program")
    if args.output is not None and not args.compile_only:
        parser.error("--output is only valid with --compile-only")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.compile_only:
        result = compile_domain_program_file(args.program, enrich_context=False)
        text = json.dumps(result.workflow.model_dump(mode="json"), indent=2) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(f"wrote {args.output}", file=sys.stderr)
        else:
            sys.stdout.write(text)
        return 0

    if args.stub_external:
        os.environ["WORKER_STUB_EXTERNAL"] = "1"

    # NFS / shared mounts (e.g. /work): avoid HDF5 file-lock failures during parallel centroids.
    os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

    context: dict = {}
    if args.context_file:
        context = json.loads(args.context_file.read_text(encoding="utf-8"))
    if args.context:
        context.update(json.loads(args.context))

    if args.force_rerun:
        context["forceRerun"] = True

    config = SchedulerConfig(
        dry_run=args.dry_run,
        parallel_workers=args.parallel_workers,
        force_rerun=args.force_rerun,
    )
    engine = LocalWorkflowEngine(config=config)

    if args.program:
        run = engine.run_program(args.program, context)
    else:
        spec = LocalWorkflowEngine.load_spec(args.workflow)
        run = engine.run_spec(spec, context)

    print(
        json.dumps(
            {
                "status": run.status,
                "actions": run.trace.executed_actions,
                "skipped_actions": run.trace.skipped_actions,
            },
            indent=2,
        )
    )
    if run.error:
        print(f"error: {run.error}", file=sys.stderr)
        return 1
    return 0 if run.status == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
