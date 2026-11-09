import type {
  MetaClassField,
  MetaClassLineageNode,
  MetaClassSummary,
  MetaDataTypeSummary,
  MetaObjectDocument,
} from "./meta.js";
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

    async getMetaClass(className: string): Promise<MetaClassSummary> {
      const res = await fetchFn(`${base}/api/meta/classes/${encodeURIComponent(className)}`, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const body = await readJson<{ class: MetaClassSummary }>(res);
      return body.class;
    },

    async getMetaClassLineage(className: string): Promise<MetaClassLineageNode[]> {
      const res = await fetchFn(
        `${base}/api/meta/classes/${encodeURIComponent(className)}/lineage`,
        {
          method: "GET",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        },
      );
      const body = await readJson<{ lineage: MetaClassLineageNode[] }>(res);
      return body.lineage;
    },

    async getMetaDataType(typeName: string, version?: string): Promise<MetaDataTypeSummary> {
      const qs = version ? `?version=${encodeURIComponent(version)}` : "";
      const res = await fetchFn(`${base}/api/meta/types/${encodeURIComponent(typeName)}${qs}`, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const body = await readJson<{ type: MetaDataTypeSummary }>(res);
      return body.type;
    },

    async getMetaClassFields(className: string): Promise<MetaClassField[]> {
      const res = await fetchFn(
        `${base}/api/meta/classes/${encodeURIComponent(className)}/fields`,
        {
          method: "GET",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        },
      );
      const body = await readJson<{ fields: MetaClassField[] }>(res);
      return body.fields;
    },

    async createMetaObject(
      className: string,
      document: Record<string, unknown>,
    ): Promise<{ objId: number }> {
      const res = await fetchFn(
        `${base}/api/meta/classes/${encodeURIComponent(className)}/objects`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: { Accept: "application/json", "Content-Type": "application/json" },
          body: JSON.stringify({ document }),
        },
      );
      return readJson<{ objId: number }>(res);
    },

    async getMetaObject(objId: number): Promise<MetaObjectDocument> {
      const res = await fetchFn(`${base}/api/meta/objects/${objId}`, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const body = await readJson<{ object: MetaObjectDocument }>(res);
      return body.object;
    },

    async updateMetaObject(objId: number, document: Record<string, unknown>): Promise<void> {
      const res = await fetchFn(`${base}/api/meta/objects/${objId}`, {
        method: "PATCH",
        credentials: "same-origin",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ document }),
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
        nodePath: row.nodePath == null ? null : String(row.nodePath),
      }));
    },
  };
}

export type PlatformBffClient = ReturnType<typeof createPlatformBffClient>;
