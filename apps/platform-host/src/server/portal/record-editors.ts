import "server-only";

import { portalSessionCall } from "./bridge";

/**
 * Server-side registry of Workflows record editors. Each entity maps fixed SQL to the
 * session-gated portal functions in `portal_session_record_editors_api.sql`.
 * Client input only ever reaches SQL as bound parameters.
 */

export const RECORD_EDITOR_ENTITIES = [
  "class_method",
  "domain_program",
  "cluster",
  "worker_enrollment",
  "event_subscription",
] as const;

export type RecordEditorEntity = (typeof RECORD_EDITOR_ENTITIES)[number];

export function isRecordEditorEntity(value: string): value is RecordEditorEntity {
  return (RECORD_EDITOR_ENTITIES as readonly string[]).includes(value);
}

export class RecordEditorInputError extends Error {}

function splitNameVersion(key: string): { name: string; version: string } {
  const at = key.lastIndexOf("@");
  if (at <= 0 || at === key.length - 1) {
    throw new RecordEditorInputError("key must be name@version");
  }
  return { name: key.slice(0, at), version: key.slice(at + 1) };
}

function intKey(key: string | null | undefined, label: string): number {
  const n = Number.parseInt(String(key ?? ""), 10);
  if (!Number.isFinite(n) || n <= 0) {
    throw new RecordEditorInputError(`${label} must be a positive integer`);
  }
  return n;
}

function asObject(value: unknown): Record<string, unknown> {
  if (value == null || typeof value !== "object" || Array.isArray(value)) {
    throw new RecordEditorInputError("document must be an object");
  }
  return value as Record<string, unknown>;
}

async function jsonbScalar(token: string, sql: string, params: unknown[]): Promise<Record<string, unknown>> {
  const rows = await portalSessionCall(token, sql, params);
  const first = rows[0];
  const value = first ? Object.values(first)[0] : null;
  return (value ?? {}) as Record<string, unknown>;
}

export async function listRecords(token: string, entity: RecordEditorEntity): Promise<Record<string, unknown>[]> {
  switch (entity) {
    case "class_method":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_list_class_methods($1)");
    case "domain_program":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_list_domain_programs($1, false)");
    case "cluster":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_list_clusters($1)");
    case "worker_enrollment":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_list_worker_enrollments($1, NULL)");
    case "event_subscription":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_list_event_subscriptions($1)");
  }
}

export async function getRecord(
  token: string,
  entity: RecordEditorEntity,
  key: string,
): Promise<Record<string, unknown>> {
  switch (entity) {
    case "class_method":
      return jsonbScalar(token, "SELECT portal.sp_session_get_class_method($1, $2::int) AS doc", [
        intKey(key, "method id"),
      ]);
    case "domain_program": {
      const { name, version } = splitNameVersion(key);
      return jsonbScalar(token, "SELECT portal.sp_session_get_domain_program($1, $2, $3) AS doc", [name, version]);
    }
    case "cluster":
      return jsonbScalar(token, "SELECT portal.sp_session_get_cluster($1, $2) AS doc", [key]);
    case "event_subscription":
      return jsonbScalar(token, "SELECT portal.sp_session_get_event_subscription($1, $2::bigint) AS doc", [
        intKey(key, "subscription id"),
      ]);
    case "worker_enrollment": {
      const rows = await listRecords(token, "worker_enrollment");
      const row = rows.find((r) => `${r.cluster_key}/${r.external_worker_key}` === key);
      if (!row) throw new RecordEditorInputError("enrollment not found");
      return {
        cluster_key: row.cluster_key,
        public_ip: row.public_ip,
        external_worker_key: row.external_worker_key,
      };
    }
  }
}

export async function saveRecord(
  token: string,
  entity: RecordEditorEntity,
  key: string | null,
  document: unknown,
): Promise<{ key: string }> {
  const doc = asObject(document);
  const json = JSON.stringify(doc);
  switch (entity) {
    case "class_method": {
      const methodId = key ? intKey(key, "method id") : null;
      const rows = await portalSessionCall(
        token,
        "SELECT portal.sp_session_save_class_method($1, $2::int, $3::jsonb) AS id",
        [methodId, json],
      );
      return { key: String(rows[0]?.id ?? "") };
    }
    case "domain_program": {
      const rows = await portalSessionCall(
        token,
        "SELECT * FROM portal.sp_session_save_domain_program($1, $2::jsonb)",
        [json],
      );
      return { key: `${rows[0]?.name}@${rows[0]?.version}` };
    }
    case "cluster": {
      const rows = await portalSessionCall(token, "SELECT portal.sp_session_save_cluster($1, $2::jsonb) AS k", [json]);
      return { key: String(rows[0]?.k ?? "") };
    }
    case "worker_enrollment": {
      await portalSessionCall(token, "SELECT portal.sp_session_save_worker_enrollment($1, $2::jsonb) AS id", [json]);
      return { key: `${doc.cluster_key}/${doc.external_worker_key}` };
    }
    case "event_subscription": {
      const id = key ? intKey(key, "subscription id") : null;
      const rows = await portalSessionCall(
        token,
        "SELECT portal.sp_session_save_event_subscription($1, $2::bigint, $3::jsonb) AS id",
        [id, json],
      );
      return { key: String(rows[0]?.id ?? "") };
    }
  }
}

export type RecordEditorAction = "publish" | "revoke" | "defaults";

export async function runRecordAction(
  token: string,
  entity: RecordEditorEntity,
  action: string,
  key: string,
  document?: unknown,
): Promise<Record<string, unknown>> {
  if (entity === "domain_program" && action === "publish") {
    const { name, version } = splitNameVersion(key);
    const rows = await portalSessionCall(
      token,
      "SELECT * FROM portal.sp_session_publish_domain_program($1, $2, $3)",
      [name, version],
    );
    return rows[0] ?? {};
  }
  if (entity === "worker_enrollment" && action === "revoke") {
    const slash = key.indexOf("/");
    if (slash <= 0) throw new RecordEditorInputError("key must be cluster_key/external_worker_key");
    const rows = await portalSessionCall(
      token,
      "SELECT portal.sp_session_revoke_worker_enrollment($1, $2, $3) AS status",
      [key.slice(0, slash), key.slice(slash + 1)],
    );
    return rows[0] ?? {};
  }
  if (entity === "class_method" && action === "defaults") {
    const rows = await portalSessionCall(
      token,
      "SELECT portal.sp_session_save_method_param_defaults($1, $2::int, $3::jsonb) AS updated",
      [intKey(key, "method id"), JSON.stringify(asObject(document ?? {}))],
    );
    return rows[0] ?? {};
  }
  throw new RecordEditorInputError(`unsupported action ${action} for ${entity}`);
}
