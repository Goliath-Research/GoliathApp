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
  "workflow_version",
  "workflow_run",
  "semantic_namespace",
  "semantic_entity",
  "semantic_attribute",
  "semantic_request",
  "meta_class",
  "meta_field",
  "meta_link",
  "cfg_site",
  "cfg_pipeline_profile",
  "organization",
] as const;

const CFG_KIND: Record<string, string> = { cfg_site: "site", cfg_pipeline_profile: "pipeline_profile" };

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
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_list_clusters_with_usage($1)");
    case "worker_enrollment":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_list_worker_enrollment_states($1)");
    case "event_subscription":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_list_event_subscriptions($1)");
    case "workflow_version":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_list_graph_versions($1)");
    case "workflow_run":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_list_recent_instances($1, NULL, 200)");
    case "semantic_namespace":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_semantic_list_namespaces_editor($1)");
    case "semantic_entity":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_semantic_list_entities_editor($1)");
    case "semantic_attribute":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_semantic_list_attributes_editor($1)");
    case "semantic_request":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_semantic_list_requests_editor($1)");
    case "meta_class":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_meta_editor_list_classes($1)");
    case "meta_field":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_meta_editor_list_fields($1)");
    case "meta_link":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_meta_editor_list_links($1)");
    case "cfg_site":
    case "cfg_pipeline_profile":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_cfg_document_list($1, $2)", [CFG_KIND[entity]]);
    case "organization":
      return portalSessionCall(token, "SELECT * FROM portal.sp_session_org_list($1)");
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
    case "workflow_version":
      return jsonbScalar(token, "SELECT portal.sp_session_get_workflow_version_spec($1, $2::bigint) AS doc", [
        intKey(key, "workflow version id"),
      ]);
    case "workflow_run":
      return jsonbScalar(token, "SELECT portal.sp_session_get_run($1, $2::bigint) AS doc", [
        intKey(key, "workflow run id"),
      ]);
    case "semantic_namespace":
      return jsonbScalar(token, "SELECT portal.sp_session_semantic_get_namespace($1, $2) AS doc", [key]);
    case "semantic_entity":
      return jsonbScalar(token, "SELECT portal.sp_session_semantic_get_entity($1, $2::int) AS doc", [
        intKey(key, "entity id"),
      ]);
    case "semantic_attribute":
      return jsonbScalar(token, "SELECT portal.sp_session_semantic_get_attribute($1, $2::int) AS doc", [
        intKey(key, "attribute id"),
      ]);
    case "semantic_request": {
      const { name, version } = splitNameVersion(key);
      return jsonbScalar(token, "SELECT portal.sp_session_semantic_get_request($1, $2, $3) AS doc", [name, version]);
    }
    case "meta_class":
      return jsonbScalar(token, "SELECT portal.sp_session_meta_editor_get_class($1, $2) AS doc", [key]);
    case "meta_field":
      return jsonbScalar(token, "SELECT portal.sp_session_meta_editor_get_field($1, $2::int) AS doc", [
        intKey(key, "field id"),
      ]);
    case "meta_link":
      return jsonbScalar(token, "SELECT portal.sp_session_meta_editor_get_link($1, $2::int) AS doc", [
        intKey(key, "relation id"),
      ]);
    case "cfg_site":
    case "cfg_pipeline_profile":
      if (key === "new") {
        return jsonbScalar(token, "SELECT portal.sp_session_cfg_document_type($1, $2) AS doc", [CFG_KIND[entity]]);
      }
      return jsonbScalar(token, "SELECT portal.sp_session_cfg_document_get($1, $2, $3::bigint) AS doc", [
        CFG_KIND[entity],
        intKey(key, "document id"),
      ]);
    case "organization": {
      const rows = await listRecords(token, "organization");
      const row = rows.find((r) => String(r.organization_id) === key);
      if (!row) throw new RecordEditorInputError("organization not found");
      return { organization_id: row.organization_id, name: row.name, active: row.active };
    }
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
    case "workflow_version": {
      if (!key) {
        // New workflow: definition + inactive version 1.0 with a single root node.
        const created = await portalSessionCall(
          token,
          "SELECT * FROM portal.sp_session_create_workflow($1, $2::jsonb)",
          [json],
        );
        return { key: String(created[0]?.workflow_version_id ?? "") };
      }
      // Never edits in place: the key is the base version; the result is a new inactive version.
      const rows = await portalSessionCall(
        token,
        "SELECT * FROM portal.sp_session_save_workflow_version($1, $2::bigint, $3::jsonb)",
        [intKey(key, "base workflow version id"), json],
      );
      return { key: String(rows[0]?.workflow_version_id ?? "") };
    }
    case "workflow_run":
      throw new RecordEditorInputError("workflow runs are not edited; use cancel, retry or link_study");
    case "cfg_site":
    case "cfg_pipeline_profile": {
      const id = key ? intKey(key, "document id") : null;
      const rows = await portalSessionCall(
        token,
        "SELECT portal.sp_session_cfg_document_save($1, $2, $3::bigint, $4::jsonb) AS id",
        [CFG_KIND[entity], id, json],
      );
      return { key: String(rows[0]?.id ?? "") };
    }
    case "organization": {
      const id = key ? intKey(key, "organization id") : null;
      const rows = await portalSessionCall(token, "SELECT portal.sp_session_org_save($1, $2::int, $3::jsonb) AS id", [
        id,
        json,
      ]);
      return { key: String(rows[0]?.id ?? "") };
    }
    case "semantic_namespace": {
      const rows = await portalSessionCall(
        token,
        "SELECT portal.sp_session_semantic_save_namespace($1, $2, $3::jsonb) AS k",
        [key || null, json],
      );
      return { key: String(rows[0]?.k ?? "") };
    }
    case "semantic_entity": {
      const rows = await portalSessionCall(
        token,
        "SELECT portal.sp_session_semantic_save_entity($1, $2::int, $3::jsonb) AS id",
        [key ? intKey(key, "entity id") : null, json],
      );
      return { key: String(rows[0]?.id ?? "") };
    }
    case "semantic_attribute": {
      const rows = await portalSessionCall(
        token,
        "SELECT portal.sp_session_semantic_save_attribute($1, $2::int, $3::jsonb) AS id",
        [key ? intKey(key, "attribute id") : null, json],
      );
      return { key: String(rows[0]?.id ?? "") };
    }
    case "semantic_request": {
      const ident = key ? splitNameVersion(key) : null;
      const rows = await portalSessionCall(
        token,
        "SELECT * FROM portal.sp_session_semantic_save_request($1, $2, $3, $4::jsonb)",
        [ident?.name ?? null, ident?.version ?? null, json],
      );
      return { key: `${rows[0]?.request_code}@${rows[0]?.version}` };
    }
    case "meta_class": {
      const rows = await portalSessionCall(
        token,
        "SELECT portal.sp_session_meta_editor_save_class($1, $2, $3::jsonb) AS k",
        [key || null, json],
      );
      return { key: String(rows[0]?.k ?? "") };
    }
    case "meta_field":
    case "meta_link": {
      const fn = entity === "meta_field" ? "sp_session_meta_editor_save_field" : "sp_session_meta_editor_save_link";
      const rows = await portalSessionCall(token, `SELECT portal.${fn}($1, $2::int, $3::jsonb) AS id`, [
        key ? intKey(key, "id") : null,
        json,
      ]);
      return { key: String(rows[0]?.id ?? "") };
    }
  }
}

export type RecordEditorAction = "publish" | "revoke" | "defaults";

/** Enrollment row actions that set the enrolled worker's desired_state. */
const WORKER_DESIRED_STATE_ACTIONS: Record<string, "ACTIVE" | "DRAINING" | "STOPPING"> = {
  activate_worker: "ACTIVE",
  drain_worker: "DRAINING",
  stop_worker: "STOPPING",
};

function splitEnrollmentKey(key: string): { clusterKey: string; workerKey: string } {
  const slash = key.indexOf("/");
  if (slash <= 0 || slash === key.length - 1) {
    throw new RecordEditorInputError("key must be cluster_key/external_worker_key");
  }
  return { clusterKey: key.slice(0, slash), workerKey: key.slice(slash + 1) };
}

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
    const { clusterKey, workerKey } = splitEnrollmentKey(key);
    const rows = await portalSessionCall(
      token,
      "SELECT portal.sp_session_revoke_worker_enrollment($1, $2, $3) AS status",
      [clusterKey, workerKey],
    );
    return rows[0] ?? {};
  }
  if (entity === "worker_enrollment" && action === "delete") {
    const { clusterKey, workerKey } = splitEnrollmentKey(key);
    const rows = await portalSessionCall(
      token,
      "SELECT portal.sp_session_delete_worker_enrollment($1, $2, $3) AS status",
      [clusterKey, workerKey],
    );
    return rows[0] ?? {};
  }
  if (entity === "worker_enrollment" && action in WORKER_DESIRED_STATE_ACTIONS) {
    splitEnrollmentKey(key);
    const rows = await listRecords(token, "worker_enrollment");
    const row = rows.find((r) => `${r.cluster_key}/${r.external_worker_key}` === key);
    if (!row) throw new RecordEditorInputError("enrollment not found");
    if (row.status !== "ENROLLED") {
      throw new RecordEditorInputError("only an enrolled worker's desired state can be changed");
    }
    const workerId = Number(row.enrolled_worker_id);
    if (!Number.isFinite(workerId) || workerId <= 0) {
      throw new RecordEditorInputError("this enrollment has no enrolled worker yet");
    }
    const result = await portalSessionCall(
      token,
      "SELECT portal.sp_session_set_worker_desired_state($1, $2::bigint, $3) AS desired_state",
      [workerId, WORKER_DESIRED_STATE_ACTIONS[action]],
    );
    return result[0] ?? {};
  }
  if (entity === "cluster" && (action === "retire" || action === "delete")) {
    const fn = action === "retire" ? "sp_session_retire_cluster" : "sp_session_delete_cluster";
    const rows = await portalSessionCall(token, `SELECT portal.${fn}($1, $2) AS result`, [key]);
    return rows[0] ?? {};
  }
  if (entity === "event_subscription" && (action === "retire" || action === "delete")) {
    const fn =
      action === "retire" ? "sp_session_retire_event_subscription" : "sp_session_delete_event_subscription";
    const rows = await portalSessionCall(token, `SELECT portal.${fn}($1, $2::bigint) AS result`, [
      intKey(key, "subscription id"),
    ]);
    return rows[0] ?? {};
  }
  if (entity === "meta_class" && action === "delete") {
    const rows = await portalSessionCall(token, "SELECT portal.sp_session_meta_editor_delete_class($1, $2) AS result", [
      key,
    ]);
    return rows[0] ?? {};
  }
  if ((entity === "meta_field" || entity === "meta_link") && action === "delete") {
    const fn = entity === "meta_field" ? "sp_session_meta_editor_delete_field" : "sp_session_meta_editor_delete_link";
    const rows = await portalSessionCall(token, `SELECT portal.${fn}($1, $2::int) AS result`, [intKey(key, "id")]);
    return rows[0] ?? {};
  }
  if (entity === "semantic_namespace" && action === "delete") {
    const rows = await portalSessionCall(token, "SELECT portal.sp_session_semantic_delete_namespace($1, $2) AS result", [
      key,
    ]);
    return rows[0] ?? {};
  }
  if ((entity === "semantic_entity" || entity === "semantic_attribute") && action === "delete") {
    const fn = entity === "semantic_entity" ? "sp_session_semantic_delete_entity" : "sp_session_semantic_delete_attribute";
    const rows = await portalSessionCall(token, `SELECT portal.${fn}($1, $2::int) AS result`, [intKey(key, "id")]);
    return rows[0] ?? {};
  }
  if (entity === "semantic_request" && (action === "retire" || action === "activate")) {
    const { name, version } = splitNameVersion(key);
    const rows = await portalSessionCall(
      token,
      "SELECT portal.sp_session_semantic_set_request_status($1, $2, $3, $4) AS status",
      [name, version, action === "retire" ? "RETIRED" : "ACTIVE"],
    );
    return rows[0] ?? {};
  }
  if (entity === "semantic_request" && action === "delete") {
    const { name, version } = splitNameVersion(key);
    const rows = await portalSessionCall(
      token,
      "SELECT portal.sp_session_semantic_delete_request($1, $2, $3) AS result",
      [name, version],
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
  if (entity === "workflow_version" && action === "activate") {
    const rows = await portalSessionCall(
      token,
      "SELECT * FROM portal.sp_session_activate_workflow_version($1, $2::bigint)",
      [intKey(key, "workflow version id")],
    );
    return rows[0] ?? {};
  }
  if (entity === "workflow_run" && action === "cancel") {
    const doc = document == null ? {} : asObject(document);
    const reason = typeof doc.reason === "string" && doc.reason.trim() ? doc.reason.trim() : null;
    const rows = await portalSessionCall(
      token,
      "SELECT * FROM portal.sp_session_cancel_run($1, $2::bigint, $3)",
      [intKey(key, "workflow run id"), reason],
    );
    return rows[0] ?? {};
  }
  if (entity === "workflow_run" && action === "retry") {
    const rows = await portalSessionCall(
      token,
      "SELECT * FROM portal.sp_session_retry_run_node($1, $2::bigint)",
      [intKey(key, "node execution id")],
    );
    return rows[0] ?? {};
  }
  if (entity === "workflow_run" && action === "link_study") {
    const doc = asObject(document ?? {});
    const rows = await portalSessionCall(
      token,
      "SELECT portal.sp_session_link_run_study($1, $2::bigint, $3::bigint) AS id",
      [intKey(key, "workflow run id"), intKey(String(doc.study_row_id ?? ""), "study_row_id")],
    );
    return rows[0] ?? {};
  }
  if ((entity === "cfg_site" || entity === "cfg_pipeline_profile") && (action === "publish" || action === "retire")) {
    const rows = await portalSessionCall(
      token,
      "SELECT portal.sp_session_cfg_document_action($1, $2, $3::bigint, $4) AS status",
      [CFG_KIND[entity], intKey(key, "document id"), action],
    );
    return rows[0] ?? {};
  }
  throw new RecordEditorInputError(`unsupported action ${action} for ${entity}`);
}
