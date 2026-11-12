/**
 * Property-grid schemas for the workflow graph editor. Graph edits always save a NEW inactive
 * version; node input templates are carried over by node_key on the server and are not edited
 * here, so no field accepts free-form JSON.
 */

export const NODE_TYPES = [
  "ACTION",
  "SEQUENCE",
  "PARALLEL",
  "IF",
  "SWITCH",
  "REPEAT",
  "WHILE",
  "FOREACH",
  "WAIT_EVENT",
  "SCHEDULE",
] as const;

export const BRANCH_KINDS = ["SEQUENCE", "PARALLEL", "THEN", "ELSE", "CASE", "DEFAULT", "BODY"] as const;

const s = (description?: string) => ({ type: "string", ...(description ? { description } : {}) });

export const WORKFLOW_NODE_SCHEMA: Record<string, unknown> = {
  type: "object",
  properties: {
    node_key: s("Unique key within the version"),
    node_type: { type: "string", enum: [...NODE_TYPES] },
    action_name: { type: "string", "x-goliath-ref": "action", description: "Action (ACTION nodes)" },
    repeat_count: { type: "integer", minimum: 0 },
    condition_ref_node_key: s(),
    switch_ref_node_key: s(),
    condition_var: s(),
    switch_var: s(),
    foreach_collection_var: s(),
    foreach_item_var: s(),
    foreach_index_var: s(),
    foreach_parallel: { type: "boolean" },
    wait_event_type: { type: "string", "x-goliath-ref": "event_type" },
    wait_correlation_var: s(),
    schedule_interval_seconds: { type: "integer", minimum: 1 },
  },
  required: ["node_key", "node_type"],
};

export const WORKFLOW_EDGE_SCHEMA: Record<string, unknown> = {
  type: "object",
  properties: {
    parent_node_key: s(),
    child_node_key: s(),
    child_order: { type: "integer", minimum: 0 },
    branch_kind: { type: "string", enum: [...BRANCH_KINDS] },
    condition_expr: s(),
    switch_case_value: { type: "integer" },
    is_default: { type: "boolean" },
  },
  required: ["parent_node_key", "child_node_key"],
};

const NODES_AND_EDGES = {
  root_node_key: s("Root node key"),
  nodes: { type: "array", items: WORKFLOW_NODE_SCHEMA },
  edges: { type: "array", items: WORKFLOW_EDGE_SCHEMA },
};

/** Steps page: the node graph only. */
export const WORKFLOW_STEPS_SCHEMA: Record<string, unknown> = {
  type: "object",
  properties: NODES_AND_EDGES,
};

/** Definitions page: the whole version graph. */
export const WORKFLOW_DEFINITION_SCHEMA: Record<string, unknown> = {
  type: "object",
  properties: {
    description: s(),
    ...NODES_AND_EDGES,
    input_bindings: {
      type: "array",
      items: {
        type: "object",
        properties: {
          node_key: s(),
          target_json_path: s(),
          source_expr: s(),
          is_required: { type: "boolean" },
        },
        required: ["node_key", "target_json_path", "source_expr"],
      },
    },
    output_bindings: {
      type: "array",
      items: {
        type: "object",
        properties: { node_key: s(), var_name: s(), source_kind: s(), source_json_path: s() },
        required: ["node_key", "var_name", "source_kind"],
      },
    },
    scope_defaults: {
      type: "array",
      items: {
        type: "object",
        properties: { node_key: s(), var_name: s(), default_expr: s() },
        required: ["node_key", "var_name", "default_expr"],
      },
    },
    collection_bindings: {
      type: "array",
      items: {
        type: "object",
        properties: {
          bind_order: { type: "integer", minimum: 0 },
          scope_var: s(),
          kind: s(),
          path_var: s(),
          base_var: s(),
          json_path: s(),
        },
        required: ["scope_var", "kind"],
      },
    },
  },
};

export type GraphEditorMode = "definitions" | "steps";

export function graphSchemaFor(mode: GraphEditorMode): Record<string, unknown> {
  return mode === "steps" ? WORKFLOW_STEPS_SCHEMA : WORKFLOW_DEFINITION_SCHEMA;
}

/** Editable document from an exported spec: keys of the mode's schema, input templates removed. */
export function editableGraphDocument(
  mode: GraphEditorMode,
  spec: Record<string, unknown>,
): Record<string, unknown> {
  const props = (graphSchemaFor(mode).properties ?? {}) as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(props)) {
    const value = spec[key];
    if (value === undefined || value === null) continue;
    if (key === "nodes" && Array.isArray(value)) {
      out.nodes = value.map((n) => {
        if (!n || typeof n !== "object") return n;
        const { input_template: _template, ...rest } = n as Record<string, unknown>;
        return rest;
      });
    } else {
      out[key] = value;
    }
  }
  return out;
}

/** Statuses for which a run can still be cancelled. */
export function canCancelRun(status: unknown): boolean {
  return typeof status === "string" && !["COMPLETED", "CANCELLED"].includes(status.toUpperCase());
}

export function canRetryNode(status: unknown): boolean {
  return typeof status === "string" && status.toUpperCase() === "FAILED";
}
