import { Graph, layout } from "@dagrejs/dagre";

/**
 * Read-only layout of a workflow version graph (nodes + edges from the exported spec) for the
 * graph canvas. Pure data: positions come from dagre; nothing here edits the version.
 */

export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 56;

export type CanvasNode = {
  id: string;
  label: string;
  nodeType: string;
  detail?: string;
  isRoot: boolean;
  isEnd: boolean;
  isError: boolean;
  x: number;
  y: number;
};

export type CanvasEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
};

export type CanvasGraph = { nodes: CanvasNode[]; edges: CanvasEdge[]; missing: string[] };

function str(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return "";
}

function rows(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter((x): x is Record<string, unknown> => !!x && typeof x === "object") : [];
}

function nodeDetail(n: Record<string, unknown>): string | undefined {
  switch (str(n.node_type).toUpperCase()) {
    case "ACTION":
      return str(n.action_name) || undefined;
    case "REPEAT":
      return n.repeat_count != null ? `× ${str(n.repeat_count)}` : undefined;
    case "IF":
      return str(n.condition_var) || str(n.condition_ref_node_key) || undefined;
    case "SWITCH":
      return str(n.switch_var) || str(n.switch_ref_node_key) || undefined;
    case "WHILE":
      return str(n.condition_var) || undefined;
    case "FOREACH": {
      const coll = str(n.foreach_collection_var);
      return coll ? `${str(n.foreach_item_var) || "item"} in ${coll}` : undefined;
    }
    case "WAIT_EVENT":
      return str(n.wait_event_type) || undefined;
    case "SCHEDULE":
      return n.schedule_interval_seconds != null ? `every ${str(n.schedule_interval_seconds)} s` : undefined;
    default:
      return undefined;
  }
}

function edgeLabel(e: Record<string, unknown>): string | undefined {
  const kind = str(e.branch_kind).toUpperCase();
  if (kind === "CASE") return `case ${str(e.switch_case_value)}`.trim();
  if (kind === "THEN" || kind === "ELSE" || kind === "DEFAULT" || kind === "BODY") return kind.toLowerCase();
  if (e.is_default === true) return "default";
  const order = str(e.child_order);
  return order ? `#${order}` : undefined;
}

/** Lay out nodes top-to-bottom. Edges whose endpoints are not nodes are dropped and listed in `missing`. */
export function layoutWorkflowGraph(spec: Record<string, unknown> | null | undefined): CanvasGraph {
  const nodeRows = rows(spec?.nodes);
  const root = str(spec?.root_node_key);
  const keys = new Set<string>();
  const g = new Graph();
  g.setGraph({ rankdir: "TB", nodesep: 32, ranksep: 56 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodeRows) {
    const key = str(n.node_key);
    if (!key || keys.has(key)) continue;
    keys.add(key);
    g.setNode(key, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  const missing = new Set<string>();
  const edges: CanvasEdge[] = [];
  const sorted = rows(spec?.edges)
    .map((e, i) => ({ e, i }))
    .sort((a, b) => Number(a.e.child_order ?? 0) - Number(b.e.child_order ?? 0) || a.i - b.i);
  for (const { e, i } of sorted) {
    const source = str(e.parent_node_key);
    const target = str(e.child_node_key);
    if (!keys.has(source) || !keys.has(target)) {
      if (source && !keys.has(source)) missing.add(source);
      if (target && !keys.has(target)) missing.add(target);
      continue;
    }
    g.setEdge(source, target);
    edges.push({ id: `e${i}:${source}->${target}`, source, target, label: edgeLabel(e) });
  }
  layout(g);
  const outgoing = new Set(edges.map((e) => e.source));
  const nodes: CanvasNode[] = [];
  const seen = new Set<string>();
  for (const n of nodeRows) {
    const key = str(n.node_key);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const pos = g.node(key);
    const nodeType = str(n.node_type).toUpperCase() || "NODE";
    const detail = nodeDetail(n);
    nodes.push({
      id: key,
      label: key,
      nodeType,
      detail,
      isRoot: key === root,
      isEnd: !outgoing.has(key),
      isError: nodeType === "ACTION" && !detail,
      // dagre gives centres; the canvas positions by top-left corner.
      x: (pos?.x ?? 0) - NODE_WIDTH / 2,
      y: (pos?.y ?? 0) - NODE_HEIGHT / 2,
    });
  }
  return { nodes, edges, missing: [...missing].sort() };
}
