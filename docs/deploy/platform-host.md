# Platform UI host (GoliathApp-owned)

The **platform host** is a small Next.js process in `apps/platform-host/` that ships the P0 shared UI packages. It is **not** Goliath-portal and does not use PostgreSQL or operator auth.

## What it serves

| Route | Purpose |
|-------|---------|
| `/` | Static overview of P0 scope and build identity |
| `/fixture` | `PlatformFixtureDemo` — labeled fixture rows/tree only |
| `/api/health` | JSON metadata (`status`, `revision`, `version`) — no secrets |

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

The image contains the Next.js **standalone** server only. No database env vars are read.

### Deploying to your target

A **production URL is not configured in this repository**. To put the host on a container platform (DigitalOcean App Platform, Fly.io, Kubernetes, etc.):

1. Build and push the image to **your** registry (credentials not stored here).
2. Set `PORT=3400` (or map platform `PORT` to the process).
3. Set `PLATFORM_HOST_REVISION` to the git SHA you built (for `/api/health`).
4. Optional: `PLATFORM_HOST_VERSION` (default `0.1.0-p0`).

Do not point this host at production PostgreSQL until P1 session transport exists.

## Child applications

Children **depend on the same packages** (`@goliath/ui`, `@goliath/platform-ui`, `@goliath/client`) and either:

- Run their own Next host copying `EXAMPLE_CHILD_EXTENSION` from `apps/platform-host/src/lib/child-extension.ts`, or
- Merge additional routes into a future shared shell API (P1+).

Editor components and `classIconOverrides` are registered in the **child build manifest** (`GoliathUiManifest`), not loaded from Python at runtime.

## Tests

```bash
npm run test:e2e:host   # Playwright smoke (starts host if needed)
```
