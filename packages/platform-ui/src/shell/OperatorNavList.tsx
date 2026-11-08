import { ObjectBadge } from "@goliath/ui";
import type { OperatorNavNode } from "@goliath/client";

export function OperatorNavList({
  nodes,
  "aria-label": ariaLabel = "Operator navigation",
}: {
  nodes: OperatorNavNode[];
  "aria-label"?: string;
}) {
  if (nodes.length === 0) {
    return (
      <p className="g-operator-nav__empty" role="status">
        No navigation entries are authorized for this session.
      </p>
    );
  }

  const sorted = [...nodes].sort((a, b) => a.seq - b.seq || a.nodeId - b.nodeId);

  return (
    <ul className="g-operator-nav" aria-label={ariaLabel}>
      {sorted.map((node) => (
        <li key={node.nodeId}>
          <ObjectBadge kind={node.presentationKind} label={node.caption} />
        </li>
      ))}
    </ul>
  );
}
