"use client";

import { useMemo, useState } from "react";

/**
 * Generic tree editor view: nested records with expand/collapse, View / Edit, Add child,
 * Add sibling, reorder (up / down), move (drag onto a node, or a move-to-parent picker) and an
 * optional Delete. It knows nothing about the record type; callers pass nodes in sibling order
 * and callbacks (for Meta trees: sp_session_meta_tree_* through the host BFF).
 */
export type RecordTreeNode = {
  key: string;
  parentKey: string | null;
  label: string;
  /** Short secondary text (class, path). */
  detail?: string;
};

export type RecordTreeProps = {
  title: string;
  noun?: string;
  nodes: RecordTreeNode[];
  loading?: boolean;
  selectedKey?: string | null;
  onRefresh?: () => void;
  onView?: (node: RecordTreeNode) => void;
  onEdit?: (node: RecordTreeNode) => void;
  /** Add a child under `parent` (null = a new root). */
  onAddChild?: (parent: RecordTreeNode | null) => void;
  /** Add a node right after `sibling`, under the same parent. */
  onAddSibling?: (sibling: RecordTreeNode) => void;
  /** Move `node` under `parentKey` (null = root) at sibling `position` (null = last). */
  onMove?: (node: RecordTreeNode, parentKey: string | null, position: number | null) => void;
  onDelete?: (node: RecordTreeNode) => void;
  canDelete?: (node: RecordTreeNode, childCount: number) => boolean;
  testId?: string;
};

type Index = {
  children: Map<string | null, RecordTreeNode[]>;
  byKey: Map<string, RecordTreeNode>;
};

export function buildTreeIndex(nodes: RecordTreeNode[]): Index {
  const byKey = new Map(nodes.map((n) => [n.key, n]));
  const children = new Map<string | null, RecordTreeNode[]>();
  for (const n of nodes) {
    const parent = n.parentKey != null && byKey.has(n.parentKey) ? n.parentKey : null;
    const list = children.get(parent) ?? [];
    list.push(n);
    children.set(parent, list);
  }
  return { children, byKey };
}

/** Keys of `key` and everything under it (a node cannot move under these). */
export function subtreeKeys(index: Index, key: string): Set<string> {
  const out = new Set<string>([key]);
  const stack = [key];
  while (stack.length) {
    const k = stack.pop()!;
    for (const c of index.children.get(k) ?? []) {
      if (!out.has(c.key)) {
        out.add(c.key);
        stack.push(c.key);
      }
    }
  }
  return out;
}

export function RecordTree({
  title,
  noun = "node",
  nodes,
  loading = false,
  selectedKey,
  onRefresh,
  onView,
  onEdit,
  onAddChild,
  onAddSibling,
  onMove,
  onDelete,
  canDelete,
  testId,
}: RecordTreeProps) {
  const index = useMemo(() => buildTreeIndex(nodes), [nodes]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [movingKey, setMovingKey] = useState<string | null>(null);
  const [moveTarget, setMoveTarget] = useState<string>("");
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const needle = filter.trim().toLowerCase();
  const matches = useMemo(() => {
    if (!needle) return null;
    const keep = new Set<string>();
    for (const n of nodes) {
      if (`${n.label} ${n.detail ?? ""}`.toLowerCase().includes(needle)) {
        let cur: RecordTreeNode | undefined = n;
        while (cur && !keep.has(cur.key)) {
          keep.add(cur.key);
          cur = cur.parentKey != null ? index.byKey.get(cur.parentKey) : undefined;
        }
      }
    }
    return keep;
  }, [needle, nodes, index]);

  const toggle = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const drop = (target: RecordTreeNode | null) => {
    if (!dragKey || !onMove) return;
    const node = index.byKey.get(dragKey);
    setDragKey(null);
    if (!node) return;
    if (target && subtreeKeys(index, node.key).has(target.key)) return;
    onMove(node, target?.key ?? null, null);
  };

  const renderLevel = (parent: string | null, depth: number) => {
    const list = (index.children.get(parent) ?? []).filter((n) => !matches || matches.has(n.key));
    if (list.length === 0) return null;
    return (
      <ul role={depth === 0 ? "tree" : "group"} aria-label={depth === 0 ? title : undefined} className="g-record-tree__level">
        {list.map((node, i) => {
          const kids = index.children.get(node.key) ?? [];
          const open = !collapsed.has(node.key) || Boolean(matches);
          const active = selectedKey != null && selectedKey === node.key;
          const parentKey = parent;
          return (
            <li
              key={node.key}
              role="treeitem"
              aria-expanded={kids.length ? open : undefined}
              aria-selected={active}
              aria-level={depth + 1}
              data-testid={testId ? `${testId}-node-${node.key}` : undefined}
            >
              <div
                className={`g-record-tree__row${active ? " is-selected" : ""}${dragKey === node.key ? " is-dragging" : ""}`}
                draggable={Boolean(onMove)}
                onDragStart={(e) => {
                  setDragKey(node.key);
                  e.dataTransfer.effectAllowed = "move";
                }}
                onDragEnd={() => setDragKey(null)}
                onDragOver={(e) => {
                  if (dragKey && !subtreeKeys(index, dragKey).has(node.key)) e.preventDefault();
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  drop(node);
                }}
              >
                {kids.length ? (
                  <button
                    type="button"
                    className="g-record-tree__toggle"
                    aria-label={`${open ? "Collapse" : "Expand"} ${node.label}`}
                    onClick={() => toggle(node.key)}
                  >
                    {open ? "▾" : "▸"}
                  </button>
                ) : (
                  <span className="g-record-tree__toggle" aria-hidden="true" />
                )}
                <span className="g-record-tree__label">{node.label}</span>
                {node.detail ? <span className="g-record-tree__detail">{node.detail}</span> : null}
                <span className="g-record-tree__actions">
                  {onView ? (
                    <button type="button" onClick={() => onView(node)} aria-label={`View ${node.label}`}>
                      View
                    </button>
                  ) : null}
                  {onEdit ? (
                    <button type="button" onClick={() => onEdit(node)} aria-label={`Edit ${node.label}`}>
                      Edit
                    </button>
                  ) : null}
                  {onAddChild ? (
                    <button type="button" onClick={() => onAddChild(node)} aria-label={`Add child under ${node.label}`}>
                      Add child
                    </button>
                  ) : null}
                  {onAddSibling ? (
                    <button type="button" onClick={() => onAddSibling(node)} aria-label={`Add sibling after ${node.label}`}>
                      Add sibling
                    </button>
                  ) : null}
                  {onMove ? (
                    <>
                      <button
                        type="button"
                        disabled={i === 0}
                        onClick={() => onMove(node, parentKey, i - 1)}
                        aria-label={`Move ${node.label} up`}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        disabled={i === list.length - 1}
                        onClick={() => onMove(node, parentKey, i + 1)}
                        aria-label={`Move ${node.label} down`}
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setMovingKey(node.key);
                          setMoveTarget(parentKey ?? "");
                        }}
                        aria-label={`Move ${node.label} to another parent`}
                      >
                        Move…
                      </button>
                    </>
                  ) : null}
                  {onDelete && (canDelete == null || canDelete(node, kids.length)) ? (
                    <button type="button" onClick={() => onDelete(node)} aria-label={`Delete ${node.label}`}>
                      Delete
                    </button>
                  ) : null}
                </span>
              </div>
              {movingKey === node.key && onMove ? (
                <form
                  className="g-record-tree__move"
                  onSubmit={(e) => {
                    e.preventDefault();
                    setMovingKey(null);
                    onMove(node, moveTarget === "" ? null : moveTarget, null);
                  }}
                >
                  <label>
                    New parent{" "}
                    <select value={moveTarget} onChange={(e) => setMoveTarget(e.target.value)}>
                      <option value="">(top level)</option>
                      {nodes
                        .filter((n) => !subtreeKeys(index, node.key).has(n.key))
                        .map((n) => (
                          <option key={n.key} value={n.key}>
                            {n.label}
                            {n.detail ? ` — ${n.detail}` : ""}
                          </option>
                        ))}
                    </select>
                  </label>
                  <button type="submit">Move</button>
                  <button type="button" onClick={() => setMovingKey(null)}>
                    Cancel
                  </button>
                </form>
              ) : null}
              {kids.length && open ? renderLevel(node.key, depth + 1) : null}
            </li>
          );
        })}
      </ul>
    );
  };

  return (
    <section className="g-record-tree" data-testid={testId} aria-label={`${title} tree`}>
      <header className="g-record-grid__toolbar">
        <h3 className="g-record-grid__title">{title}</h3>
        <input
          type="search"
          className="g-record-grid__filter"
          placeholder="Filter…"
          aria-label={`Filter ${title}`}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <span className="g-record-grid__count" role="status">
          {nodes.length} {nodes.length === 1 ? noun : `${noun}s`}
        </span>
        <button type="button" className="g-host-button" onClick={() => setCollapsed(new Set())}>
          Expand all
        </button>
        <button
          type="button"
          className="g-host-button"
          onClick={() => setCollapsed(new Set(nodes.filter((n) => index.children.has(n.key)).map((n) => n.key)))}
        >
          Collapse all
        </button>
        {onRefresh ? (
          <button type="button" className="g-host-button" onClick={onRefresh} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        ) : null}
        {onAddChild ? (
          <button
            type="button"
            className="g-host-button g-host-button--primary"
            onClick={() => onAddChild(null)}
            data-testid={testId ? `${testId}-add` : undefined}
          >
            Add {noun}
          </button>
        ) : null}
      </header>
      {nodes.length === 0 ? (
        <p role="status">{loading ? "Loading…" : `No ${noun}s yet.`}</p>
      ) : (
        renderLevel(null, 0)
      )}
      {onMove && dragKey ? (
        <div
          className="g-record-tree__root-drop"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            drop(null);
          }}
        >
          Drop here to move to the top level
        </div>
      ) : null}
    </section>
  );
}
