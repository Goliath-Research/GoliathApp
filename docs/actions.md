# User-defined actions

An action is a row in `wf.workflow_action`, not a Python class in this repository. A workflow graph points ACTION nodes at `action_name`. Workers receive `capability` and `input_json` and return `result_code` plus `output_json`. The product that specializes the platform implements the handler.

## Row

`00_schema.sql` creates `action_name` (unique), `capability`, and `payload_schema_ref`. Later scripts add:

| Source | Columns |
|--------|---------|
| `wf_action_dispatch_metadata.sql` | `execution_mode`, `cli_tool`, `in_process_handler`, `argv_map` |
| `wf_action_dispatch_concurrency.sql` | `max_per_worker`, `exclusive_worker` |
| `wf_action_dispatch_affinity.sql` | `affinity_key_field`, `prefer_previous_worker`, `prefer_continue_group`, `require_previous_worker` |
| `wf_data_type.sql` | `input_type_id`, `output_type_id`, `implementation_status`, `can_pause`, `can_continue`, `can_stop` |

Upsert procedures replace one another as the apply order advances: 3 arguments, then 7, then 9, then the affinity script's wider argument list. Each script drops the previous overload so PostgreSQL does not keep both.

`execution_mode`, `cli_tool`, `in_process_handler`, and `argv_map` are stored for the worker that runs the action. The gateway does not read them when claiming a task. `wf.wf_repo_list_actions` returns the dispatch columns. The gateway has no `GET /v1/actions` route. `goliath_worker.WorkflowRestClient.list_actions` calls `GET /actions`, which this gateway answers with 404.

## Data types and schemas

`wf.data_type` is the type registry (`name`, `version`, `status` of `draft` / `published` / `retired`, `kind`, optional `schema_json`). Kinds are `string`, `int`, `bool`, `number`, `datetime`, `bytes`, `enum`, `object`, `array`, and `any`. Arrays point at `element_type_id`. Objects have `wf.data_type_field` rows. Enums have `wf.data_type_enum_value` rows.

`wf.wf_repo_upsert_data_type` writes a type. `schema_json` is the JSON Schema document. The kind and field tables are an index over that document.

`wf.workflow_action_schema` (`wf_action_schema.sql`) still stores input and output JSON blobs per action. Its own comment marks seeding of that table as retired: `wf.wf_repo_get_action_schema` is redefined in `wf_data_type.sql` to prefer the data-type `schema_json`, then the legacy blob, then an empty object. The table remains so older rows still resolve.

`cfg.action_definition` is created by `cfg_registry_tables.sql`. The config CLI does not write it. `goliath-cfg sync-actions` ignores `--from-json`, `--seed-wf`, and `--draft` and always tries to seed `wf` by executing `workflow_engine/sql_pg/seed_action_catalog.py`. That file is not in this repository, so the command raises `FileNotFoundError`.

## Defining an action from this tree

1. Insert or upsert `wf.workflow_action` through `wf.wf_repo_upsert_workflow_action` after the dispatch scripts have been applied, so the wide argument list is the one installed.
2. Upsert input and output types with `wf.wf_repo_upsert_data_type` and point `input_type_id` / `output_type_id` at them.
3. Author a DomainProgram step whose `action` or `do` is that `action_name`. With no product catalog installed, the compiler keeps the step's `with` template.
4. Register a worker whose `capabilities` include the action's `capability`, or `["*"]`.

`goliath-cfg scaffold-action NAME --define` builds an in-memory document (capability defaults to the text before the first dot) and writes files under the repo root:

- `schemas/tasks/<schema_id>.input.schema.json` and `.output.schema.json`
- `workers/methyl_worker/scaffolded/<slug>.py` (handler stub that raises `NotImplementedError`)
- a catalog note and a DomainProgram snippet in that same directory
- `workers/methyl_worker/task_models/<slug>_scaffold.py` unless `--no-pydantic`

Those paths are the product worker layout. This repository does not contain `workers/methyl_worker/` until the command creates the stub directory. Scaffold does not insert the database row. Without `--define`, the command reads `schemas/actions/catalog.json`, which is not in this tree, and raises `KeyError`.

## What a worker does with the row

The claim response carries `action_name`, `capability`, and `input_json`. Handler selection (`execution_mode`, CLI argv, in-process function) is product code. `goliath_worker` submits the result and does not dispatch a handler.
