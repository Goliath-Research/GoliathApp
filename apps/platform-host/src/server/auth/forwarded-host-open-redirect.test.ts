import { describe, expect, it, vi } from "vitest";
import { createOidcTransaction, buildOidcTransactionCookie } from "./state-cookie";
import { PortalSessionDeniedError } from "@/server/portal/bridge";

/**
 * Spec for the unvalidated X-Forwarded-Host / Host origin used on sign-in.
 * These assertions fail while the login page, the provider list, and the OIDC
 * callback reflect that host. They pass once those responses stay on an
 * allowlisted origin, or on the request URL origin when the forwarded host is
 * not allowlisted. An allowlisted forwarded host must still be used, which is
 * how the host works behind a TLS proxy.
 *
 * A check that reads the header again after allowlisting must not observe a
 * different host. The sequenced-header cases return the allowlisted host on
 * the first read and an attacker host on every later read.
 */

const ALLOWED_ORIGIN = "https://app.example.com";
const ATTACKER_HOST = "evil.example";
const REQUEST_URL = "http://127.0.0.1:3400/api/auth/oidc/entra/callback?code=placeholder&state=placeholder";

const bridge = vi.hoisted(() => ({
  configured: false,
  open: vi.fn(),
}));

const oidc = vi.hoisted(() => ({
  exchangeOidcCallback: vi.fn(),
}));

const headerState = vi.hoisted(() => ({
  current: new Headers() as Headers,
}));

vi.hoisted(() => {
  process.env.GOLIATH_AUTH_OIDC_PROVIDERS_JSON = JSON.stringify([
    {
      providerId: "entra",
      displayName: "Entra",
      issuer: "https://issuer.example/tenant",
      clientId: "client-id-placeholder",
      clientSecret: "client-secret-placeholder",
      scopeId: 1,
      scopes: ["openid"],
      allowedOrigins: ["https://app.example.com"],
    },
  ]);
  process.env.GOLIATH_AUTH_STATE_SECRET = "placeholder-state-key";
  delete process.env.PGHOST;
  delete process.env.PGDATABASE;
  delete process.env.GOLIATH_PORTAL_PASSWORD;
  delete process.env.GOLIATH_PORTAL_DB;
  delete process.env.POSTGRES_HOST;
  delete process.env.POSTGRES_DB;
  delete process.env.POSTGRES_PASSWORD;
  delete process.env.PGPASSWORD;
});

vi.mock("server-only", () => ({}));

vi.mock("next/headers", () => ({
  headers: async () => headerState.current,
  cookies: async () => ({
    get(name: string) {
      if (name === "goliath_platform_session") return { value: "placeholder-session-token" };
      return undefined;
    },
  }),
}));

vi.mock("@goliath/ui", () => ({
  ObjectBadge: () => null,
}));

vi.mock("@/server/auth/oidc", () => ({
  exchangeOidcCallback: (...args: unknown[]) => oidc.exchangeOidcCallback(...args),
  buildOidcAuthorizationUrl: vi.fn(),
}));

vi.mock("@/server/portal/bridge", async () => {
  const actual = await vi.importActual<typeof import("@/server/portal/bridge")>("@/server/portal/bridge");
  return {
    ...actual,
    isPortalBridgeConfigured: () => bridge.configured,
    portalSessionOpenForScopeIdentity: (...args: unknown[]) => bridge.open(...args),
    portalSessionSecurity: async () => ({ users: [] }),
    portalSessionPlatformQuery: async () => [],
  };
});

vi.mock("@goliath/platform-ui", () => ({
  MetaClassHierarchyList: () => null,
}));

vi.mock("@/components/ActionMethodsWorkspace", () => ({ ActionMethodsWorkspace: () => null }));
vi.mock("@/components/QueryRecordGrid", () => ({ QueryRecordGrid: () => null }));
vi.mock("@/components/RecordEditorWorkspace", () => ({ RecordEditorWorkspace: () => null }));
vi.mock("@/components/DomainProgramStructurePanel", () => ({ DomainProgramStructurePanel: () => null }));
vi.mock("@/components/RunInspector", () => ({ RunInspector: () => null }));
vi.mock("@/components/WorkflowGraphWorkspace", () => ({ WorkflowGraphWorkspace: () => null }));
vi.mock("@/components/AdminGrantsWorkspace", () => ({ AdminGrantsWorkspace: () => null }));
vi.mock("@/components/AdminRolesWorkspace", () => ({ AdminRolesWorkspace: () => null }));
vi.mock("@/components/AdminUsersWorkspace", () => ({ AdminUsersWorkspace: () => null }));
vi.mock("@/components/MetaTreePanel", () => ({ MetaTreePanel: () => null }));
vi.mock("@/components/MetaWorkbenchPanel", () => ({ MetaWorkbenchPanel: () => null }));
vi.mock("@/components/OperatorDashboardsWorkspaceServer", () => ({
  OperatorDashboardsWorkspaceServer: () => null,
}));
vi.mock("@/components/OperatorViewsWorkspaceServer", () => ({
  OperatorViewsWorkspaceServer: () => null,
}));
vi.mock("@/components/SemanticPackageExport", () => ({ SemanticPackageExport: () => null }));

type HeaderSource = Headers | { get(name: string): string | null };

function asRequest(url: string, headers: HeaderSource): Request {
  return { url, headers } as Request;
}

function attackerHeaders(extra?: Record<string, string>): Headers {
  return new Headers({
    host: "app.example.com",
    "x-forwarded-host": ATTACKER_HOST,
    "x-forwarded-proto": "https",
    ...extra,
  });
}

/**
 * First read of x-forwarded-host is the allowlisted host. Every later read is
 * the attacker host. A fix that looks the header up again between the
 * allowlist check and the redirect fails.
 */
function rereadHeaders(extra?: Record<string, string>): HeaderSource {
  const base = new Headers({
    host: "app.example.com",
    "x-forwarded-proto": "https",
    ...extra,
  });
  let forwardedReads = 0;
  return {
    get(name: string) {
      if (name.toLowerCase() === "x-forwarded-host") {
        forwardedReads += 1;
        return forwardedReads === 1 ? "app.example.com" : ATTACKER_HOST;
      }
      return base.get(name);
    },
  };
}

function assertSafeLocation(location: string | null, requestUrl: string, pathAndQuery: string) {
  expect(location, "missing Location").toBeTruthy();
  const url = new URL(location!);
  expect(`${url.pathname}${url.search}`, location!).toBe(pathAndQuery);
  expect(url.hostname, location!).not.toBe(ATTACKER_HOST);
  const requestOrigin = new URL(requestUrl).origin;
  expect([ALLOWED_ORIGIN, requestOrigin]).toContain(url.origin);
}

function collectProps(node: unknown, found: Record<string, string>[]): void {
  if (node == null || typeof node !== "object") return;
  if (Array.isArray(node)) {
    for (const child of node) collectProps(child, found);
    return;
  }
  const props = (node as { props?: Record<string, unknown> }).props;
  if (!props) return;
  const record: Record<string, string> = {};
  for (const key of ["href", "signInUrl"]) {
    if (typeof props[key] === "string") record[key] = props[key];
  }
  if (Object.keys(record).length) found.push(record);
  collectProps(props.children, found);
}

async function callback(request: Request, providerId = "entra") {
  const { GET } = await import("@/app/api/auth/oidc/[providerId]/callback/route");
  return GET(request, { params: Promise.resolve({ providerId }) });
}

describe("unvalidated forwarded host on operator sign-in", () => {
  it("callback unknown-provider redirect does not follow an attacker X-Forwarded-Host", async () => {
    bridge.configured = false;
    const headers = attackerHeaders();
    headerState.current = headers;
    const response = await callback(asRequest(REQUEST_URL, headers), "not-a-provider");
    assertSafeLocation(response.headers.get("location"), REQUEST_URL, "/login?error=provider");
  });

  it("callback bridge redirect does not follow an attacker X-Forwarded-Host", async () => {
    bridge.configured = false;
    const headers = attackerHeaders();
    headerState.current = headers;
    const response = await callback(asRequest(REQUEST_URL, headers));
    assertSafeLocation(response.headers.get("location"), REQUEST_URL, "/login?error=bridge");
  });

  it("callback transaction redirect does not follow an attacker X-Forwarded-Host", async () => {
    bridge.configured = true;
    const headers = attackerHeaders();
    headerState.current = headers;
    const response = await callback(asRequest(REQUEST_URL, headers));
    assertSafeLocation(response.headers.get("location"), REQUEST_URL, "/login?error=transaction");
  });

  it("callback state redirect does not follow an attacker X-Forwarded-Host", async () => {
    bridge.configured = true;
    const tx = createOidcTransaction({ providerId: "entra", scopeId: 1 });
    const headers = attackerHeaders({ cookie: buildOidcTransactionCookie(tx) });
    headerState.current = headers;
    const response = await callback(asRequest(REQUEST_URL, headers));
    assertSafeLocation(response.headers.get("location"), REQUEST_URL, "/login?error=state");
  });

  it("callback oauth redirect does not follow an attacker X-Forwarded-Host", async () => {
    bridge.configured = true;
    const tx = createOidcTransaction({ providerId: "entra", scopeId: 1 });
    const headers = attackerHeaders({ cookie: buildOidcTransactionCookie(tx) });
    headerState.current = headers;
    oidc.exchangeOidcCallback.mockRejectedValueOnce(new Error("token exchange failed"));
    const url = `http://127.0.0.1:3400/api/auth/oidc/entra/callback?code=placeholder&state=${encodeURIComponent(tx.state)}`;
    const response = await callback(asRequest(url, headers));
    assertSafeLocation(response.headers.get("location"), url, "/login?error=oauth");
  });

  it("callback not-linked redirect does not follow an attacker X-Forwarded-Host", async () => {
    bridge.configured = true;
    const tx = createOidcTransaction({ providerId: "entra", scopeId: 1 });
    const headers = attackerHeaders({ cookie: buildOidcTransactionCookie(tx) });
    headerState.current = headers;
    oidc.exchangeOidcCallback.mockResolvedValueOnce({
      issuer: "https://issuer.example/tenant",
      subject: "subject-placeholder",
      snapshot: "{}",
    });
    bridge.open.mockRejectedValueOnce(new PortalSessionDeniedError("external identity is not linked"));
    const url = `http://127.0.0.1:3400/api/auth/oidc/entra/callback?code=placeholder&state=${encodeURIComponent(tx.state)}`;
    const response = await callback(asRequest(url, headers));
    assertSafeLocation(response.headers.get("location"), url, "/login?error=not_linked");
  });

  it("callback success redirect does not follow an attacker X-Forwarded-Host", async () => {
    bridge.configured = true;
    const tx = createOidcTransaction({ providerId: "entra", scopeId: 1 });
    const headers = attackerHeaders({ cookie: buildOidcTransactionCookie(tx) });
    headerState.current = headers;
    oidc.exchangeOidcCallback.mockResolvedValueOnce({
      issuer: "https://issuer.example/tenant",
      subject: "subject-placeholder",
      snapshot: "{}",
    });
    bridge.open.mockResolvedValueOnce({
      sessionToken: "placeholder-session-token",
      expiresAtUtc: new Date("2026-01-01T00:00:00.000Z"),
      userId: 1,
    });
    const url = `http://127.0.0.1:3400/api/auth/oidc/entra/callback?code=placeholder&state=${encodeURIComponent(tx.state)}`;
    const response = await callback(asRequest(url, headers));
    assertSafeLocation(response.headers.get("location"), url, "/app");
    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).not.toContain(ATTACKER_HOST);
    const exchangeUrl = oidc.exchangeOidcCallback.mock.calls.at(-1)?.[1] as URL;
    expect(exchangeUrl.origin).not.toBe(`https://${ATTACKER_HOST}`);
    expect([ALLOWED_ORIGIN, new URL(url).origin]).toContain(exchangeUrl.origin);
  });

  it("callback uses the first forwarded host when a later read differs", async () => {
    bridge.configured = false;
    const headers = rereadHeaders();
    headerState.current = headers as Headers;
    const response = await callback(asRequest(REQUEST_URL, headers), "not-a-provider");
    const location = response.headers.get("location");
    expect(new URL(location!).origin).toBe(ALLOWED_ORIGIN);
    expect(new URL(location!).hostname).not.toBe(ATTACKER_HOST);
  });

  it("callback success uses the host from the first read, not a later read", async () => {
    bridge.configured = true;
    const tx = createOidcTransaction({ providerId: "entra", scopeId: 1 });
    const headers = rereadHeaders({ cookie: buildOidcTransactionCookie(tx) });
    headerState.current = headers as Headers;
    oidc.exchangeOidcCallback.mockResolvedValueOnce({
      issuer: "https://issuer.example/tenant",
      subject: "subject-placeholder",
      snapshot: "{}",
    });
    bridge.open.mockResolvedValueOnce({
      sessionToken: "placeholder-session-token",
      expiresAtUtc: new Date("2026-01-01T00:00:00.000Z"),
      userId: 1,
    });
    const url = `http://127.0.0.1:3400/api/auth/oidc/entra/callback?code=placeholder&state=${encodeURIComponent(tx.state)}`;
    const response = await callback(asRequest(url, headers));
    expect(new URL(response.headers.get("location")!).origin).toBe(ALLOWED_ORIGIN);
    const exchangeUrl = oidc.exchangeOidcCallback.mock.calls.at(-1)?.[1] as URL;
    expect(exchangeUrl.hostname).not.toBe(ATTACKER_HOST);
    expect([ALLOWED_ORIGIN, new URL(url).origin]).toContain(exchangeUrl.origin);
  });

  it("callback ignores an attacker host that is only the first of several forwarded hosts", async () => {
    bridge.configured = false;
    const headers = new Headers({
      host: "app.example.com",
      "x-forwarded-host": `${ATTACKER_HOST}, app.example.com`,
      "x-forwarded-proto": "https",
    });
    headerState.current = headers;
    const response = await callback(asRequest(REQUEST_URL, headers), "not-a-provider");
    assertSafeLocation(response.headers.get("location"), REQUEST_URL, "/login?error=provider");
  });

  it("callback ignores a Host header that is not allowlisted when no forwarded host is set", async () => {
    bridge.configured = false;
    const headers = new Headers({ host: ATTACKER_HOST });
    headerState.current = headers;
    const response = await callback(asRequest(REQUEST_URL, headers), "not-a-provider");
    assertSafeLocation(response.headers.get("location"), REQUEST_URL, "/login?error=provider");
  });

  it("callback ignores a forwarded origin whose scheme is not allowlisted", async () => {
    bridge.configured = false;
    const headers = new Headers({
      host: "app.example.com",
      "x-forwarded-host": "app.example.com",
      "x-forwarded-proto": "http",
    });
    headerState.current = headers;
    const response = await callback(asRequest(REQUEST_URL, headers), "not-a-provider");
    assertSafeLocation(response.headers.get("location"), REQUEST_URL, "/login?error=provider");
  });

  it("callback still redirects to an allowlisted forwarded host", async () => {
    bridge.configured = false;
    const headers = new Headers({
      host: "internal.example",
      "x-forwarded-host": "app.example.com",
      "x-forwarded-proto": "https",
    });
    headerState.current = headers;
    const response = await callback(asRequest(REQUEST_URL, headers), "not-a-provider");
    const location = new URL(response.headers.get("location")!);
    expect(location.origin).toBe(ALLOWED_ORIGIN);
    expect(location.pathname + location.search).toBe("/login?error=provider");
  });

  it("login page provider link does not use an attacker X-Forwarded-Host", async () => {
    headerState.current = attackerHeaders();
    const { default: LoginPage } = await import("@/app/(marketing)/login/page");
    const tree = await LoginPage({ searchParams: Promise.resolve({}) });
    const props: Record<string, string>[] = [];
    collectProps(tree, props);
    const hrefs = props.map((p) => p.href).filter(Boolean);
    expect(hrefs.some((href) => href.includes("/api/auth/oidc/entra/start"))).toBe(true);
    for (const href of hrefs) {
      if (href.startsWith("http")) {
        expect(new URL(href).hostname).not.toBe(ATTACKER_HOST);
        expect([ALLOWED_ORIGIN, "http://localhost:3400"]).toContain(new URL(href).origin);
      }
    }
  });

  it("login page link uses the first forwarded host when a later read differs", async () => {
    headerState.current = rereadHeaders() as Headers;
    const { default: LoginPage } = await import("@/app/(marketing)/login/page");
    const tree = await LoginPage({ searchParams: Promise.resolve({}) });
    const props: Record<string, string>[] = [];
    collectProps(tree, props);
    const start = props.map((p) => p.href).find((href) => href?.includes("/api/auth/oidc/entra/start"));
    expect(start).toBeTruthy();
    expect(new URL(start!).origin).toBe(ALLOWED_ORIGIN);
  });

  it("login page keeps an allowlisted forwarded host on the provider link", async () => {
    headerState.current = new Headers({
      host: "internal.example",
      "x-forwarded-host": "app.example.com",
      "x-forwarded-proto": "https",
    });
    const { default: LoginPage } = await import("@/app/(marketing)/login/page");
    const tree = await LoginPage({ searchParams: Promise.resolve({}) });
    const props: Record<string, string>[] = [];
    collectProps(tree, props);
    const start = props.map((p) => p.href).find((href) => href?.includes("/api/auth/oidc/entra/start"));
    expect(new URL(start!).origin).toBe(ALLOWED_ORIGIN);
  });

  it("provider list sign-in URL does not use an attacker X-Forwarded-Host", async () => {
    const { GET } = await import("@/app/api/auth/providers/route");
    const response = await GET(
      new Request("http://127.0.0.1:3400/api/auth/providers", { headers: attackerHeaders() }),
    );
    const body = (await response.json()) as { providers: { signInUrl: string }[] };
    expect(body.providers.length).toBeGreaterThan(0);
    for (const provider of body.providers) {
      const url = new URL(provider.signInUrl);
      expect(url.hostname).not.toBe(ATTACKER_HOST);
      expect([ALLOWED_ORIGIN, "http://127.0.0.1:3400"]).toContain(url.origin);
      expect(url.pathname).toBe("/api/auth/oidc/entra/start");
    }
  });

  it("provider list uses the first forwarded host when a later read differs", async () => {
    const { GET } = await import("@/app/api/auth/providers/route");
    const response = await GET(asRequest("http://127.0.0.1:3400/api/auth/providers", rereadHeaders()));
    const body = (await response.json()) as { providers: { signInUrl: string }[] };
    expect(new URL(body.providers[0]!.signInUrl).origin).toBe(ALLOWED_ORIGIN);
  });

  it("admin users sign-in URL does not use an attacker X-Forwarded-Host", async () => {
    headerState.current = attackerHeaders();
    const { PortalWorkspacePanel } = await import("@/components/PortalWorkspacePanel");
    const tree = await PortalWorkspacePanel({
      spec: {
        kind: "admin_users",
        title: "Users",
        description: "Create users, invitations, and scoped role assignments.",
      },
    });
    const props: Record<string, string>[] = [];
    collectProps(tree, props);
    const signInUrl = props.map((p) => p.signInUrl).find(Boolean);
    expect(signInUrl).toBeTruthy();
    const url = new URL(signInUrl!);
    expect(url.hostname, signInUrl).not.toBe(ATTACKER_HOST);
    expect([ALLOWED_ORIGIN, "http://localhost:3400"]).toContain(url.origin);
    expect(url.pathname).toBe("/login");
  });

  it("admin users sign-in URL uses the first forwarded host when a later read differs", async () => {
    headerState.current = rereadHeaders() as Headers;
    const { PortalWorkspacePanel } = await import("@/components/PortalWorkspacePanel");
    const tree = await PortalWorkspacePanel({
      spec: {
        kind: "admin_users",
        title: "Users",
        description: "Create users, invitations, and scoped role assignments.",
      },
    });
    const props: Record<string, string>[] = [];
    collectProps(tree, props);
    const signInUrl = props.map((p) => p.signInUrl).find(Boolean);
    expect(new URL(signInUrl!).origin).toBe(ALLOWED_ORIGIN);
  });

  it("sign-in start still refuses an attacker X-Forwarded-Host", async () => {
    const { GET } = await import("@/app/api/auth/oidc/[providerId]/start/route");
    const response = await GET(new Request("http://127.0.0.1:3400/api/auth/oidc/entra/start", { headers: attackerHeaders() }), {
      params: Promise.resolve({ providerId: "entra" }),
    });
    expect(response.status).toBe(403);
    expect(response.headers.get("location")).toBeNull();
    const body = await response.json();
    expect(JSON.stringify(body)).not.toContain(ATTACKER_HOST);
  });
});
