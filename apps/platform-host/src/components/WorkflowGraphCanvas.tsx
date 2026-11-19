"use client";

import "@xyflow/react/dist/style.css";

import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { useMemo } from "react";
import { layoutWorkflowGraph, NODE_HEIGHT, NODE_WIDTH } from "@/lib/workflow-graph-layout";

/**
 * Read-only canvas of a workflow version graph. Nodes cannot be dragged, connected or deleted;
 * edits go through the property grid below, which saves a new inactive version.
 */
export function WorkflowGraphCanvas({ spec }: { spec: Record<string, unknown> | null }) {
  const graph = useMemo(() => layoutWorkflowGraph(spec), [spec]);
  const nodes: Node[] = useMemo(
    () =>
      graph.nodes.map((n) => ({
        id: n.id,
        position: { x: n.x, y: n.y },
        data: {
          label: (
            <div className="g-graph-node__label">
              <strong>{n.label}</strong>
              <span className="g-graph-node__type">{n.nodeType}</span>
              {n.detail ? <span className="g-graph-node__detail">{n.detail}</span> : null}
            </div>
          ),
        },
        className: `g-graph-node g-graph-node--${n.nodeType.toLowerCase()}${n.isRoot ? " g-graph-node--root" : ""}`,
        style: { width: NODE_WIDTH, minHeight: NODE_HEIGHT },
        draggable: false,
        connectable: false,
        deletable: false,
      })),
    [graph],
  );
  const edges: Edge[] = useMemo(
    () =>
      graph.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        deletable: false,
      })),
    [graph],
  );

  if (graph.nodes.length === 0) {
    return <p className="g-record-editor__note">This version has no nodes to draw.</p>;
  }
  return (
    <>
      <div className="g-graph-canvas" aria-label="workflow graph (read-only)" data-testid="workflow-graph-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesFocusable={false}
          deleteKeyCode={null}
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
