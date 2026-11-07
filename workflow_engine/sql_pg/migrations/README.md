# Optional PostgreSQL migrations (`workflow_engine/sql_pg/migrations/`)

Files here are **not** run by [`apply_schema.sh`](../apply_schema.sh). Operators run them explicitly after a successful full schema apply, usually against a **production or integration** database that already has `portal."NavTree"` data.

For platform DDL order and idempotent apply, see [docs/schema-apply.md](../../../docs/schema-apply.md). For NavTree → Meta bridge semantics, see [docs/nav-tree-meta.md](../../../docs/nav-tree-meta.md) and [docs/deploy-nav-tree-migration.md](../../../docs/deploy-nav-tree-migration.md).

## NavTree → Meta (`20261107_*`)

Introduced in PR [#55](https://github.com/Goliath-Research/GoliathApp/pull/55).

| Step | Script (exact path) | Mutates data? | Purpose |
| --- | --- | --- | --- |
| 0 — Backup | *Provider snapshot / branch* (see deploy guide) | No | Mandatory before step 2 on shared DBs |
| 1 — DDL | [`../apply_schema.sh`](../apply_schema.sh) (includes `portal_nav_meta.sql`) | DDL only | Install `portal/NavNode`, bridge column, APIs |
| 2a — Preflight (read-only) | [`20261107_nav_tree_meta__00_preflight_readonly.sql`](20261107_nav_tree_meta__00_preflight_readonly.sql) | **No** | Catalog present, counts, sample rows |
| 2b — Backfill dry-run (not read-only) | `SELECT * FROM portal.sp_nav_backfill_meta(true);` | **Yes** (catalog; see below) | Report `would_create` rows; **does not** backfill `MetaObjID` |
| 3 — Backfill apply | [`20261107_nav_tree_meta_backfill.sql`](20261107_nav_tree_meta_backfill.sql) or `SELECT * FROM portal.sp_nav_backfill_meta(false);` | **Yes** (inserts Meta objs + links; updates `MetaObjID`) | One-time / idempotent backfill |
| 4 — Verify (read-only) | [`20261107_nav_tree_meta__99_verify_readonly.sql`](20261107_nav_tree_meta__99_verify_readonly.sql) | **No** | Post-check invariants |

### Prerequisites

- PostgreSQL **15+** (17+ recommended); `ltree` extension (created by platform DDL).
- Full `apply_schema.sh` completed successfully on the target database **at the merge commit** (must include `meta_model_tree_maintenance.sql` and `portal_nav_meta.sql`).
- Role with rights to `INSERT`/`UPDATE` on `Meta.*` and `portal."NavTree"` for backfill and for `sp_nav_backfill_meta` (including dry-run). **Read-only database roles** may run only the preflight/verify `.sql` files.

### `sp_nav_backfill_meta(true)` is not read-only

Every call runs `portal.sp_nav_ensure_meta_catalog()` first, which may **insert or update** platform catalog state (`Meta.Classes` / `Fields` / `MetaLinks`, `wf.data_type`, class view regeneration). Dry-run mode (`true`) **only** skips navigation backfill (`MetaObjID`, `Meta.Objs`, tree links); it is **not** equivalent to the true read-only scripts in step 2a/4. Run it only after backup on targets that authorize catalog writes, or after DDL (`apply_schema.sh` / `portal_nav_meta.sql`) has already ensured the catalog.

### Safe re-run

| Script / call | Re-run safety |
| --- | --- |
| `apply_schema.sh` | Idempotent (CREATE OR REPLACE / IF NOT EXISTS) |
| Preflight / verify `.sql` | Read-only `SELECT`; unlimited |
| `sp_nav_backfill_meta(true)` | Idempotent catalog ensure + report; may write catalog |
| `sp_nav_backfill_meta(false)` / backfill `.sql` | Skips rows that already have `MetaObjID`; safe to repeat |

### Backup guidance

On **Neon** (and similar): create a **branch** or provider snapshot **before** step 3; name it with date and ticket (pattern used in platform decoupling: `backup-*-YYYYMMDD`). Do **not** drop `portal."NavTree"` or legacy RBAC tables. Roll back by restoring the branch / snapshot if verification fails.

### Legacy migrations in this folder

| File | Notes |
| --- | --- |
| `20260822_drop_e_portal.sql` | e_portal cutover |
| `20260824_data_type_schema_json.sql` | `wf.data_type.schema_json` alignment |
| `20261105_meta_model_phase_a.sql` | Historical; prefer full apply list for greenfield |
