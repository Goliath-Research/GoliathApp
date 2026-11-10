# Platform UI host (GoliathApp-owned)

The **platform host** is a Next.js application in `apps/platform-host/` that ships shared UI packages and, when configured with a portal database bridge, the **signed-in operator portal** at `/app`.

## What it serves

| Route | Purpose |
|-------|---------|
| `/` | Public overview of platform UI scope and build identity |
| `/login` | OIDC (and related) operator sign-in |
| `/fixture` | `PlatformFixtureDemo` — labeled fixture rows/tree only (public) |
| `/app` | **Signed-in operator portal** — NavTree, Meta hierarchy, platform surfaces, views/dashboards |
| `/api/health` | JSON metadata (`status`, `revision`, `version`) — no secrets |
| `/api/navigation`, `/api/meta/*`, `/api/portal/*` | Session-gated BFF (requires portal DB + cookie) |

Operator experience, plan, and **required end-user documentation**: [platform-host-operator-portal.md](platform-host-operator-portal.md), [operator-portal-guide.md](../operator-portal-guide.md).

## Local run

```bash
npm ci
npm run build
npm run start:host
# http://127.0.0.1:3400
curl -s http://127.0.0.1:3400/api/health | jq .
```

Development:

```bash
npm run dev --workspace @goliath/platform-host
```

Configure `GOLIATH_PORTAL_*` (see [platform-host-p1-auth.md](platform-host-p1-auth.md)) for `/app` and BFF routes. Without the bridge, `/app` redirects with an unconfigured auth hint.

## Container image (portable artifact)

Build from the **repository root** (not `apps/platform-host` alone):

```bash
docker build -f apps/platform-host/Dockerfile \
  --build-arg PLATFORM_HOST_REVISION="$(git rev-parse HEAD)" \
  -t goliath-platform-host:local .
docker run --rm -p 3400:3400 \
  -e PLATFORM_HOST_REVISION="$(git rev-parse HEAD)" \
  goliath-platform-host:local
```

The standalone image does not include PostgreSQL. Set portal bridge and OIDC env vars in your deployment for operator sign-in.

### Deploying to your target

1. Build and push the image to **your** registry.
2. Set `PORT=3400` (or map platform `PORT` to the process).
3. Set `PLATFORM_HOST_REVISION` to the git SHA you built (for `/api/health`).
4. Configure portal database connection and OIDC providers for production `/app`.

## Child applications

Children **depend on the same packages** (`@goliath/ui`, `@goliath/platform-ui`, `@goliath/client`) and either:

- Run their own Next host copying `EXAMPLE_CHILD_EXTENSION` from `apps/platform-host/src/lib/child-extension.ts`, or
- Extend the operator portal with additional NavTree nodes and manifest overrides.

Editor components and `classIconOverrides` are registered in the **child build manifest** (`GoliathUiManifest`), not loaded from Python at runtime.

## Tests

```bash
npm run test:e2e:host   # Playwright smoke (starts host if needed)
```
