"use client";

import { ObjectBadge } from "@goliath/ui";

export type MetaClassListRow = {
  classId: number;
  className: string;
  parentId: number | null;
  isAbstract: boolean;
};

function classWorkbenchHref(className: string): string {
  return `/app/meta?class=${encodeURIComponent(className)}`;
}

export function MetaClassHierarchyList({
  classes,
  selectedClassName,
  semanticHighlight,
}: {
  classes: MetaClassListRow[];
  selectedClassName?: string;
  /** When set, visually emphasize classes in this namespace prefix (child semantic extensions). */
  semanticHighlight?: string;
}) {
  const byParent = new Map<number | null, MetaClassListRow[]>();
  for (const row of classes) {
    const key = row.parentId;
    const bucket = byParent.get(key) ?? [];
    bucket.push(row);
    byParent.set(key, bucket);
  }
  for (const bucket of byParent.values()) {
    bucket.sort((a, b) => a.className.localeCompare(b.className));
  }

  function Branch({ parentId, depth }: { parentId: number | null; depth: number }) {
    const kids = byParent.get(parentId) ?? [];
    if (kids.length === 0) return null;
    return (
      <ul className="g-meta-hierarchy" style={{ marginLeft: depth ? "1rem" : 0 }}>
        {kids.map((row) => {
          const selected = selectedClassName === row.className;
          const semantic =
            semanticHighlight != null &&
            semanticHighlight.length > 0 &&
            row.className.startsWith(semanticHighlight);
          const href = classWorkbenchHref(row.className);
          return (
            <li key={row.classId}>
              <a
                href={href}
                className={
                  selected
                    ? "g-meta-hierarchy__link g-meta-hierarchy__link--active"
                    : semantic
                      ? "g-meta-hierarchy__link g-meta-hierarchy__link--semantic"
                      : "g-meta-hierarchy__link"
                }
                aria-current={selected ? "true" : undefined}
              >
                <ObjectBadge
                  kind="meta_class"
                  label={row.className}
                  classFqn={row.className}
                  subtitle={row.isAbstract ? "abstract" : undefined}
                />
              </a>
              <Branch parentId={row.classId} depth={depth + 1} />
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <section aria-labelledby="meta-hierarchy-heading">
      <h3 id="meta-hierarchy-heading">Class hierarchy</h3>
      <p className="g-host-home__lead">
        Browse inherited platform classes and child-app semantic extensions. Selecting a class opens the Meta workbench
        with SchemaPropertyGrid and the nested inspector.
      </p>
      <Branch parentId={null} depth={0} />
    </section>
  );
}
