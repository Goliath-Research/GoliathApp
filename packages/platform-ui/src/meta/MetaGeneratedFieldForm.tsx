"use client";

import type { MetaClassField } from "@goliath/client";
import type { FormEvent } from "react";
import { useMemo, useState } from "react";

export type MetaGeneratedFieldFormProps = {
  fields: MetaClassField[];
  initialDocument?: Record<string, unknown>;
  onSubmit: (document: Record<string, unknown>) => void | Promise<void>;
  submitLabel?: string;
  disabled?: boolean;
};

function inferInputKind(
  typeKind: string | null | undefined,
  typeName: string | null,
): "text" | "number" | "checkbox" {
  const kind = typeKind?.toLowerCase();
  if (kind === "int" || kind === "number") {
    return "number";
  }
  if (kind === "bool") {
    return "checkbox";
  }
  if (kind) {
    return "text";
  }
  if (!typeName) return "text";
  const lower = typeName.toLowerCase();
  if (lower.includes("int") || lower.includes("number") || lower.includes("decimal")) {
    return "number";
  }
  if (lower.includes("bool")) {
    return "checkbox";
  }
  return "text";
}

export function MetaGeneratedFieldForm({
  fields,
  initialDocument = {},
  onSubmit,
  submitLabel = "Save instance",
  disabled = false,
}: MetaGeneratedFieldFormProps) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const next: Record<string, string> = {};
    for (const field of fields) {
      const raw = initialDocument[field.fieldName];
      next[field.fieldName] = raw == null ? "" : String(raw);
    }
    return next;
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const orderedFields = useMemo(
    () => [...fields].sort((a, b) => a.fieldName.localeCompare(b.fieldName)),
    [fields],
  );

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const document: Record<string, unknown> = {};
    for (const field of orderedFields) {
      const raw = values[field.fieldName] ?? "";
      const kind = inferInputKind(field.typeKind, field.typeName);
      if (kind === "checkbox") {
        document[field.fieldName] = raw === "true";
        continue;
      }
      if (raw === "") {
        if (field.required) {
          setError(`Field ${field.fieldName} is required`);
          return;
        }
        continue;
      }
      if (kind === "number") {
        const n = Number(raw);
        if (!Number.isFinite(n)) {
          setError(`Field ${field.fieldName} must be a number`);
          return;
        }
        const typeKind = field.typeKind?.toLowerCase();
        document[field.fieldName] =
          typeKind === "int" || (typeKind == null && field.typeName?.toLowerCase().includes("int"))
            ? Math.trunc(n)
            : n;
        continue;
      }
      document[field.fieldName] = raw;
    }
    setBusy(true);
    try {
      await onSubmit(document);
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="g-meta-field-form">
      <p className="g-host-home__lead">
        Generated from resolved Meta fields (string/int only in this slice). Complex refs and nested objects
        still require JSON or a child <code>editorComponents</code> override.
      </p>
      {orderedFields.map((field) => {
        const kind = inferInputKind(field.typeKind, field.typeName);
        const id = `meta-field-${field.fieldName}`;
        return (
          <p key={field.fieldName} className="g-meta-field-row">
            <label htmlFor={id}>
              {field.fieldName}
              {field.required ? " *" : ""}
            </label>
            {kind === "checkbox" ? (
              <input
                id={id}
                type="checkbox"
                checked={values[field.fieldName] === "true"}
                disabled={disabled || busy}
                onChange={(e) =>
                  setValues((prev) => ({
                    ...prev,
                    [field.fieldName]: e.target.checked ? "true" : "false",
                  }))
                }
              />
            ) : (
              <input
                id={id}
                type={kind === "number" ? "number" : "text"}
                className="g-host-input"
                value={values[field.fieldName] ?? ""}
                disabled={disabled || busy}
                onChange={(e) =>
                  setValues((prev) => ({ ...prev, [field.fieldName]: e.target.value }))
                }
              />
            )}
          </p>
        );
      })}
      <button type="submit" className="g-host-button" disabled={disabled || busy}>
        {submitLabel}
      </button>
      {error ? (
        <p role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
