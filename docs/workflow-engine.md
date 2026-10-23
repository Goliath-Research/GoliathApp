# Workflow engine

The workflow engine is SQL. PostgreSQL sources are `workflow_engine/sql_pg/`. They expose the objects listed in `workflow_engine/contract/db_objects.yaml`. `workflow_engine/contract/validate_contract.py` checks that those names appear in the deploy scripts.

A graph is rows in `wf.workflow_def`, `wf.workflow_version`, `wf.workflow_node`, and `wf.workflow_edge`. Node types match the compiler: `ACTION`, `SEQUENCE`, `PARALLEL`, `IF`, `SWITCH`, `REPEAT`, `WHILE`, `FOREACH`, `WAIT_EVENT`.

## Runtime

`03_engine_core.sql` and the parity scripts (`05_runtime_parity.sql` through `08_foreach_support.sql`) implement activation and continuation:

- Scope variables are read with `${var.*}` and `${ctx.*}` placeholders. PostgreSQL keeps JSON types through placeholder resolution (`tests/test_pg_plpgsql_variable_conflict.py` guards a related PL/pgSQL name clash).
- `wf.wf_build_input_json_for_action` builds the payload a worker receives.
- Output bindings and branch variables are written on submit.
- `wf.wf_try_task_result_code` turns `node_execution.result_code` into IF and SWITCH branches.
- FOREACH, including collection bindings (`wf_sql_collection_bindings.sql`), runs in the database. `wf.foreach_bundle_entry` records a content key so a repeated body can be skipped when the same key is already committed. The local runner mirrors that idea under `{project_root}/.caas/foreach_bundle/` (`workflow_engine/local/foreach_caas.py`).
- `wf_reclaim_expired_leases.sql` returns expired leases to READY. The worker request path calls it when leases have expired.
- `04_admin.sql` defines `wf.sp_delete_workflow_def`.
- `wf_repo_create_workflow_graph.sql` inserts a graph from the repository API.

`wf_execution_scope.sql` and `wf_apply_validation_plan.sql` extend instance scope and validation-plan application. The gateway calls `rest.execution_scope.sync_execution_scope_action_entry_after_submit` after a successful submit and ignores errors from that call.

## Events

`wf_event_plane.sql` adds `wf.event_type`, `wf.event`, `wf.event_subscription`, and `wf.event_delivery`. Subscription modes are `start_instance`, `signal_wait`, and `start_or_signal`.

`POST /v1/events` on the gateway calls `wf.sp_ingest_event`. Required JSON fields are `event_type`, `source`, and `idempotency_key`. Optional fields are `payload` (or `payload_json`), `correlation_key`, and `occurred_at_utc`. A duplicate `(source, idempotency_key)` is a no-op. A matching subscription starts an instance or completes a READY `WAIT_EVENT` node.

The local scheduler does not run `WAIT_EVENT`. That node type is database-only.

## Two ways to run a graph

**Database.** Workers call the gateway. The engine leases one READY ACTION, the worker submits `result_code` and `output_json`, and SQL continues the instance. See [workers.md](workers.md).

**In-process.** `LocalWorkflowEngine` in `workflow_engine/local/engine.py` walks the same spec with a thread pool for `PARALLEL` and parallel FOREACH (`--parallel-workers`, default 1). `--dry-run` resolves templates and does not call a handler. `--force-rerun` sets context `forceRerun`.

Result codes follow the worker contract: a negative code fails the instance; `0`, `1`, and higher values select branches defined by the graph.

## Dispatch columns the engine reads

Action rows carry dispatch metadata the claim query honors. The engine does not interpret the action name.

| Column | Effect on claim |
|--------|-----------------|
| `capability` | Task is offered only to a worker whose `wf.worker.capabilities` allows it. |
| `max_per_worker` | Cap on concurrent RUNNING leases of this action for one worker. NULL means no cap. |
| `exclusive_worker` | While this action is leased, that worker receives no further claim. |
| `affinity_key_field` | Input field copied onto `node_execution.affinity_key` at activation. |
| `prefer_previous_worker` | Soft preference for the worker that last completed the same key. |
| `prefer_continue_group` | Soft preference for READY rows whose key already has a success. |
| `require_previous_worker` | Hard pin: after a pinned action of the key has succeeded, a later pinned action is claimable by the worker that completed the most recent one. An exclusive pinned producer is not constrained, and a new run of the same action is not pinned to its own prior success. |

`desired_state` on `wf.worker` is `ACTIVE`, `DRAINING`, or `STOPPING`. Claim echoes `command` `NONE`, `DRAIN`, or `STOP`. Draining and stopping workers receive no new task.

## Test bed script

`workflow_engine/sql_pg/deploy_test_bed.sh` applies `wf_instance_extension.sql`, `wf_test_bed_schema.sql`, `wf_test_bed_worker.sql`, `wf_two_group_test_seed.sql`, `wf_mc_two_group_test_seed.sql`, and `wf_test_bed_run.sql`. The two seed files, and `instance_context_examples/`, are not in this repository, so the script stops when it reaches the first missing file. The schema, worker, and run scripts that are present define `wf.test_bed_run`, `wf.test_bed_task_log`, and `wf.sp_test_bed_run_workflow` once the missing seeds are supplied by the caller.

Example workflow seed SQL files are not in the PostgreSQL `SCRIPTS` array in this repository.
