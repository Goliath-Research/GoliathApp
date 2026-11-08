import type { OperatorNavNode } from "./nav.js";
import { coercePresentationKind } from "./nav.js";
import type { PlatformSessionSnapshot } from "./session.js";
import { SessionTransportError } from "./session.js";

export type PlatformBffClientOptions = {
  /** Same-origin base (default: relative). */
  baseUrl?: string;
  fetchFn?: typeof fetch;
};

function statusToCode(status: number): SessionTransportError["code"] {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 503) return "misconfigured";
  return "upstream";
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { error?: string };
      if (body.error) detail = body.error;
    } catch {
      // ignore
    }
    throw new SessionTransportError(statusToCode(res.status), detail, res.status);
  }
  return (await res.json()) as T;
}

/**
 * Browser-side client: calls only same-origin platform host routes.
 * Session tokens never appear in JS — the host stores them in httpOnly cookies.
 */
export function createPlatformBffClient(options: PlatformBffClientOptions = {}) {
  const base = options.baseUrl?.replace(/\/$/, "") ?? "";
  const fetchFn = options.fetchFn ?? fetch;

  return {
    async getSession(): Promise<PlatformSessionSnapshot | null> {
      const res = await fetchFn(`${base}/api/session/me`, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (res.status === 401) return null;
      return readJson<PlatformSessionSnapshot>(res);
    },

    async logout(): Promise<void> {
      const res = await fetchFn(`${base}/api/session/logout`, {
        method: "POST",
        credentials: "same-origin",
      });
      await readJson<{ ok: boolean }>(res);
    },

    async getOperatorNavigation(): Promise<OperatorNavNode[]> {
      const res = await fetchFn(`${base}/api/navigation`, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const body = await readJson<{ nodes: Array<Record<string, unknown>> }>(res);
      return body.nodes.map((row) => ({
        nodeId: Number(row.nodeId),
        parentId: row.parentId == null ? null : Number(row.parentId),
        caption: String(row.caption),
        seq: Number(row.seq),
        presentationKind: coercePresentationKind(String(row.presentationKind)),
      }));
    },
  };
}

export type PlatformBffClient = ReturnType<typeof createPlatformBffClient>;
