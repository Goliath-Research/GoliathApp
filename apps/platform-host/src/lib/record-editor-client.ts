/** Browser helpers for /api/portal/records/:entity. */

export class RecordEditorRequestError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function readJson<T>(res: Response): Promise<T> {
  const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) {
    const message =
      (typeof body.error === "string" && body.error) ||
      (typeof body.message === "string" && body.message) ||
      `Request failed (${res.status})`;
    throw new RecordEditorRequestError(res.status, message);
  }
  return body as T;
}

export function recordsUrl(entity: string, suffix: "" | "/item" | "/action" = "", key?: string): string {
  const base = `/api/portal/records/${encodeURIComponent(entity)}${suffix}`;
  return key != null ? `${base}?key=${encodeURIComponent(key)}` : base;
}

export async function fetchRecordRows(entity: string): Promise<Record<string, unknown>[]> {
  const res = await fetch(recordsUrl(entity), { credentials: "same-origin", cache: "no-store" });
  return (await readJson<{ rows: Record<string, unknown>[] }>(res)).rows ?? [];
}

export async function fetchRecordDocument(entity: string, key: string): Promise<Record<string, unknown>> {
  const res = await fetch(recordsUrl(entity, "/item", key), { credentials: "same-origin", cache: "no-store" });
  return (await readJson<{ document: Record<string, unknown> }>(res)).document ?? {};
}

export async function saveRecordDocument(
  entity: string,
  key: string | null,
  document: Record<string, unknown>,
): Promise<string> {
  const res = await fetch(recordsUrl(entity), {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ key, document }),
  });
  return (await readJson<{ key: string }>(res)).key;
}

export async function runRecordEditorAction(
  entity: string,
  action: string,
  key: string,
  document?: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const res = await fetch(recordsUrl(entity, "/action"), {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action, key, document }),
  });
  return (await readJson<{ result: Record<string, unknown> }>(res)).result ?? {};
}
