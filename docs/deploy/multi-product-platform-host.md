# Multi-product platform host (one VM, multiple databases)

The platform host can serve **multiple child products** from a single Node process. Each HTTP hostname selects a **product id**, which selects a **PostgreSQL database** (separate `goliath_portal` login per database). GoliathApp core code stays product-neutral; product-specific seeds and Meta classes live under `products/<product_id>/` or in the child application repository.

## Runtime configuration

Set `GOLIATH_PLATFORM_PRODUCTS_JSON` to a JSON document matching [`products/host-registry.example.json`](../../products/host-registry.example.json). Each product uses **environment variables derived from its id** (uppercase):

| Variable | Purpose |
|----------|---------|
| `GOLIATH_PRODUCT_<ID>_PORTAL_DB` | Optional full libpq URL override |
| `GOLIATH_PRODUCT_<ID>_PGHOST` | Postgres host |
| `GOLIATH_PRODUCT_<ID>_PGDATABASE` | Database name |
| `GOLIATH_PRODUCT_<ID>_GOLIATH_PORTAL_PASSWORD` | `goliath_portal` role password |

When `GOLIATH_PLATFORM_PRODUCTS_JSON` is **unset**, the host keeps today’s single-database behaviour (`PGHOST`, `PGDATABASE`, `GOLIATH_PORTAL_PASSWORD`, …).

The edge middleware resolves the product from the `Host` header and forwards `x-goliath-product-id` to server handlers.

## GoliathApp + GoliathOmics on 45.63.16.235 (David approval required)

**Do not execute these steps from automation.** David must approve secrets, database creation, and Entra changes.

### 1. Neon databases (no touch to legacy)

| Database | Status |
|----------|--------|
| Existing `GoliathOmics` | **Frozen** — becomes `GoliathOmics_legacy` only when David renames |
| New `GoliathOmics_v2` (working name) | Create empty branch DB; apply GoliathApp baseline + Omics package (see `products/goliathomics/README.md`) |
| GoliathApp production DB | Unchanged (`app.goliathresearch.com`) |

### 2. Apply order (new Omics v2 database)

1. `bash workflow_engine/sql_pg/apply_schema.sh` (GoliathApp DDL + Meta security stack)
2. Python catalog seeds (`seed_semantic_catalog.py`, `seed_action_catalog.py --use-db`) per [database-population.md](../database-population.md)
3. `psql -f workflow_engine/sql_pg/seed_platform_nav_tree.sql`
4. `bash products/goliathomics/sql/apply_package.sh` (parameter `TARGET_PGDATABASE`)

Each database needs its own `goliath_portal` role password (Neon console or `database_gateway_roles.sql` after apply).

### 3. Platform host environment (single container)

```bash
export GOLIATH_PLATFORM_PRODUCTS_JSON="$(cat /secure/path/host-registry.json)"
export GOLIATH_PRODUCT_GOLIATHAPP_PGHOST=…
export GOLIATH_PRODUCT_GOLIATHAPP_PGDATABASE=…
export GOLIATH_PRODUCT_GOLIATHAPP_GOLIATH_PORTAL_PASSWORD=…
export GOLIATH_PRODUCT_GOLIATHOMICS_PGHOST=…
export GOLIATH_PRODUCT_GOLIATHOMICS_PGDATABASE=GoliathOmics_v2
export GOLIATH_PRODUCT_GOLIATHOMICS_GOLIATH_PORTAL_PASSWORD=…
# OIDC: GOLIATH_AUTH_OIDC_PROVIDERS_JSON with allowedOrigins including https://omics.goliathresearch.com
```

Do **not** set `GOLIATH_PLATFORM_HOST_DEV_LOGIN=1` in production.

### 4. Caddy (same VM as app)

Replace the omics placeholder with a reverse_proxy to the **same** platform-host upstream as `app.goliathresearch.com` (hostname-based routing inside the app). TLS certificates for `omics.goliathresearch.com` must cover the new vhost.

### 5. Entra ID

Register redirect URI: `https://omics.goliathresearch.com/api/auth/oidc/<providerId>/callback` (match the provider id configured in the Omics database’s `RBAC.IdentityProviders` row). The App registration may be shared or per-product depending on David’s tenant layout.

### 6. Verification

- Sign in on `app.*` → GoliathApp NavTree and branding
- Sign in on `omics.*` with God Architect active role → non-empty nav + meta workspaces (god_architect operator superset applies per database)
- `workflow_engine/scripts/verify_security_meta_migration.sh` on each database

## Related

- [Platform host operator portal](platform-host-operator-portal.md) (P6 multi-child)
- [Database population](../database-population.md)
- [God Architect](../platform-god-architect.md)
