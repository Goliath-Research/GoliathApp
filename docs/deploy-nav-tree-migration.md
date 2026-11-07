# Deploy: NavTree Meta bridge (backup-first)

Use this runbook **after** PR [#55](https://github.com/Goliath-Research/GoliathApp/pull/55) is merged to `main` and the coordinator deploys the **exact merged commit**. This document does not perform deploy steps itself; it records order, script paths, and access assumptions from repository docs and prior integration context.

**Do not** apply backfill before a verified backup. **Do not** drop legacy `portal."NavTree"` or `Role2Node`.

## Intended environment (integration / `goliath-test`)

From [deployment.md](deployment.md):

| Layer | Documented owner | Notes |
| --- | --- | --- |
| PostgreSQL + GoliathApp DDL | GoliathApp `apply_schema.sh` | Neon-hosted DB name **`GoliathOmics`** retained per [decoupling-plan.md](decoupling-plan.md) D8 |
| Gateway + workers + `/work` | Extension app **`goliath-test`** profile | Playbook lives in the extension repository, not GoliathApp |
| Exograph / portal-only | **`goliath-exo`** | `deploy/targets/goliath-exo.json` |

Prior integration context (not stored in this repo): gateway on **`45.76.21.8`**, unit **`goliath-gateway.service`**, install path **`/opt/goliath-gateway`**, Omics release tag **`v2026.11.6`** may **not** include NavTree Meta DDL until the coordinator pins a newer App commit after merge. Treat production/integration as **not upgraded** until DDL + backfill + verify complete.

## Access (use existing approved infra only)

| Target | How operators reach it (no new credentials in docs) |
| --- | --- |
| Neon `GoliathOmics` | Console branch/snapshot + `psql` with existing org libpq secrets (same as prior D8 apply; see decoupling plan Neon backup pattern) |
| Gateway host | SSH to integration VPS (address above) using team-approved keys; restart **`goliath-gateway.service`** only **after** DB verify passes — gateway is not a schema apply path |
| CI disposable Postgres | PR workflow `postgres` service + `POSTGRES_*` env (validation only) |

GoliathApp workers remain **gateway-only**; no worker holds DSN for schema migration.

## Ordered procedure

1. **Freeze writes (coordination)** — pause portal nav registration jobs if any; no destructive DDL.
2. **Backup** — Neon branch or snapshot (name e.g. `backup-nav-tree-meta-YYYYMMDD`) **before** any backfill.
3. **Deploy App commit** — checkout **merged SHA**; run full `workflow_engine/sql_pg/apply_schema.sh` against the target database (must include `meta_model_tree_maintenance.sql` + `portal_nav_meta.sql`).
4. **Preflight (read-only)** —  
   `psql … -v ON_ERROR_STOP=1 -f workflow_engine/sql_pg/migrations/20261107_nav_tree_meta__00_preflight_readonly.sql`
5. **Dry-run** — `SELECT * FROM portal.sp_nav_backfill_meta(true);` (read-only).
6. **Backfill** (only if preflight OK and backup verified) —  
   `psql … -v ON_ERROR_STOP=1 -f workflow_engine/sql_pg/migrations/20261107_nav_tree_meta_backfill.sql`  
   or `SELECT * FROM portal.sp_nav_backfill_meta(false);`
7. **Verify (read-only)** —  
   `psql … -v ON_ERROR_STOP=1 -f workflow_engine/sql_pg/migrations/20261107_nav_tree_meta__99_verify_readonly.sql`  
   Expect `navtree_missing_metaobjid = 0`, `orphan_metaobj = 0`, `nav_without_treenode = 0`.
8. **Extension app** — Omics (or other descendants) **no code change required** for nav registration APIs; optional: run descendant smoke (`portal.sp_nav_register_node` + RBAC grant) on a throwaway branch first.
9. **Gateway** — bounce `goliath-gateway.service` only if a release artifact pin changes; schema is DB-side.

## Rollback

Restore the Neon branch/snapshot from step 2. `MetaObjID` backfill is forward-only; rollback is **restore**, not inverse SQL.

## Script index

Canonical index: `workflow_engine/sql_pg/migrations/README.md` in the repository.

## Blockers checklist (pre-deploy)

- [ ] Merged SHA recorded and checked out on deploy runner
- [ ] Backup branch/snapshot exists and is named
- [ ] `apply_schema.sh` succeeded on target
- [ ] Preflight SQL OK
- [ ] Verify SQL shows zero missing `MetaObjID` after backfill
- [ ] Omics/gateway pin bumped to include merged App commit (if using release tags)

## Related

- [nav-tree-meta.md](nav-tree-meta.md) — contract and API
- [database-population.md](database-population.md) — descendant registration
- [schema-apply.md](schema-apply.md) — DDL order
