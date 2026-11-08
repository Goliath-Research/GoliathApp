# Platform visualization (frontend)

GoliathApp ships shared UI packages for descendant operator applications. Backend contracts (`portal.sp_*`, Meta JSON Schema, semantic registry) live in PostgreSQL; this tree adds **typed presentation** (icons, badges, shell primitives) without browser database credentials.

## Packages (P0 implemented)

| Package | Status | Role |
|---------|--------|------|
| `@goliath/ui` | **P0** | Allowlisted Lucide icons, kind defaults, class override resolution, `ObjectBadge`, theme CSS |
| `@goliath/client` | **P1** | `GoliathUiManifest`, `createPlatformBffClient`, session/nav types |
| `@goliath/platform-ui` | **P0** | Fixture demo table/tree using shared badges (not descendant product screens) |
| `@goliath/platform-host` (`apps/platform-host`) | **P0 host + P1 BFF** | Runnable shell: `/`, `/fixture`, `/app`, session/nav APIs — [deploy/platform-host.md](deploy/platform-host.md), [P1 auth](deploy/platform-host-p1-auth.md) |

Install path for child repos: depend on **published semver tarballs** (`npm pack` / future registry). In this monorepo, `npm ci` + workspace builds apply. Run `npm run verify:consumer` to simulate an external child install.

### Icon contract

- Every `PlatformObjectKind` (see `packages/ui/src/kinds.ts`) has a deterministic default icon key; `platform_generic` is the final fallback.
- Icons are **allowlisted keys** → Lucide components (`packages/ui/src/icons/allowlist.ts`). No SVG/JS/CSS from the database.
- Class-specific icons: child **build-time manifest** maps Meta class FQN → allowlisted key. Resolution order: explicit key → exact class → nearest ancestor → kind default → generic (`packages/ui/src/icons/resolve.ts`).
- Invalid keys and ancestry cycles produce diagnostics and safe fallbacks (`platform:unknown` / kind default).

### Child extension (no Python→React loading)

```typescript
// child: ui-manifest.ts (bundled at build time)
export const goliathUiManifest = {
  appId: "my_app",
  classIconOverrides: {
    "my_app/StudyCase": "platform:collection",
  },
  editorComponents: {
  ...
```

Validate overrides with `diagnoseUiManifest` from `@goliath/client` in CI. Editor React components are registered only in the child bundle; keys must stay stable across releases.

### Licensing

`@goliath/ui` renders icons via **lucide-react** (ISC). See `packages/ui/NOTICE`.

## Phased roadmap

| Phase | Scope | Status |
|-------|--------|--------|
| **P0** | Workspace, `@goliath/ui` icons/badges/tokens, fixture demo, tests, consumer pack verify | **Implemented (this PR)** |
| **P1** | Same-origin BFF, `portal.sp_session_*`, `sp_session_operator_nav_tree`, httpOnly cookie (OIDC bridge pending) | **In review (stacked on PR #58)** |
| **P2** | Meta hierarchy + JSON Schema editors (`portal.sp_get_data_type`, ObjValues writes via portal procs) | Pending |
| **P3** | Workflow designer/monitor (DomainPrograms, defs, runs) | Pending |
| **P4** | Semantic + admin screens (`sp_run_semantic_request`, RBAC admin procs) | Pending |
| **P5** | Declarative views/dashboards (semantic request widgets only) | Pending |
| **P6** | Two-child adoption (e.g. portal + one greenfield app on shared packages) | Pending |

## Seeds and apply order (future)

When UI metadata moves to PostgreSQL, platform seeds run **before** child apps in the existing [schema apply](schema-apply.md) order. P0 does **not** add DDL; presentation overrides remain in child manifests until a registry table is designed (P2+).

## Commands

```bash
npm ci
npm run build
npm test
npm run verify:consumer
```

MkDocs: this page is linked from [architecture.md](architecture.md).
