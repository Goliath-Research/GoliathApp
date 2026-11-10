import type { PlatformObjectKind, PresentationKind } from "@goliath/ui";
import { PLATFORM_GENERIC_KIND, PLATFORM_OBJECT_KINDS } from "@goliath/ui";

/** Row from `portal.sp_session_operator_nav_tree` (via host BFF). */
export type OperatorNavNode = {
  nodeId: number;
  parentId: number | null;
  caption: string;
  seq: number;
  presentationKind: PresentationKind;
  /** Official `portal."NavTree"."NodePath"` (e.g. `/app/meta/classes`). */
  nodePath: string | null;
};

export function coercePresentationKind(raw: string): PresentationKind {
  if ((PLATFORM_OBJECT_KINDS as readonly string[]).includes(raw)) {
    return raw as PlatformObjectKind;
  }
  if (raw === PLATFORM_GENERIC_KIND) {
    return PLATFORM_GENERIC_KIND;
  }
  return PLATFORM_GENERIC_KIND;
}

export type OperatorNavTreeNode = OperatorNavNode & {
  children: OperatorNavTreeNode[];
  /** Nav href under the platform host (`/app/...`). */
  href: string;
};

/** Build nested tree from flat permission-filtered nav rows. */
export function buildOperatorNavTree(nodes: OperatorNavNode[]): OperatorNavTreeNode[] {
  const byId = new Map<number, OperatorNavTreeNode>();
  for (const node of nodes) {
    const path = node.nodePath?.trim() || null;
    const href = path && path.startsWith("/") ? path : `/app`;
    byId.set(node.nodeId, { ...node, children: [], href });
  }
  const roots: OperatorNavTreeNode[] = [];
  for (const node of byId.values()) {
    if (node.parentId != null && byId.has(node.parentId)) {
      byId.get(node.parentId)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  const sortRec = (list: OperatorNavTreeNode[]) => {
    list.sort((a, b) => a.seq - b.seq || a.nodeId - b.nodeId);
    for (const n of list) sortRec(n.children);
  };
  sortRec(roots);
  return roots;
}
