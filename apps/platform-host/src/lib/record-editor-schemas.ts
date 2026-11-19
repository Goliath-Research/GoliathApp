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
  /**
   * When set, the record's `document` field is typed by the JSON Schema the server returns in
   * this key of the record document (registered by the app that owns the record kind). Without
   * a schema the document is view-only.
   */
  documentSchemaKey?: string;
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

const JSON_TYPES = ["string", "integer", "number", "boolean"];
const FILTER_OPS = ["eq", "gte", "lte", "starts_with", "is_null"];

export const SEMANTIC_PARAM_SCHEMA: Record<string, unknown> = {
  type: "object",
  properties: {
    name: str("Parameter name"),
    title: str("Label"),
    json_type: { type: "string", enum: JSON_TYPES },
    required: { type: "boolean" },
    nullable: { type: "boolean", description: "Accepts null (optional value)" },
    minimum: { type: "number" },
    maximum: { type: "number" },
    exclusive_minimum: { type: "number" },
  },
  required: ["name", "json_type"],
};

export const SEMANTIC_FILTER_SCHEMA: Record<string, unknown> = {
  type: "object",
  properties: {
    attribute: { type: "string", "x-goliath-ref": "semantic_attribute", description: "Entity attribute" },
    op: { type: "string", enum: FILTER_OPS },
    param: str("Request parameter compared with the attribute (not needed for is_null)"),
  },
  required: ["attribute", "op"],
};

const SEMANTIC_REQUEST_BODY = {
  entity_id: { type: "integer", "x-goliath-ref": "semantic_entity" },
  target_kind: { type: "string", enum: ["function", "template"] },
  target_name: {
    type: "string",
    "x-goliath-ref": "semantic_target_function",
    description: "Function schema.name(integer, jsonb, integer), or a runner template",
  },
  row_type: { type: "string", "x-goliath-ref": "semantic_row_type", description: "Portal row type" },
  required_permission: { type: "string", "x-goliath-ref": "permission" },
  max_rows: { type: "integer", minimum: 1 },
  params: { type: "array", items: SEMANTIC_PARAM_SCHEMA },
  filters: { type: "array", items: SEMANTIC_FILTER_SCHEMA, description: "All must match (template targets only)" },
};

const SEMANTIC_ENTITY_EDIT = {
  display_name: str(),
  description: str(),
  storage_relation: str("schema.relation that stores the rows (template targets)"),
};

const SEMANTIC_ATTRIBUTE_EDIT = {
  column_name: str("Column in the row type / storage relation"),
  json_type: { type: "string", enum: JSON_TYPES },
  role: { type: "string", enum: ["list", "detail", "filter", "key"] },
  filterable_ops: { type: "array", items: { type: "string", enum: FILTER_OPS } },
};

/** Platform namespaces are edited by the God Architect only (enforced in SQL). */
export const SEMANTIC_PLATFORM_NAMESPACES = ["platform", "portal", "core"];

const META_FIELD_EDIT = {
  type_id: { type: "integer", "x-goliath-ref": "data_type", description: "Catalog data type" },
  required: { type: "boolean" },
  description: str(),
};

const META_LINK_EDIT = {
  min_card: { type: "integer", minimum: 0 },
  max_card: { type: "integer", minimum: 0, description: "Empty for unbounded" },
  is_hierarchical: { type: "boolean" },
};


function cfgDocumentEditor(entity: string, title: string, noun: string): RecordEditorDefinition {
  return {
    entity,
    title,
    noun,
    columns: [
      { key: "name", label: "Name" },
      { key: "version", label: "Version" },
      { key: "status", label: "Status" },
      { key: "updated_at_utc", label: "Updated" },
    ],
    createSchema: { type: "object", properties: { name: str("Name (letters, digits, _ . : -)") }, required: ["name"] },
    editSchema: { type: "object", properties: {} },
    rowKey: (row) => String(row.id),
    rowLabel: (row) => `${row.name} v${row.version}`,
    canCreate: true,
    documentSchemaKey: "document_schema",
    canEdit: (row) => row.editable === true || row.editable === "t",
    rowActions: [
      { action: "publish", label: "Publish", visible: (row) => row.status === "draft" },
      {
        action: "retire",
        label: "Retire",
        visible: (row) => row.status === "draft" || row.status === "published",
        confirm: "Retire this version? It is kept but no longer offered.",
      },
    ],
  };
}

/** Classes named platform/* are edited by the God Architect only (enforced in SQL). */
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
        action: "compile_publish",
        label: "Compile and publish",
        visible: (row) => row.status === "draft",
        confirm:
          "Compile this draft on the server and publish it? A new inactive workflow version is created; activate it on Workflow definitions.",
      },
      {
        action: "publish",
        label: "Publish without compiling",
        visible: (row) => row.status === "draft",
      },
    ],
  },
  domain_program_step: {
    entity: "domain_program_step",
    title: "Draft program steps",
    noun: "step",
    columns: [
      { key: "program", label: "Program" },
      { key: "version", label: "Version" },
      { key: "step_path", label: "Step" },
      { key: "action_name", label: "Action" },
      { key: "param_count", label: "Parameters" },
    ],
    createSchema: { type: "object", properties: {} },
    editSchema: { type: "object", properties: {} },
    rowKey: (row) => String(row.step_key),
    rowLabel: (row) => `${row.program} v${row.version} ${row.step_path} (${row.action_name})`,
    canCreate: false,
    documentSchemaKey: "document_schema",
    canEdit: (row) => row.editable === true || row.editable === "t",
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
  semantic_namespace: {
    entity: "semantic_namespace",
    title: "Semantic namespaces",
    noun: "namespace",
    columns: [
      { key: "code", label: "Code" },
      { key: "display_name", label: "Name" },
      { key: "owner_app", label: "Owner app" },
      { key: "entity_count", label: "Entities" },
      { key: "request_count", label: "Requests" },
    ],
    createSchema: {
      type: "object",
      properties: { code: str("Lower case code"), display_name: str(), owner_app: str("Owning application") },
      required: ["code", "display_name"],
    },
    editSchema: {
      type: "object",
      properties: { display_name: str(), owner_app: str("Owning application") },
      required: ["display_name"],
    },
    rowKey: (row) => String(row.code),
    rowLabel: (row) => String(row.code),
    canCreate: true,
    rowActions: [
      {
        action: "delete",
        label: "Delete",
        visible: (row) => Number(row.entity_count) === 0 && Number(row.request_count) === 0,
        confirm: "Delete this empty namespace?",
      },
    ],
  },
  semantic_entity: {
    entity: "semantic_entity",
    title: "Semantic entities",
    noun: "entity",
    columns: [
      { key: "namespace", label: "Namespace" },
      { key: "code", label: "Code" },
      { key: "display_name", label: "Name" },
      { key: "meta_class_name", label: "Meta class" },
      { key: "attribute_count", label: "Attributes" },
      { key: "request_count", label: "Requests" },
    ],
    createSchema: {
      type: "object",
      properties: {
        namespace: { type: "string", "x-goliath-ref": "semantic_namespace" },
        code: str("Lower case code"),
        meta_class_name: { type: "string", "x-goliath-ref": "meta_class", description: "Optional Meta class mapping" },
        ...SEMANTIC_ENTITY_EDIT,
      },
      required: ["namespace", "code", "display_name"],
    },
    editSchema: { type: "object", properties: SEMANTIC_ENTITY_EDIT, required: ["display_name"] },
    rowKey: (row) => String(row.id),
    rowLabel: (row) => `${row.namespace}.${row.code}`,
    canCreate: true,
    rowActions: [
      {
        action: "delete",
        label: "Delete",
        visible: (row) => !row.meta_class_name && Number(row.request_count) === 0,
        confirm: "Delete this entity and its attributes?",
      },
    ],
  },
  semantic_attribute: {
    entity: "semantic_attribute",
    title: "Semantic attributes",
    noun: "attribute",
    columns: [
      { key: "entity", label: "Entity" },
      { key: "code", label: "Code" },
      { key: "column_name", label: "Column" },
      { key: "json_type", label: "Type" },
      { key: "role", label: "Role" },
      { key: "filterable_ops", label: "Operators" },
    ],
    createSchema: {
      type: "object",
      properties: {
        entity_id: { type: "integer", "x-goliath-ref": "semantic_entity" },
        code: str("Lower case code"),
        ...SEMANTIC_ATTRIBUTE_EDIT,
      },
      required: ["entity_id", "code", "column_name", "json_type", "role"],
    },
    editSchema: {
      type: "object",
      properties: SEMANTIC_ATTRIBUTE_EDIT,
      required: ["column_name", "json_type", "role"],
    },
    rowKey: (row) => String(row.id),
    rowLabel: (row) => `${row.entity}.${row.code}`,
    canCreate: true,
    rowActions: [
      { action: "delete", label: "Delete", visible: () => true, confirm: "Delete this attribute?" },
    ],
  },
  semantic_request: {
    entity: "semantic_request",
    title: "Semantic requests",
    noun: "request",
    columns: [
      { key: "request_code", label: "Request" },
      { key: "version", label: "Version" },
      { key: "entity", label: "Entity" },
      { key: "target_kind", label: "Target kind" },
      { key: "target_name", label: "Target" },
      { key: "row_type", label: "Row type" },
      { key: "required_permission", label: "Permission" },
      { key: "status", label: "Status" },
    ],
    createSchema: {
      type: "object",
      properties: {
        request_code: str("namespace.name"),
        version: str("Version (default 1)"),
        namespace: { type: "string", "x-goliath-ref": "semantic_namespace" },
        ...SEMANTIC_REQUEST_BODY,
      },
      required: ["request_code", "namespace", "entity_id", "target_kind", "target_name", "row_type"],
    },
    editSchema: {
      type: "object",
      properties: SEMANTIC_REQUEST_BODY,
      required: ["entity_id", "target_kind", "target_name", "row_type"],
    },
    rowKey: (row) => `${row.request_code}@${row.version}`,
    rowLabel: (row) => `${row.request_code} v${row.version}`,
    canCreate: true,
    rowActions: [
      {
        action: "retire",
        label: "Retire",
        visible: (row) => row.status === "ACTIVE",
        confirm: "Retire this request? It stays registered but no longer runs or lists.",
      },
      { action: "activate", label: "Activate", visible: (row) => row.status === "RETIRED" },
      {
        action: "delete",
        label: "Delete",
        visible: (row) => row.status === "RETIRED",
        confirm: "Delete this retired request?",
      },
    ],
  },
  meta_class: {
    entity: "meta_class",
    title: "Classes",
    noun: "class",
    columns: [
      { key: "class_name", label: "Class" },
      { key: "parent_class_name", label: "Parent" },
      { key: "is_abstract", label: "Abstract" },
      { key: "field_count", label: "Fields" },
      { key: "method_count", label: "Methods" },
      { key: "link_count", label: "Relations" },
      { key: "subclass_count", label: "Subclasses" },
      { key: "object_count", label: "Objects" },
    ],
    createSchema: {
      type: "object",
      properties: {
        class_name: str("namespace/ClassName"),
        parent_class_name: { type: "string", "x-goliath-ref": "meta_class", description: "Parent class" },
        is_abstract: { type: "boolean" },
      },
      required: ["class_name", "parent_class_name"],
    },
    editSchema: { type: "object", properties: { is_abstract: { type: "boolean" } } },
    rowKey: (row) => String(row.class_name),
    rowLabel: (row) => String(row.class_name),
    canCreate: true,
    rowActions: [
      {
        action: "delete",
        label: "Delete",
        visible: (row) =>
          ["field_count", "method_count", "link_count", "subclass_count", "object_count"].every(
            (k) => Number(row[k]) === 0,
          ),
        confirm: "Delete this empty class?",
      },
    ],
  },
  meta_field: {
    entity: "meta_field",
    title: "Fields",
    noun: "field",
    columns: [
      { key: "class_name", label: "Class" },
      { key: "field_name", label: "Field" },
      { key: "type_name", label: "Type" },
      { key: "required", label: "Required" },
      { key: "value_count", label: "Objects with a value" },
    ],
    createSchema: {
      type: "object",
      properties: {
        class_name: { type: "string", "x-goliath-ref": "meta_class" },
        field_name: str("Field name"),
        ...META_FIELD_EDIT,
      },
      required: ["class_name", "field_name", "type_id"],
    },
    editSchema: { type: "object", properties: META_FIELD_EDIT, required: ["type_id"] },
    rowKey: (row) => String(row.field_id),
    rowLabel: (row) => `${row.class_name}.${row.field_name}`,
    canCreate: true,
    rowActions: [
      {
        action: "delete",
        label: "Delete",
        visible: (row) => Number(row.value_count) === 0,
        confirm: "Delete this field? No object holds a value for it.",
      },
    ],
  },
  meta_link: {
    entity: "meta_link",
    title: "Relations",
    noun: "relation",
    columns: [
      { key: "class_name", label: "Class" },
      { key: "link_name", label: "Relation" },
      { key: "target_class_name", label: "Target" },
      { key: "min_card", label: "Min" },
      { key: "max_card", label: "Max" },
      { key: "is_hierarchical", label: "Hierarchical" },
      { key: "instance_count", label: "Instances" },
    ],
    createSchema: {
      type: "object",
      properties: {
        class_name: { type: "string", "x-goliath-ref": "meta_class" },
        link_name: str("Relation name"),
        target_class_name: { type: "string", "x-goliath-ref": "meta_class" },
        ...META_LINK_EDIT,
      },
      required: ["class_name", "link_name", "target_class_name"],
    },
    editSchema: { type: "object", properties: META_LINK_EDIT },
    rowKey: (row) => String(row.link_id),
    rowLabel: (row) => `${row.class_name}.${row.link_name}`,
    canCreate: true,
    rowActions: [
      {
        action: "delete",
        label: "Delete",
        visible: (row) => Number(row.instance_count) === 0,
        confirm: "Delete this relation? No instance uses it.",
      },
    ],
  },
  cfg_site: cfgDocumentEditor("cfg_site", "Sites", "site"),
  cfg_pipeline_profile: cfgDocumentEditor("cfg_pipeline_profile", "Pipeline profiles", "pipeline profile"),
  organization: {
    entity: "organization",
    title: "Organizations",
    noun: "organization",
    columns: [
      { key: "name", label: "Name" },
      { key: "active", label: "Active" },
      { key: "member_count", label: "Members" },
      { key: "created_at_utc", label: "Created" },
    ],
    createSchema: {
      type: "object",
      properties: { name: str("Organization name"), active: { type: "boolean", default: true } },
      required: ["name"],
    },
    editSchema: {
      type: "object",
      properties: { name: str("Organization name"), active: { type: "boolean" } },
      required: ["name"],
    },
    rowKey: (row) => String(row.organization_id),
    rowLabel: (row) => String(row.name),
    canCreate: true,
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

/** Read-only schema for View: every create and edit property (identity fields included). */
/** Add the server-provided document schema as the typed `document` field of an editor schema. */
export function withDocumentSchema(
  base: Record<string, unknown>,
  documentSchema: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  if (!documentSchema || typeof documentSchema !== "object") return base;
  const props = (documentSchema.properties ?? {}) as Record<string, unknown>;
  return {
    ...base,
    properties: {
      ...((base.properties ?? {}) as Record<string, unknown>),
      document: {
        type: "object",
        description: "Document (typed by the registered document type)",
        properties: props,
        ...(Array.isArray(documentSchema.required) ? { required: documentSchema.required } : {}),
      },
    },
  };
}

export function viewSchemaFor(def: RecordEditorDefinition): Record<string, unknown> {
  const createProps = (def.createSchema.properties ?? {}) as Record<string, unknown>;
  const editProps = (def.editSchema.properties ?? {}) as Record<string, unknown>;
  return { type: "object", properties: { ...createProps, ...editProps } };
}
