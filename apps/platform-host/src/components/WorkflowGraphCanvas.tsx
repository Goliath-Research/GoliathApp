"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import { useCallback, useMemo } from "react";
import { layoutWorkflowGraph, NODE_HEIGHT, NODE_WIDTH } from "@/lib/workflow-graph-layout";
import { connect, removeEdges, removeNodes } from "@/lib/workflow-graph-edit";

export type WorkflowGraphCanvasProps = {
  spec: Record<string, unknown> | null;
  /** When set, nodes can be connected (drag from a node's bottom handle) and deleted (Delete key). */
  onChange?: (next: Record<string, unknown>) => void;
  selectedNodeKey?: string | null;
  onSelectNode?: (key: string | null) => void;
  /** When false, the canvas uses the inactive-version node chrome (dashed border). */
  versionActive?: boolean;
};

/**
 * Canvas of a workflow version graph. Read-only unless `onChange` is given; edits change the
 * draft only — saving creates a new inactive version.
 */
export function WorkflowGraphCanvas({
  spec,
  onChange,
  selectedNodeKey,
  onSelectNode,
  versionActive,
}: WorkflowGraphCanvasProps) {
  const editable = onChange != null;
  const graph = useMemo(() => layoutWorkflowGraph(spec), [spec]);
  const nodes: Node[] = useMemo(
    () =>
      graph.nodes.map((n) => ({
        id: n.id,
        position: { x: n.x, y: n.y },
        selected: n.id === selectedNodeKey,
        data: {
          label: (
            <div className="g-graph-node__label" data-testid={`graph-node-${n.id}`}>
              <strong>{n.label}</strong>
              <span className="g-graph-node__type">{n.nodeType}</span>
              {n.detail ? <span className="g-graph-node__detail">{n.detail}</span> : null}
            </div>
          ),
        },
        className: [
          "g-graph-node",
          `g-graph-node--${n.nodeType.toLowerCase()}`,
          n.isRoot ? "g-graph-node--root" : "",
          n.isEnd ? "g-graph-node--end" : "",
          n.isError ? "g-graph-node--error" : "",
        ]
          .filter(Boolean)
          .join(" "),
        style: { width: NODE_WIDTH, minHeight: NODE_HEIGHT },
        draggable: false,
        connectable: editable,
        deletable: editable && !n.isRoot,
        selectable: true,
      })),
    [graph, editable, selectedNodeKey],
  );
  const edges: Edge[] = useMemo(
    () =>
      graph.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        deletable: editable,
      })),
    [graph, editable],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (spec && onChange && c.source && c.target) onChange(connect(spec, c.source, c.target));
    },
    [spec, onChange],
  );
  const onDelete = useCallback(
    ({ nodes: ns, edges: es }: { nodes: Node[]; edges: Edge[] }) => {
      if (!spec || !onChange) return;
      let next = spec;
      if (es.length) next = removeEdges(next, es.map((e) => e.id));
      if (ns.length) next = removeNodes(next, ns.map((n) => n.id));
      onChange(next);
      if (ns.some((n) => n.id === selectedNodeKey)) onSelectNode?.(null);
    },
    [spec, onChange, selectedNodeKey, onSelectNode],
  );

  if (graph.nodes.length === 0) {
    return <p className="g-record-editor__note">This version has no nodes to draw.</p>;
  }
  return (
    <>
      <div
        className={
          versionActive === false
            ? "g-graph-canvas g-graph-canvas--inactive"
            : versionActive === true
              ? "g-graph-canvas g-graph-canvas--active"
              : "g-graph-canvas"
        }
        aria-label={editable ? "workflow graph (editable)" : "workflow graph (read-only)"}
        data-testid="workflow-graph-canvas"
        data-version-active={versionActive == null ? undefined : String(versionActive)}
      >
        <ReactFlow
          colorMode="light"
          nodes={nodes}
          edges={edges}
          nodesDraggable={false}
          nodesConnectable={editable}
          edgesFocusable={editable}
          deleteKeyCode={editable ? ["Delete", "Backspace"] : null}
          onConnect={editable ? onConnect : undefined}
          onDelete={editable ? onDelete : undefined}
          onNodeClick={(_, n) => onSelectNode?.(n.id)}
          onPaneClick={() => onSelectNode?.(null)}
          fitView
          minZoom={0.1}
        >
          <Background />
          <MiniMap pannable zoomable />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {graph.missing.length > 0 ? (
        <p role="status" className="g-record-editor__note">
          Edges to unknown nodes are not drawn: {graph.missing.join(", ")}.
        </p>
      ) : null}
    </>
  );
}
