import type { ReferenceOption, ReferenceResolver } from "@goliath/platform-ui";

/** Reference kinds the platform host resolves (`x-goliath-ref`). Descendants may add more server-side. */
export const PLATFORM_REFERENCE_KINDS = [
  "action",
  "meta_method",
  "workflow_def",
  "workflow_version",
  "event_type",
  "cluster",
  "worker",
  "data_type",
  "meta_class",
  "study",
] as const;

export function referenceSearchUrl(kind: string, query: string, limit = 50): string {
  const params = new URLSearchParams({ kind, q: query, limit: String(limit) });
  return `/api/portal/references?${params.toString()}`;
}

/** Browser resolver backed by GET /api/portal/references (session cookie, server-side SQL). */
export function createHostReferenceResolver(fetchImpl: typeof fetch = fetch): ReferenceResolver {
  return {
    async search(kind, query, options) {
      const res = await fetchImpl(referenceSearchUrl(kind, query, options?.limit ?? 50), {
        credentials: "same-origin",
        headers: { accept: "application/json" },
      });
      if (!res.ok) {
        let message = `reference search failed (${res.status})`;
        try {
          const body = (await res.json()) as { error?: string };
          if (body?.error) message = body.error;
        } catch {
          /* keep default */
        }
        throw new Error(message);
      }
      const body = (await res.json()) as { rows?: ReferenceOption[] };
      return Array.isArray(body.rows) ? body.rows : [];
    },
  };
}
