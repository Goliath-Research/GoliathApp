# Deployment targets

GoliathApp ships provider-neutral target descriptors under `deploy/targets/` for platform stacks that need PostgreSQL and the semantic read layer. Worker fleets and the REST gateway are provisioned from descendant repositories (see GoliathOmics `goliath-test`).

## goliath-exo

Use **`goliath-exo`** when standing up:

- PostgreSQL with GoliathApp schema apply and semantic seed
- Portal backends via `goliath_app.portal.PortalClient` or Exograph GraphQL
- Optional MCP agents via Exograph profile `semantic_read`

Files:

| File | Role |
|------|------|
| `deploy/targets/goliath-exo.json` | Active target template with secret placeholders |
| `deploy/targets/goliath-exo.example.json` | Copy-and-customize starter |
| `deploy/targets/target.schema.json` | JSON schema for validation |
| `deploy/scripts/deploy_goliath_exo.sh` | Ordered checklist (no cloud-specific provisioner) |

Exograph install steps and environment variables are also summarized in [schema apply](schema-apply.md#exograph-and-mcp-optional) and `exo/README.md`.

## goliath-test (Omics)

The **`goliath-test`** name is reserved for the GoliathOmics integration stack (gateway, workers, shared `/work` storage). Do not reuse that name for the Exograph profile.
