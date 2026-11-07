# Example SQL (not applied by `apply_schema.sh`)

Scripts here are **documentation samples** for descendant applications. They are **not** part of the ordered `SCRIPTS` array in `apply_schema.sh`.

| File | Purpose |
|------|---------|
| `descendant_acme_child_register_demo.sql` | Neutral `acme_child` pattern: semantic namespace, entity, attributes, NavTree node (see published [Database population](https://goliath-research.github.io/GoliathApp/database-population/) after merge) |
| `docs_bootstrap_minimal_workflow.sql` | Disposable-DB smoke: `wf_repo_create_workflow_graph`, optional `cfg.domain_program` FK row, instance start, `READY` task for `workflow.const_string` (requires `seed_action_catalog.py --use-db`) |
