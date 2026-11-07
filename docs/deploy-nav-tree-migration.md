# Deploy: NavTree Meta bridge (backup-first)

Use this runbook **after** PR [#55](https://github.com/Goliath-Research/GoliathApp/pull/55) is merged to `main` and the coordinator deploys the **exact merged commit**. This document does not perform deploy steps itself; it records order, script paths, and access assumptions from [deployment.md](deployment.md) and [decoupling-plan.md](decoupling-plan.md).

**Do not** apply backfill before a verified backup. **Do not** drop legacy `portal."NavTree"` or `Role2Node`.

## Intended environment (integration / `goliath-test`)

| Layer | Documented owner | Notes |
| --- | --- | --- |
| PostgreSQL + GoliathApp DDL | GoliathApp `apply_schema.sh` | Hosted Postgres (e.g. Neon); database naming per decoupling **D8** in [decoupling-plan.md](decoupling-plan.md) |
| Gateway + workers + `/work` | Extension app **`goliath-test`** profile | Playbook lives in the **extension application repository**, not GoliathApp |
| Exograph / portal-only | **`goliath-exo`** | `deploy/targets/goliath-exo.json` |

The coordinator holds integration-specific hostnames, libpq URLs, release tag pins, and gateway unit names outside this neutral platform doc. Treat the live integration stack as **not upgraded** until DDL, backfill, and verify scripts succeed on the **merged App SHA**.

## Access (use existing approved infra only)

| Target | How operators reach it |
| --- | --- |
| Hosted Postgres | Provider console (branch/snapshot) + `psql` with existing org libpq secrets (same pattern as decoupling D8 Neon backup) |
| Integration gateway | SSH to the integration VPS using team-approved keys; restart the gateway unit only **after** DB verify passes — gateway is not a schema apply path |
| CI disposable Postgres | PR workflow service + `POSTGRES_*` env (validation only) |

Workers remain **gateway-only**; no worker holds DSN for schema migration.

## Ordered procedure

1. **Freeze writes (coordination)** — pause portal nav registration jobs if any; no destructive DDL.
2. **Backup** — provider branch or snapshot (name e.g. `backup-nav-tree-meta-YYYYMMDD`) **before** any backfill.
3. **Deploy App commit** — checkout **merged SHA**; run full `workflow_engine/sql_pg/apply_schema.sh` (must include `meta_model_tree_maintenance.sql` + `portal_nav_meta.sql`).
4. **Preflight (read-only)** —  
   `psql … -v ON_ERROR_STOP=1 -f workflow_engine/sql_pg/migrations/20261107_nav_tree_meta__00_preflight_readonly.sql`
5. **Backfill dry-run (not read-only)** — `SELECT * FROM portal.sp_nav_backfill_meta(true);` — reports rows that would backfill; **always** runs `portal.sp_nav_ensure_meta_catalog()` (may write Meta catalog state). Does **not** perform navigation backfill. Requires the same backup/mutation authorization as step 6; use step 4 for true read-only checks.
6. **Backfill** (only if preflight OK and backup verified) —  
   `psql … -v ON_ERROR_STOP=1 -f workflow_engine/sql_pg/migrations/20261107_nav_tree_meta_backfill.sql`  
   or `SELECT * FROM portal.sp_nav_backfill_meta(false);`
7. **Verify (read-only)** —  
   `psql … -v ON_ERROR_STOP=1 -f workflow_engine/sql_pg/migrations/20261107_nav_tree_meta__99_verify_readonly.sql`  
   Expect `navtree_missing_metaobjid = 0`, `orphan_metaobj = 0`, `nav_without_treenode = 0`.
8. **Extension apps** — descendant repositories require **no API change** for `portal.sp_nav_register_node`; optional smoke on a throwaway provider branch first.
9. **Gateway** — bounce the gateway service only if a release artifact pin changes; schema is DB-side.

## Rollback

Restore the provider branch/snapshot from step 2. `MetaObjID` backfill is forward-only; rollback is **restore**, not inverse SQL.

## Script index

Canonical index: `workflow_engine/sql_pg/migrations/README.md` in the repository.

## Blockers checklist (pre-deploy)

- [ ] Merged SHA recorded and checked out on deploy runner
- [ ] Backup branch/snapshot exists and is named
- [ ] `apply_schema.sh` succeeded on target
- [ ] Preflight SQL OK
- [ ] Verify SQL shows zero missing `MetaObjID` after backfill
- [ ] Extension-app release pin includes merged App commit (if using version tags)

## Related

- [nav-tree-meta.md](nav-tree-meta.md) — contract and API
- [database-population.md](database-population.md) — descendant registration
- [schema-apply.md](schema-apply.md) — DDL order
