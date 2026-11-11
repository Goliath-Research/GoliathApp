# Multi-product platform host (one VM, multiple databases)

The platform host can serve **multiple child products** from a single Node process. Each HTTP hostname selects a **product id**, which selects a **PostgreSQL database** (separate `goliath_portal` login per database). GoliathApp core code stays product-neutral; product-specific seeds and Meta classes live in **child application repositories**.

## Runtime configuration

Set `GOLIATH_PLATFORM_PRODUCTS_JSON` to a JSON document matching `deploy/examples/host-registry.example.json` in the repository root. Each product uses **environment variables derived from its id** (uppercase):

| Variable | Purpose |
|----------|---------|
| `GOLIATH_PRODUCT_<ID>_PORTAL_DB` | Optional full libpq URL override |
| `GOLIATH_PRODUCT_<ID>_PGHOST` | Postgres host |
| `GOLIATH_PRODUCT_<ID>_PGDATABASE` | Database name |
| `GOLIATH_PRODUCT_<ID>_GOLIATH_PORTAL_PASSWORD` | `goliath_portal` role password |

When `GOLIATH_PLATFORM_PRODUCTS_JSON` is **unset**, the host keeps today’s single-database behaviour (`PGHOST`, `PGDATABASE`, `GOLIATH_PORTAL_PASSWORD`, …).

The edge middleware resolves the product from the `Host` header and forwards `x-goliath-product-id` to server handlers.

## Child product on a shared VM (operator approval required)

**Do not execute these steps from automation.** Database creation, secrets, and identity-provider changes require operator approval.

### 1. Databases

| Role | Notes |
|------|--------|
| Platform (GoliathApp) production DB | Unchanged for the primary hostname |
| Child product DB | New database; apply order is owned by the **child application repository** (App baseline, then child package SQL) |

### 2. Platform host environment (single container)

```bash
export GOLIATH_PLATFORM_PRODUCTS_JSON="$(cat /secure/path/host-registry.json)"
export GOLIATH_PRODUCT_GOLIATHAPP_PGHOST=…
export GOLIATH_PRODUCT_GOLIATHAPP_PGDATABASE=…
export GOLIATH_PRODUCT_GOLIATHAPP_GOLIATH_PORTAL_PASSWORD=…
export GOLIATH_PRODUCT_CHILDAPP_PGHOST=…
export GOLIATH_PRODUCT_CHILDAPP_PGDATABASE=…
export GOLIATH_PRODUCT_CHILDAPP_GOLIATH_PORTAL_PASSWORD=…
# OIDC: GOLIATH_AUTH_OIDC_PROVIDERS_JSON — add each product hostname to allowedOrigins
```

Do **not** set `GOLIATH_PLATFORM_HOST_DEV_LOGIN=1` in production.

### 3. Edge proxy (Caddy or equivalent)

Add a vhost for the child hostname that reverse-proxies to the **same** platform-host upstream as the primary app hostname (routing is by `Host` inside the app). TLS must cover the child hostname.

### 4. Identity provider

Register a redirect URI per child hostname: `https://<child-host>/api/auth/oidc/<providerId>/callback` (match `RBAC.IdentityProviders` in that product’s database).

### 5. Verification

- Primary hostname → platform NavTree and branding
- Child hostname → child NavTree (from child package) with Meta security unchanged
- `workflow_engine/scripts/verify_security_meta_migration.sh` on **each** database

## Related

- [Platform host operator portal](platform-host-operator-portal.md) (P6 multi-child)
- [Database population](../database-population.md)
- [God Architect](../platform-god-architect.md)
