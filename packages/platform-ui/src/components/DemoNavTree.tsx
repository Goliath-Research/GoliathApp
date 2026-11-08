import { ObjectBadge } from "@goliath/ui";
import type { FixtureTreeNode } from "../fixture/sample-rows.js";

function TreeBranch({ node, depth }: { node: FixtureTreeNode; depth: number }) {
  return (
    <li>
      <ObjectBadge kind={node.kind} label={node.label} fixture />
      {node.children?.length ? (
        <ul className="g-demo-tree" aria-label={`${node.label} children`}>
          {node.children.map((child) => (
            <TreeBranch key={child.id} node={child} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function DemoNavTree({ root }: { root: FixtureTreeNode }) {
  return (
    <ul className="g-demo-tree" aria-label="Fixture navigation tree">
      <TreeBranch node={root} depth={0} />
    </ul>
  );
}
