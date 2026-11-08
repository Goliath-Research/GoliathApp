"use client";

import type { MetaClassField, MetaClassLineageNode, MetaClassSummary } from "@goliath/client";
import { ObjectBadge, resolvePresentation } from "@goliath/ui";
import type { ReactNode } from "react";

export type MetaClassExplorerProps = {
  summary: MetaClassSummary;
  lineage: MetaClassLineageNode[];
  fields: MetaClassField[];
  /** Optional child-registered editor slot (opaque key from GoliathUiManifest). */
  editorSlot?: ReactNode;
};

function ancestryChain(lineage: MetaClassLineageNode[], className: string): string[] {
  const ancestors = lineage
    .filter((n) => n.lineageRole === "ancestor" || n.lineageRole === "self")
    .sort((a, b) => b.depth - a.depth)
    .map((n) => n.className);
  if (!ancestors.includes(className)) {
    return [className, ...ancestors];
  }
  return ancestors;
}

export function MetaClassExplorer({ summary, lineage, fields, editorSlot }: MetaClassExplorerProps) {
  const ancestry = ancestryChain(lineage, summary.className);
  const classPresentation = resolvePresentation({
    kind: "meta_class",
    classFqn: summary.className,
    classAncestry: ancestry,
    label: summary.className,
  });

  return (
    <div className="g-meta-explorer">
      <section aria-labelledby="meta-class-heading">
        <h3 id="meta-class-heading">Meta class</h3>
        <p>
          <ObjectBadge
            kind={classPresentation.kind}
            label={classPresentation.label}
            iconKey={classPresentation.iconKey}
          />
          {summary.parentName ? (
            <span>
              {" "}
              extends{" "}
              <ObjectBadge kind="meta_class" label={summary.parentName} classFqn={summary.parentName} />
            </span>
          ) : null}
        </p>
        <p>
          Catalog type: <code>{summary.catalogTypeName}</code>
          {summary.isAbstract ? " · abstract" : null}
        </p>
      </section>

      <section aria-labelledby="meta-lineage-heading">
        <h3 id="meta-lineage-heading">Hierarchy</h3>
        <ul className="g-operator-nav" aria-label="Class lineage">
          {lineage.map((node) => {
            const pres = resolvePresentation({
              kind: node.lineageRole === "self" ? "meta_object" : "meta_class",
              classFqn: node.className,
              classAncestry: ancestry,
              label: `${node.lineageRole}: ${node.className}`,
            });
            return (
              <li key={`${node.lineageRole}-${node.classId}`}>
                <ObjectBadge kind={pres.kind} label={pres.label} iconKey={pres.iconKey} />
              </li>
            );
          })}
        </ul>
      </section>

      <section aria-labelledby="meta-fields-heading">
        <h3 id="meta-fields-heading">Resolved fields</h3>
        <table className="g-host-table">
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Type</th>
              <th scope="col">Origin</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => (
              <tr key={field.fieldName}>
                <td>
                  <ObjectBadge
                    kind="meta_field"
                    label={field.fieldName}
                    classFqn={summary.className}
                    classAncestry={ancestry}
                  />
                  {field.required ? " *" : ""}
                </td>
                <td>
                  <code>{field.typeName ?? "unknown"}</code>
                </td>
                <td>
                  {field.isLocal ? (
                    <span>local</span>
                  ) : (
                    <span>
                      inherited from{" "}
                      <ObjectBadge kind="meta_class" label={field.declaredOnClassName} />
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {editorSlot ? (
        <section aria-labelledby="meta-editor-heading">
          <h3 id="meta-editor-heading">Document editor (P2)</h3>
          {editorSlot}
        </section>
      ) : null}
    </div>
  );
}
