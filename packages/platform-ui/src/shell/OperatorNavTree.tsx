"use client";

import { useMemo, useState } from "react";
import { ObjectBadge } from "@goliath/ui";
import type { OperatorNavNode } from "@goliath/client";
import { buildOperatorNavTree, type OperatorNavTreeNode } from "./buildOperatorNavTree.js";

function pathMatches(navHref: string, pathname: string): boolean {
  if (navHref === "/app") return pathname === "/app";
  return pathname === navHref || pathname.startsWith(`${navHref}/`);
}

function NavTreeBranch({
  node,
  depth,
  pathname,
  openFolders,
  onToggle,
}: {
  node: OperatorNavTreeNode;
  depth: number;
  pathname: string;
  openFolders: Record<number, boolean>;
  onToggle: (nodeId: number, depth: number) => void;
}) {
  const hasChildren = node.children.length > 0;
  const selected = pathMatches(node.href, pathname);
  const expanded = openFolders[node.nodeId] ?? depth < 2;

  if (!hasChildren) {
    return (
      <a
        href={node.href}
        className={selected ? "g-portal-nav__leaf g-portal-nav__leaf--active" : "g-portal-nav__leaf"}
        style={{ paddingLeft: `${12 + depth * 14}px` }}
        aria-current={selected ? "page" : undefined}
      >
        <ObjectBadge kind={node.presentationKind} label={node.caption} />
      </a>
    );
  }

  return (
    <div className="g-portal-nav__branch">
      <button
        type="button"
        className="g-portal-nav__folder"
        style={{ paddingLeft: `${8 + depth * 14}px` }}
        onClick={() => onToggle(node.nodeId, depth)}
        aria-expanded={expanded}
      >
        <span className={expanded ? "g-portal-nav__chev g-portal-nav__chev--open" : "g-portal-nav__chev"} aria-hidden />
        <ObjectBadge kind={node.presentationKind} label={node.caption} />
      </button>
      {expanded ? (
        <div className="g-portal-nav__children">
          <a
            href={node.href}
            className={
              selected ? "g-portal-nav__leaf g-portal-nav__leaf--active" : "g-portal-nav__leaf g-portal-nav__leaf--section"
            }
            style={{ paddingLeft: `${12 + (depth + 1) * 14}px` }}
            aria-current={selected ? "page" : undefined}
          >
            Open {node.caption}
          </a>
          {node.children.map((child) => (
            <NavTreeBranch
              key={child.nodeId}
              node={child}
              depth={depth + 1}
              pathname={pathname}
              openFolders={openFolders}
              onToggle={onToggle}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function OperatorNavTree({
  nodes,
  currentPath,
  "aria-label": ariaLabel = "Platform navigation",
}: {
  nodes: OperatorNavNode[];
  /** Current browser path (e.g. from Next `usePathname` in the host). */
  currentPath: string;
  "aria-label"?: string;
}) {
  const tree = useMemo(() => buildOperatorNavTree(nodes), [nodes]);
  const [openFolders, setOpenFolders] = useState<Record<number, boolean>>({});

  if (tree.length === 0) {
    return (
      <p className="g-operator-nav__empty" role="status">
        No navigation entries are authorized for this session.
      </p>
    );
  }

  return (
    <nav className="g-portal-nav" aria-label={ariaLabel}>
      {tree.map((node) => (
        <NavTreeBranch
          key={node.nodeId}
          node={node}
          depth={0}
          pathname={currentPath}
          openFolders={openFolders}
          onToggle={(id, depth) =>
            setOpenFolders((prev) => ({ ...prev, [id]: !(prev[id] ?? depth < 2) }))
          }
        />
      ))}
    </nav>
  );
}
