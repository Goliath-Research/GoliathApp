"use client";

/**
 * Web port of the SchemaPropertyGrid contract documented on `wf.data_type.schema_json`
 * (see `workflow_engine/sql_pg/wf_data_type.sql`): one vertical row per property, editor
 * chosen from flattened JSON Schema with Meta field fallback.
 */

import type { MetaClassField } from "@goliath/client";
import type { FormEvent, ReactNode } from "react";
import { useMemo, useState } from "react";
import { type ParsedFieldEditor } from "./parseFlattenedFieldSchema.js";
import { resolveFieldEditor } from "./resolveFieldEditor.js";

export type SchemaPropertyGridProps = {
  fields: MetaClassField[];
  flattenedSchema: unknown;
  initialDocument?: Record<string, unknown>;
  onSubmit: (document: Record<string, unknown>) => void | Promise<void>;
  submitLabel?: string;
  disabled?: boolean;
  /** Optional slot above the grid (child `editorComponents` override). */
  headerSlot?: ReactNode;
};

type FieldPlan = {
  field: MetaClassField;
  editor: ParsedFieldEditor;
};

export function SchemaPropertyGrid({
  fields,
  flattenedSchema,
  initialDocument = {},
  onSubmit,
  submitLabel = "Save instance",
  disabled = false,
  headerSlot,
}: SchemaPropertyGridProps) {
  const plans = useMemo((): FieldPlan[] => {
    return [...fields]
      .sort((a, b) => a.fieldName.localeCompare(b.fieldName))
      .map((field) => ({
        field,
        editor: resolveFieldEditor(field, flattenedSchema),
      }));
  }, [fields, flattenedSchema]);

  const [values, setValues] = useState<Record<string, string>>(() => {
    const next: Record<string, string> = {};
    for (const { field } of plans) {
      const raw = initialDocument[field.fieldName];
      if (raw == null) {
        next[field.fieldName] = "";
      } else if (typeof raw === "object") {
        next[field.fieldName] = JSON.stringify(raw);
      } else {
        next[field.fieldName] = String(raw);
      }
    }
    return next;
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function buildDocument(): Record<string, unknown> | null {
    const document: Record<string, unknown> = {};
    for (const { field, editor } of plans) {
      const raw = values[field.fieldName] ?? "";
      if (editor.mode === "json") {
        if (raw === "") {
          if (!editor.optional) {
            setError(`Field ${field.fieldName} requires JSON (unsupported schema)`);
            return null;
          }
          continue;
        }
        try {
          document[field.fieldName] = JSON.parse(raw);
        } catch {
          setError(`Field ${field.fieldName} must be valid JSON`);
          return null;
        }
        continue;
      }

      if (raw === "") {
        if (!editor.optional && field.required) {
          setError(`Field ${field.fieldName} is required`);
          return null;
        }
        continue;
      }

      switch (editor.mode) {
        case "boolean":
          document[field.fieldName] = raw === "true";
          break;
        case "integer":
          document[field.fieldName] = Math.trunc(Number(raw));
          break;
        case "number":
          document[field.fieldName] = Number(raw);
          break;
        case "string":
          document[field.fieldName] = raw;
          break;
        case "array": {
          try {
            const parsed = JSON.parse(raw) as unknown;
            if (!Array.isArray(parsed)) {
              setError(`Field ${field.fieldName} must be a JSON array`);
              return null;
            }
            document[field.fieldName] = parsed;
          } catch {
            setError(`Field ${field.fieldName} must be a JSON array`);
            return null;
          }
          break;
        }
        case "object": {
          try {
            document[field.fieldName] = JSON.parse(raw);
          } catch {
            setError(`Field ${field.fieldName} must be a JSON object`);
            return null;
          }
          break;
        }
        default:
          break;
      }
    }
    return document;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const document = buildDocument();
    if (!document) return;
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
    <form onSubmit={handleSubmit} className="g-meta-field-form g-schema-property-grid">
      {headerSlot}
      <p className="g-host-home__lead">
        Vertical property grid: flattened JSON Schema picks the control per field (enums, primitives,
        arrays, shallow objects). Unsupported constructs use JSON fallback; server Meta validation is
        authoritative.
      </p>
      {plans.map(({ field, editor }) => {
        const id = `meta-field-${field.fieldName}`;
        const jsonFallback = editor.mode === "json";
        return (
          <p key={field.fieldName} className="g-meta-field-row">
            <label htmlFor={id}>
              {field.fieldName}
              {field.required ? " *" : ""}
            </label>
            {editor.mode === "boolean" ? (
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
            ) : editor.mode === "string" && editor.enumValues ? (
              <select
                id={id}
                className="g-host-input"
                value={values[field.fieldName] ?? ""}
                disabled={disabled || busy}
                onChange={(e) =>
                  setValues((prev) => ({ ...prev, [field.fieldName]: e.target.value }))
                }
              >
                <option value="">—</option>
                {editor.enumValues.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            ) : jsonFallback || editor.mode === "array" || editor.mode === "object" ? (
              <textarea
                id={id}
                rows={3}
                className="g-host-textarea"
                value={values[field.fieldName] ?? ""}
                disabled={disabled || busy}
                onChange={(e) =>
                  setValues((prev) => ({ ...prev, [field.fieldName]: e.target.value }))
                }
                spellCheck={false}
                aria-describedby={jsonFallback ? `${id}-hint` : undefined}
              />
            ) : (
              <input
                id={id}
                type={editor.mode === "integer" || editor.mode === "number" ? "number" : "text"}
                className="g-host-input"
                value={values[field.fieldName] ?? ""}
                disabled={disabled || busy}
                onChange={(e) =>
                  setValues((prev) => ({ ...prev, [field.fieldName]: e.target.value }))
                }
              />
            )}
            {jsonFallback ? (
              <span id={`${id}-hint`} className="g-host-home__lead">
                JSON fallback ({editor.reason})
              </span>
            ) : null}
          </p>
        );
      })}
      <button type="submit" className="g-host-button" disabled={disabled || busy}>
        {submitLabel}
      </button>
      {error ? <p role="alert">{error}</p> : null}
    </form>
  );
}
