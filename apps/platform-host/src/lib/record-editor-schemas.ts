/**
 * Per-entity JSON Schemas for the Workflows record editors. Every field is edited in the
 * typed property grid: references use `x-goliath-ref` pickers, lists and nested objects use
 * the nested inspector. No field accepts typed or pasted JSON.
 */

export type RecordColumn = { key: string; label: string };

export type RecordEditorDefinition = {
  entity: string;
  title: string;
  /** Singular noun for buttons ("New cluster"). */
  noun: string;
  columns: RecordColumn[];
  /** Schema for creating a record. */
  createSchema: Record<string, unknown>;
  /** Schema for editing an existing record (identity fields omitted). */
  editSchema: Record<string, unknown>;
  rowKey: (row: Record<string, unknown>) => string;
  rowLabel: (row: Record<string, unknown>) => string;
  canCreate: boolean;
  /** When set, only matching rows offer the Edit inspector action. */
  canEdit?: (row: Record<string, unknown>) => boolean;
  /** Extra per-row actions (POST /api/portal/records/:entity/action). */
  rowActions?: {
    action: string;
    label: string;
    visible: (row: Record<string, unknown>) => boolean;
    /** Ask before running (destructive or fleet-affecting actions). */
    confirm?: string;
  }[];
};

/** Enrollment rows carry the enrolled worker (sp_session_list_worker_enrollment_states). */
function hasWorker(row: Record<string, unknown>): boolean {
  const id = Number(row.enrolled_worker_id);
  return row.status === "ENROLLED" && Number.isFinite(id) && id > 0;
}

const str = (description?: string, extra: Record<string, unknown> = {}) => ({
  type: "string",
  ...(description ? { description } : {}),
  ...extra,
});

export const CLASS_METHOD_PARAMETER_SCHEMA: Record<string, unknown> = {
  type: "object",
  properties: {
    name: str("Parameter name"),
    type_id: {
      type: "integer",
      "x-goliath-ref": "data_type",
      description: "Catalog data type",
    },
    required: { type: "boolean" },
  },
  required: ["name", "type_id"],
};

const CLASS_METHOD_ACTION_SCHEMA: Record<string, unknown> = {
  type: "object",
  description: "Engine catalog settings synchronised to wf.workflow_action",
  properties: {
    capability: str("Worker capability"),
    implementation_status: {
      type: "string",
      enum: ["scaffolded", "present", "retired"],
    },
    execution_mode: { type: "string", enum: ["in_process", "cli"] },
    cli_tool: str(),
    in_process_handler: str(),
    max_per_worker: { type: "integer", minimum: 1 },
    exclusive_worker: { type: "boolean" },
    can_pause: { type: "boolean" },
    can_continue: { type: "boolean" },
  },
};

const CLASS_METHOD_BODY: Record<string, unknown> = {
  description: str(),
  impl_kind: { type: "string", enum: ["action", "sql", "python", "abstract"] },
  action_name: {
    type: "string",
    "x-goliath-ref": "action",
    description: "Bound workflow action",
  },
  impl_ref: str("sql / python implementation reference, or a new action name"),
  return_type_id: { type: "integer", "x-goliath-ref": "data_type" },
  is_final: { type: "boolean" },
  parameters: { type: "array", items: CLASS_METHOD_PARAMETER_SCHEMA },
  action: CLASS_METHOD_ACTION_SCHEMA,
};

export const CLASS_METHOD_EDIT_SCHEMA: Record<string, unknown> = {
  type: "object",
  properties: CLASS_METHOD_BODY,
  required: ["impl_kind"],
};

export const CLASS_METHOD_CREATE_SCHEMA: Record<string, unknown> = {
  type: "object",
  properties: {
    class_name: {
      type: "string",
      "x-goliath-ref": "meta_class",
      description: "Owning Meta class",
    },
    method_name: str("Method name"),
    ...CLASS_METHOD_BODY,
  },
  required: ["class_name", "method_name", "impl_kind"],
};

const DOMAIN_PROGRAM_BODY = {
  description: str(),
  program_version: str("Program schema version"),
  project_path: str("Project file path"),
};

const CLUSTER_BODY = {
  name: str("Display name"),
  status: { type: "string", enum: ["ACTIVE", "DISABLED"] },
  shared_storage_uri: str(),
  worker_mount_path: str(),
  allowed_source_cidrs: {
    type: "array",
    items: { type: "string" },
    description: "Allowed worker source CIDRs",
  },
};

const EVENT_SUBSCRIPTION_BODY = {
  event_type: { type: "string", "x-goliath-ref": "event_type" },
  workflow_version_id: { type: "integer", "x-goliath-ref": "workflow_version" },
  mode: {
    type: "string",
    enum: ["start_instance", "signal_wait", "start_or_signal"],
  },
  enabled: { type: "boolean" },
  filter: {
    type: "array",
    description: "Payload equality conditions (all must match)",
    items: {
      type: "object",
      properties: {
        key: str("Top-level payload field"),
        value: str(),
        value_type: { type: "string", enum: ["string", "number", "boolean"] },
      },
      required: ["key", "value"],
    },
  },
};

export const RECORD_EDITORS: Record<string, RecordEditorDefinition> = {
  domain_program: {
    entity: "domain_program",
    title: "Domain programs",
    noun: "program version",
    columns: [
      { key: "name", label: "Name" },
      { key: "version", label: "Version" },
      { key: "status", label: "Status" },
    ],
    createSchema: {
      type: "object",
      properties: {
        name: str("Program name"),
        version: str("Version"),
        ...DOMAIN_PROGRAM_BODY,
      },
      required: ["name", "version"],
    },
    editSchema: { type: "object", properties: DOMAIN_PROGRAM_BODY },
    rowKey: (row) => `${row.name}@${row.version}`,
    rowLabel: (row) => `${row.name} v${row.version}`,
    canCreate: true,
    rowActions: [
      {
        action: "publish",
        label: "Publish",
        visible: (row) => row.status === "draft",
      },
    ],
  },
  cluster: {
    entity: "cluster",
    title: "Clusters",
    noun: "cluster",
    columns: [
      { key: "cluster_key", label: "Key" },
      { key: "name", label: "Name" },
      { key: "status", label: "Status" },
      { key: "worker_count", label: "Workers" },
    ],
    createSchema: {
      type: "object",
      properties: { cluster_key: str("Unique cluster key"), ...CLUSTER_BODY },
      required: ["cluster_key"],
    },
    editSchema: { type: "object", properties: CLUSTER_BODY },
    rowKey: (row) => String(row.cluster_key),
    rowLabel: (row) => String(row.name ?? row.cluster_key),
    canCreate: true,
    rowActions: [
      {
        action: "retire",
        label: "Retire",
        visible: (row) => row.status !== "DISABLED",
        confirm: "Retire this cluster? It is kept and marked DISABLED; workers can no longer enroll in it.",
      },
      {
        action: "delete",
        label: "Delete",
        visible: (row) => Number(row.worker_count ?? 0) === 0 && Number(row.enrollment_count ?? 0) === 0,
        confirm: "Delete this cluster? Only a cluster with no workers or enrollments can be deleted.",
      },
    ],
  },
  worker_enrollment: {
    entity: "worker_enrollment",
    title: "Worker enrollments",
    noun: "enrollment",
    columns: [
      { key: "cluster_key", label: "Cluster" },
      { key: "external_worker_key", label: "Worker key" },
      { key: "public_ip", label: "Public IP" },
      { key: "status", label: "Status" },
      { key: "enrolled_worker_id", label: "Worker" },
      { key: "desired_state", label: "Desired state" },
      { key: "last_seen_at_utc", label: "Last seen" },
    ],
    createSchema: {
      type: "object",
      properties: {
        cluster_key: { type: "string", "x-goliath-ref": "cluster" },
        external_worker_key: str("Worker key"),
        public_ip: str("Worker public IP"),
      },
      required: ["cluster_key", "external_worker_key", "public_ip"],
    },
    editSchema: {
      type: "object",
      properties: { public_ip: str("Worker public IP") },
      required: ["public_ip"],
    },
    rowKey: (row) => `${row.cluster_key}/${row.external_worker_key}`,
    rowLabel: (row) => `${row.cluster_key}/${row.external_worker_key}`,
    canCreate: true,
    canEdit: (row) => row.status !== "REVOKED",
    rowActions: [
      {
        action: "drain_worker",
        label: "Drain",
        visible: (row) => hasWorker(row) && row.desired_state !== "DRAINING",
        confirm: "Drain this worker? It finishes its current task and claims no new work.",
      },
      {
        action: "stop_worker",
        label: "Stop",
        visible: (row) => hasWorker(row) && row.desired_state !== "STOPPING",
        confirm: "Stop this worker? Stoppable tasks are cancelled; the worker then stops claiming work.",
      },
      {
        action: "activate_worker",
        label: "Activate",
        visible: (row) => hasWorker(row) && row.desired_state != null && row.desired_state !== "ACTIVE",
      },
      {
        action: "revoke",
        label: "Revoke",
        visible: (row) => row.status !== "REVOKED",
        confirm: "Revoke this enrollment? The worker can no longer open sessions with it.",
      },
      {
        action: "delete",
        label: "Delete",
        visible: (row) => row.status !== "ENROLLED",
        confirm: "Delete this enrollment record?",
      },
    ],
  },
  event_subscription: {
    entity: "event_subscription",
    title: "Event subscriptions",
    noun: "subscription",
    columns: [
      { key: "subscription_id", label: "ID" },
      { key: "event_type_name", label: "Event type" },
      { key: "workflow_def_name", label: "Workflow" },
      { key: "mode", label: "Mode" },
      { key: "enabled", label: "Enabled" },
    ],
    createSchema: {
      type: "object",
      properties: EVENT_SUBSCRIPTION_BODY,
      required: ["event_type", "workflow_version_id", "mode"],
    },
    editSchema: {
      type: "object",
      properties: EVENT_SUBSCRIPTION_BODY,
      required: ["event_type", "workflow_version_id", "mode"],
    },
    rowKey: (row) => String(row.subscription_id),
    rowLabel: (row) => `#${row.subscription_id} ${row.event_type_name}`,
    canCreate: true,
    rowActions: [
      {
        action: "retire",
        label: "Retire",
        visible: (row) => row.enabled === true,
        confirm: "Retire this subscription? It is kept but events no longer start or signal runs.",
      },
      {
        action: "delete",
        label: "Delete",
        visible: () => true,
        confirm: "Delete this subscription? Recorded events are kept.",
      },
    ],
  },
};

/** Fields the server needs from the identity of an existing record when saving. */
export function mergeIdentityForSave(
  entity: string,
  key: string | null,
  original: Record<string, unknown> | null,
  edited: Record<string, unknown>,
): Record<string, unknown> {
  if (!key || !original) return edited;
  switch (entity) {
    case "domain_program":
      return { ...edited, name: original.name, version: original.version };
    case "cluster":
      return { ...edited, cluster_key: original.cluster_key };
    case "worker_enrollment":
      return {
        ...edited,
        cluster_key: original.cluster_key,
        external_worker_key: original.external_worker_key,
      };
    default:
      return edited;
  }
}

/** Remove keys the grid does not edit (server-computed or read-only). */
export function editableDocument(
  schema: Record<string, unknown>,
  document: Record<string, unknown>,
): Record<string, unknown> {
  const props = (schema.properties ?? {}) as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(document)) {
    if (k in props && v !== null && v !== undefined) out[k] = v;
  }
  return out;
}
