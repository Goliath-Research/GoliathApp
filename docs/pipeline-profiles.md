# Pipeline profiles

Pipeline profiles and procedures are application documents stored in `cfg.pipeline_profile` and `cfg.assay_procedure`. GoliathApp is generic: it does not seed science flags or interpret an application's keys.

`workflow_engine/domain/pipeline_profiles.py` applies only generic rules unless a descendant application registers a `goliath.application_profiles` entry point (see `workflow_engine/domain/application_extension.py`). Without a hook, a profile or procedure contributes its `actionConfig` and the scalar keys the instance does not already set, and **no scope flags** are seeded. When the hook defines any of the functions below, the platform delegates to it:

| Hook | Purpose |
|------|---------|
| `seed_pipeline_scope_flags(context, *, action_config)` | Scope flags for `IF` nodes (modality, modes, presets) |
| `apply_pipeline_profile(context, profile, *, action_config)` / `apply_pipeline_procedure(context, procedure)` | Profile / procedure merge rules |
| `validate_procedure_analyte(context)`, `context_modality(context)` | Application checks |
| `PIPELINE_FLAG_DEFAULTS` | Flag names and defaults |
| `enrich_instance_context(context)` or `enrich_project_context(context, project_path)` | Project-derived context keys |
| `load_profile` / `load_procedure` | Resolve a name or path to a document |

Named presets, modality aliases, and science flags live in the application's hook, not in this repository. GoliathOmics documents its flags in [its config registry](https://goliath-research.github.io/GoliathOmics/usage/19-config-registry/) and [sample-prep usage](https://goliath-research.github.io/GoliathOmics/usage/03-sample-prep-and-qc/).

Programs that need extra context variables in the root scope declare them with `scopeDefaults` (the compiler only adds `projectPath` itself). See [Workflow compiler](workflow-compiler.md).

## Precedence

`enrich_instance_context` in `workflow_engine/domain/workflow_context.py` documents the merge order, highest first: instance, then procedure, then profile or mode, then analyte, then site. The function rebuilds `actionConfig` in that order so a procedure value of JSON null can clear a profile key.

Published site documents are loaded with `portal.fn_published_site_document` (by `site_id`, or the published `default` site). The function is generic: it returns `document_json` and does not interpret keys. When it returns null, callers may fall back to the work-root site manifest.

Child applications register the catalog data type of each config kind with `cfg.sp_register_kind_document_type`. Operators then edit Site settings and Pipeline profiles field by field in the generic typed grid. Kinds with no registered type are view-only. GoliathApp does not ship a free-form JSON editor. See [Operator portal guide](operator-portal-guide.md).

That enrichment imports an optional external profile-path package (project load, site manifest, modality gate, sample-arm layout). Those modules are not in this repository. The local engine calls `finalize_instance_context` and, on `ImportError`, `FileNotFoundError`, or `ValueError`, logs the failure and runs with the context it already has. `goliath-workflow-run --compile-only` does not enrich.

`seed_pipeline_scope_flags` itself has no flags on a platform-only install. Tests in `workflow_engine/tests/test_pipeline_scope_flags.py` call it directly.

## Generic merge

`apply_pipeline_profile` and `apply_pipeline_procedure` deep-merge `actionConfig` when no application hook is installed. The instance overlay wins, and a JSON null deletes the key. Scalar keys already present on the instance are left unchanged. Structural keys (`pipelineProfile`, `actionConfig`, `step_config_overrides`, `catalog`) are not copied as plain scope values.

`cfg` kind `pipeline_profile` is one of the file-store kinds. `goliath-cfg` can upsert and materialize a profile document. Procedure packs use kind `assay_procedure`.

## Loading a named profile

`load_profile` and `load_procedure` are provided by the application hook (or, without one, by `application_extension`: a filesystem path that exists is read as JSON; a bare name is unknown). Mode overlays, profile directories, and deprecated name maps are application content.
