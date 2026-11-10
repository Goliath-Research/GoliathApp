"use client";

import { useState } from "react";

type Props = {
  parentClasses: string[];
  defaultParent?: string;
};

export function ModelAuthoringPanel({ parentClasses, defaultParent }: Props) {
  const [parentName, setParentName] = useState(defaultParent ?? parentClasses[0] ?? "platform/Entity");
  const [className, setClassName] = useState("");
  const [fieldClass, setFieldClass] = useState("");
  const [fieldName, setFieldName] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  async function post(body: Record<string, unknown>) {
    const res = await fetch("/api/portal/model", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = (await res.json().catch(() => ({}))) as { error?: string };
    if (!res.ok) throw new Error(payload.error ?? `Failed (${res.status})`);
  }

  async function createClass(e: React.FormEvent) {
    e.preventDefault();
    setStatus(null);
    try {
      await post({ action: "meta_class_create", className, parentClassName: parentName });
      setStatus(`Created class ${className}`);
      setClassName("");
      window.location.reload();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Create failed");
    }
  }

  async function addField(e: React.FormEvent) {
    e.preventDefault();
    setStatus(null);
    try {
      await post({
        action: "meta_field_upsert",
        className: fieldClass,
        fieldName,
        typeName: "portal/nav/Caption",
        typeVersion: "1.0",
        required: true,
      });
      setStatus(`Field ${fieldName} saved on ${fieldClass}`);
      setFieldName("");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Field save failed");
    }
  }

  return (
    <section className="g-model-authoring" aria-labelledby="model-authoring-heading">
      <h3 id="model-authoring-heading">Model authoring</h3>
      <p className="g-host-home__lead">
        Create Meta subclasses under the platform generic hierarchy, then add fields. Pair new classes with semantic
        entities in the Semantic layer workspace.
      </p>
      {status ? (
        <p role="status" className="g-portal-status">
          {status}
        </p>
      ) : null}
      <form className="g-portal-form" onSubmit={createClass}>
        <h4>Create subclass</h4>
        <label>
          Parent class
          <select value={parentName} onChange={(e) => setParentName(e.target.value)}>
            {parentClasses.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          New class FQN
          <input
            placeholder="your_app/Customer"
            value={className}
            onChange={(e) => setClassName(e.target.value)}
            required
          />
        </label>
        <button type="submit">Create class</button>
      </form>
      <form className="g-portal-form" onSubmit={addField}>
        <h4>Add or update field</h4>
        <label>
          Class
          <input value={fieldClass} onChange={(e) => setFieldClass(e.target.value)} required />
        </label>
        <label>
          Field name
          <input value={fieldName} onChange={(e) => setFieldName(e.target.value)} required />
        </label>
        <button type="submit">Save field</button>
      </form>
    </section>
  );
}
