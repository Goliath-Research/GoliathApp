"use client";

import { useCallback, useState } from "react";

export type SemanticEntityRow = {
  id: number;
  namespace: string;
  code: string;
  displayName: string;
  metaClassName: string | null;
};

export type SemanticNamespaceRow = Record<string, unknown>;
export type SemanticAttributeRow = Record<string, unknown>;

type Props = {
  entities: SemanticEntityRow[];
  namespaces: SemanticNamespaceRow[];
  attributes: SemanticAttributeRow[];
  metaClasses: string[];
};

async function postModel(body: Record<string, unknown>) {
  const res = await fetch("/api/portal/model", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = (await res.json().catch(() => ({}))) as { error?: string };
  if (!res.ok) {
    throw new Error(payload.error ?? `Request failed (${res.status})`);
  }
  return payload;
}

export function SemanticLayerWorkspace({ entities, namespaces, attributes, metaClasses }: Props) {
  const [status, setStatus] = useState<string | null>(null);
  const [ns, setNs] = useState("");
  const [entityCode, setEntityCode] = useState("");
  const [entityLabel, setEntityLabel] = useState("");
  const [metaClass, setMetaClass] = useState(metaClasses[0] ?? "platform/Material");
  const [attrEntityId, setAttrEntityId] = useState(entities[0]?.id ?? 0);
  const [attrCode, setAttrCode] = useState("");
  const [attrColumn, setAttrColumn] = useState("");

  const reload = useCallback(() => {
    window.location.reload();
  }, []);

  async function registerEntity(e: React.FormEvent) {
    e.preventDefault();
    setStatus(null);
    try {
      await postModel({
        action: "semantic_register_entity",
        namespace: ns,
        code: entityCode,
        displayName: entityLabel,
        metaClassName: metaClass,
      });
      setStatus("Entity registered.");
      reload();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Failed");
    }
  }

  async function registerAttribute(e: React.FormEvent) {
    e.preventDefault();
    setStatus(null);
    try {
      await postModel({
        action: "semantic_register_attribute",
        entityId: attrEntityId,
        code: attrCode,
        columnName: attrColumn,
        jsonType: "string",
      });
      setStatus("Attribute registered.");
      reload();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Failed");
    }
  }

  function resolveExportPrefix(): string {
    const namespace = ns.trim();
    if (namespace) return `${namespace}/`;
    const slash = metaClass.indexOf("/");
    if (slash > 0) return `${metaClass.slice(0, slash + 1)}`;
    return "your_app/";
  }

  async function exportPackage() {
    setStatus(null);
    try {
      const prefix = resolveExportPrefix();
      const res = await fetch(`/api/portal/model?prefix=${encodeURIComponent(prefix)}`, {
        credentials: "same-origin",
      });
      const body = (await res.json()) as { sql?: string; error?: string };
      if (!res.ok) throw new Error(body.error ?? "Export failed");
      const blob = new Blob([body.sql ?? ""], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "goliath-model-package.sql";
      a.click();
      URL.revokeObjectURL(url);
      setStatus("Package downloaded.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Export failed");
    }
  }

  return (
    <div className="g-semantic-workspace">
      <p className="g-host-home__lead">
        Register semantic namespaces, entities, and attributes bound to Meta classes. Changes persist in your
        deployment database and can be exported as SQL for a child application repository.
      </p>
      {status ? (
        <p className="g-portal-status" role="status">
          {status}
        </p>
      ) : null}

      <section aria-labelledby="semantic-ns-heading">
        <h3 id="semantic-ns-heading">Namespaces</h3>
        <PlatformTable
          columns={[
            { key: "code", label: "Code" },
            { key: "display_name", label: "Display name" },
          ]}
          rows={namespaces}
        />
      </section>

      <section aria-labelledby="semantic-entity-form-heading">
        <h3 id="semantic-entity-form-heading">Register entity</h3>
        <form className="g-portal-form" onSubmit={registerEntity}>
          <label>
            Namespace
            <input value={ns} onChange={(ev) => setNs(ev.target.value)} required />
          </label>
          <label>
            Entity code
            <input value={entityCode} onChange={(ev) => setEntityCode(ev.target.value)} required />
          </label>
          <label>
            Display name
            <input value={entityLabel} onChange={(ev) => setEntityLabel(ev.target.value)} required />
          </label>
          <label>
            Meta class
            <select value={metaClass} onChange={(ev) => setMetaClass(ev.target.value)}>
              {metaClasses.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Save entity</button>
        </form>
        <PlatformTable
          columns={[
            { key: "namespace", label: "Namespace" },
            { key: "code", label: "Code" },
            { key: "displayName", label: "Display" },
            { key: "metaClassName", label: "Meta class" },
          ]}
          rows={entities}
        />
      </section>

      <section aria-labelledby="semantic-attr-heading">
        <h3 id="semantic-attr-heading">Attributes</h3>
        <form className="g-portal-form" onSubmit={registerAttribute}>
          <label>
            Entity
            <select value={attrEntityId} onChange={(ev) => setAttrEntityId(Number(ev.target.value))}>
              {entities.map((ent) => (
                <option key={ent.id} value={ent.id}>
                  {ent.namespace}.{ent.code}
                </option>
              ))}
            </select>
          </label>
          <label>
            Attribute code
            <input value={attrCode} onChange={(ev) => setAttrCode(ev.target.value)} required />
          </label>
          <label>
            Column name
            <input value={attrColumn} onChange={(ev) => setAttrColumn(ev.target.value)} required />
          </label>
          <button type="submit">Save attribute</button>
        </form>
        <PlatformTable
          columns={[
            { key: "entity_id", label: "Entity ID" },
            { key: "code", label: "Code" },
            { key: "column_name", label: "Column" },
            { key: "json_type", label: "Type" },
          ]}
          rows={attributes}
        />
      </section>

      <p>
        <button type="button" onClick={() => void exportPackage()}>
          Export as package SQL
        </button>
      </p>
    </div>
  );
}

function PlatformTable({
  columns,
  rows,
}: {
  columns: { key: string; label: string }[];
  rows: Record<string, unknown>[] | SemanticEntityRow[];
}) {
  return (
    <table className="g-host-table">
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.key} scope="col">
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={columns.length}>No rows.</td>
          </tr>
        ) : (
          rows.map((row, idx) => (
            <tr key={idx}>
              {columns.map((c) => (
                <td key={c.key}>{String((row as Record<string, unknown>)[c.key] ?? "—")}</td>
              ))}
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
