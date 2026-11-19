/**
 * Pure edits of a workflow graph draft (the designer canvas). The draft uses the editable spec
 * shape (nodes / edges / bindings keyed by node_key); saving still creates a new inactive version.
 */

type Doc = Record<string, unknown>;
type Row = Record<string, unknown>;

function list(doc: Doc, key: string): Row[] {
  const value = doc[key];
  return Array.isArray(value) ? (value.filter((v) => v && typeof v === "object") as Row[]) : [];
}

const NODE_SCOPED = ["input_bindings", "output_bindings", "scope_defaults"] as const;

export function nodeKeys(doc: Doc): string[] {
  return list(doc, "nodes").map((n) => String(n.node_key ?? ""));
}

export function findNode(doc: Doc, key: string): Row | undefined {
  return list(doc, "nodes").find((n) => n.node_key === key);
}

/** A node key not used yet: `<type>_<n>`. */
export function nextNodeKey(doc: Doc, nodeType: string): string {
  const used = new Set(nodeKeys(doc));
  const base = nodeType.toLowerCase();
  for (let i = 1; ; i++) {
    const key = `${base}_${i}`;
    if (!used.has(key)) return key;
  }
}

/** Add a node; when `parentKey` is given it is connected as that node's last child. */
export function addNode(
  doc: Doc,
  node: { node_type: string; action_name?: string | null },
  parentKey?: string | null,
): { doc: Doc; key: string } {
  const key = nextNodeKey(doc, node.node_type);
  const newNode: Row = { node_key: key, node_type: node.node_type };
  if (node.node_type === "ACTION" && node.action_name) newNode.action_name = node.action_name;
  let next: Doc = { ...doc, nodes: [...list(doc, "nodes"), newNode] };
  if (parentKey && findNode(doc, parentKey)) next = connect(next, parentKey, key);
  if (!next.root_node_key) next = { ...next, root_node_key: key };
  return { doc: next, key };
}

/** Connect parent → child (no duplicates, no self-loops), appended after the parent's other children. */
export function connect(doc: Doc, parentKey: string, childKey: string): Doc {
  if (!parentKey || !childKey || parentKey === childKey) return doc;
  const edges = list(doc, "edges");
  if (edges.some((e) => e.parent_node_key === parentKey && e.child_node_key === childKey)) return doc;
  const order = edges.filter((e) => e.parent_node_key === parentKey).length;
  return {
    ...doc,
    edges: [...edges, { parent_node_key: parentKey, child_node_key: childKey, child_order: order, branch_kind: "SEQUENCE" }],
  };
}

/** Remove edges by their canvas index (edge ids are `e<index>:<source>-><target>`). */
export function removeEdges(doc: Doc, edgeIds: string[]): Doc {
  const drop = new Set(
    edgeIds.map((id) => Number(/^e(\d+):/.exec(id)?.[1] ?? Number.NaN)).filter((n) => Number.isInteger(n)),
  );
  return { ...doc, edges: list(doc, "edges").filter((_, i) => !drop.has(i)) };
}

/** Remove nodes and everything that references them (edges, bindings, defaults). */
export function removeNodes(doc: Doc, keys: string[]): Doc {
  const drop = new Set(keys);
  const next: Doc = {
    ...doc,
    nodes: list(doc, "nodes").filter((n) => !drop.has(String(n.node_key))),
    edges: list(doc, "edges").filter(
      (e) => !drop.has(String(e.parent_node_key)) && !drop.has(String(e.child_node_key)),
    ),
  };
  for (const k of NODE_SCOPED) {
    if (Array.isArray(doc[k])) next[k] = list(doc, k).filter((b) => !drop.has(String(b.node_key)));
  }
  if (typeof doc.root_node_key === "string" && drop.has(doc.root_node_key)) {
    next.root_node_key = nodeKeys(next)[0] ?? undefined;
  }
  return next;
}

export type ParameterBinding = { parameter: string; source_expr: string; is_required?: boolean };

/** Bindings of one node, as parameter rows (target `$.param` → `param`). */
export function nodeBindings(doc: Doc, key: string): ParameterBinding[] {
  return list(doc, "input_bindings")
    .filter((b) => b.node_key === key)
    .map((b) => ({
      parameter: String(b.target_json_path ?? "").replace(/^\$\./, ""),
      source_expr: String(b.source_expr ?? ""),
      is_required: Boolean(b.is_required),
    }));
}

/** Replace one node's parameter bindings. */
export function setNodeBindings(doc: Doc, key: string, bindings: ParameterBinding[]): Doc {
  const others = list(doc, "input_bindings").filter((b) => b.node_key !== key);
  const mine = bindings
    .filter((b) => b.parameter && b.source_expr)
    .map((b) => ({
      node_key: key,
      target_json_path: `$.${b.parameter}`,
      source_expr: b.source_expr,
      is_required: Boolean(b.is_required),
    }));
  return { ...doc, input_bindings: [...others, ...mine] };
}

/** Grid schema for an action node's parameters: literal values typed by the action + bindings. */
export function nodeParameterGridSchema(parameterSchema: Record<string, unknown> | null): Record<string, unknown> {
  const props = (parameterSchema?.properties ?? {}) as Record<string, unknown>;
  const names = Object.keys(props);
  return {
    type: "object",
    properties: {
      values: { type: "object", description: "Literal parameter values", properties: props },
      bindings: {
        type: "array",
        description: "Parameters bound from workflow variables or earlier step outputs",
        items: {
          type: "object",
          properties: {
            parameter: names.length ? { type: "string", enum: names } : { type: "string" },
            source_expr: { type: "string", description: "Variable or step output, e.g. ${vars.sample_id}" },
            is_required: { type: "boolean" },
          },
          required: ["parameter", "source_expr"],
        },
      },
    },
  };
}
