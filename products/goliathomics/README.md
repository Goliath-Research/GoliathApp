# GoliathOmics product package (GoliathApp-hosted)

GoliathOmics is a **child application** of GoliathApp. This directory holds SQL seeds and apply scripts that run **after** the generic GoliathApp baseline on a **dedicated PostgreSQL database**. GoliathApp core DDL and seeds remain product-neutral.

## Target database name (parameter)

| Environment | Database name | Notes |
|-------------|---------------|--------|
| Production (planned) | `GoliathOmics_v2` | **Do not create until David approves.** |
| Legacy (frozen) | `GoliathOmics` | Do not rename or apply this package until David schedules `GoliathOmics_legacy` cutover. |
| CI / local | `goliathomics_package_test` (ephemeral) | Created by pytest only. |

Set libpq variables (`PGHOST`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`) before running scripts. The apply script does **not** embed connection secrets.

## Apply order

On an empty database (or after Neon branch create):

1. GoliathApp: `bash workflow_engine/sql_pg/apply_schema.sh`
2. GoliathApp catalog seeds: `seed_semantic_catalog.py`, `seed_action_catalog.py --use-db`
3. GoliathApp: `psql -f workflow_engine/sql_pg/seed_platform_nav_tree.sql`
4. **This package:** `bash products/goliathomics/sql/apply_package.sh`

Re-running steps 1–4 is idempotent.

## Meta model

Omics classes use the **`omics/`** namespace and subclass **`platform/*`** parents (see `01_omics_meta_domain_classes.sql`). Full clinical cutover SQL remains in the [GoliathOmics repository](https://github.com/Goliath-Research/GoliathOmics) (`database/schema/`); this package ships the **portal-hosted MVP** class hierarchy and NavTree branch for multi-product host work.

## Operator portal

Serve this database from the shared platform host with hostname routing — see [multi-product platform host](../../docs/deploy/multi-product-platform-host.md).

## Security

Use the same Meta security stack as GoliathApp (`platform/User`, grants cache, single active role). **`god_architect`** must receive the operator superset (`portal.sp_sync_god_architect_operator_entitlements`) on every database apply.
