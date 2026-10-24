# GoliathApp Exograph project (semantic layer phase E)

Read-only GraphQL and MCP façade over the `portal` semantic registry and `portal.sp_run_semantic_request`.

## Runtime

- Connect as `goliath_portal` through `EXO_POSTGRES_URL` with `sslmode=verify-full` in production.
- Do **not** set `EXO_POSTGRES_READ_WRITE` (Postgres module stays read-only).
- Align `EXO_JWT_SECRET` (or your OIDC setup) with portal session minting. JWT must carry `session_token` for `runSemanticRequest` (see `PortalAuthContext` in `src/index.exo`).

Example:

```bash
export EXO_POSTGRES_URL='postgres://goliath_portal:SECRET@db.example.com:5432/goliath?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca.pem'
export EXO_JWT_SECRET='…'
third_party/vendor/exograph/0.29.1/linux-x86_64/exo-server
```

MCP profile `semantic_read` is defined in `exo.toml` (`execute_query_semantic_read`).

## Build / test

```bash
python3 scripts/fetch_third_party.py
third_party/vendor/exograph/0.29.1/linux-x86_64/exo build
third_party/vendor/exograph/0.29.1/linux-x86_64/exo test
```

## Deno → `portal.sp_run_semantic_request` spike

`src/semantic.ts` uses the `postgres` npm package as an external Deno dependency to call `portal.sp_run_semantic_request` with the caller's session token from JWT context. This path is required because `Exograph.executeQuery` only runs GraphQL operations.

### Fallback (if direct SQL from Deno is unavailable)

Use unmanaged `@table(managed=false)` types mapped to **security-barrier views** in PostgreSQL. Each view filters rows using `current_setting('goliath.session_token', true)` (or equivalent) resolved from Exograph request context via an interceptor, and delegates to the same RBAC checks as `portal.sp_run_semantic_request`. Prefer the stored-procedure dispatcher when the Deno postgres client works; views are the brownfield escape hatch without widening `goliath_portal` table privileges.
