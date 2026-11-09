"use client";

import type { MetaClassField } from "@goliath/client";
import type { FormEvent, ReactNode } from "react";
import { useId, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import {
  isSchemaRecord,
  resolveSchemaNode,
  type SyntheticSchemaField,
  SCHEMA_PROPERTY_GRID_MAX_DEPTH,
} from "./jsonSchema.js";
import type { CatalogRef } from "./catalogRef.js";
import { CatalogNestedSchemaDialog } from "./CatalogNestedSchemaDialog.js";
import { NestedSchemaDialog } from "./NestedSchemaDialog.js";
import type { MetaCatalogResolver } from "./metaCatalogResolver.js";
import type { HierarchyPresentationRegistry } from "./metaHierarchyResolver.js";
import type { ParsedFieldEditor } from "./parseFlattenedFieldSchema.js";
import { parsePropertySchema, propertySchemaFromFlattened } from "./parseFlattenedFieldSchema.js";
import { compileSchemaValidator, validationMessage } from "./schemaAjvValidate.js";
import { resolveFieldEditorDetailed } from "./resolveFieldEditor.js";

const DEFAULT_HIERARCHY_REGISTRY = {
  editorComponentsByClassFqn: {},
  iconOverridesByClassFqn: {},
  editorComponentsByDataTypeName: {},
};

export type SchemaPropertyGridSurfaceProps = {
  fields?: MetaClassField[];
  syntheticFields?: SyntheticSchemaField[];
  schema: unknown;
  rootSchema: Record<string, unknown>;
  bundledSchema?: unknown;
  registry?: HierarchyPresentationRegistry;
  catalogResolver?: MetaCatalogResolver;
  documentClassFqn?: string;
  declaringClassAncestryByField?: Record<string, readonly string[]>;
  initialDocument?: Record<string, unknown>;
  onSubmit?: (document: Record<string, unknown>) => void | Promise<void>;
  onDraftChange?: (document: Record<string, unknown>) => void;
  submitLabel?: string;
  disabled?: boolean;
  headerSlot?: ReactNode;
  depth?: number;
  embedded?: boolean;
};

type FieldPlan = {
  fieldName: string;
  required: boolean;
  editor: ParsedFieldEditor;
  catalogTarget: CatalogRef | null;
};

type DialogState =
  | {
      kind: "object";
      fieldName: string;
      schema: Record<string, unknown>;
      value: Record<string, unknown>;
    }
  | {
      kind: "catalog";
      fieldName: string;
      catalogTarget: CatalogRef;
      value: Record<string, unknown>;
      arrayIndex?: number;
      isNew?: boolean;
    }
  | {
      kind: "array-item";
      fieldName: string;
      index: number;
      schema: Record<string, unknown>;
      value: Record<string, unknown>;
      isNew: boolean;
    }
  | null;

function summaryObject(value: Record<string, unknown> | undefined): string {
  if (!value || Object.keys(value).length === 0) return "—";
  return `${Object.keys(value).length} field(s)`;
}

export function SchemaPropertyGridSurface({
  fields,
  syntheticFields,
  schema,
  rootSchema,
  bundledSchema,
  registry,
  catalogResolver,
  documentClassFqn,
  declaringClassAncestryByField,
  initialDocument = {},
  onSubmit,
  onDraftChange,
  submitLabel = "Save instance",
  disabled = false,
  headerSlot,
  depth = 0,
  embedded = false,
}: SchemaPropertyGridSurfaceProps) {
  const plans = useMemo((): FieldPlan[] => {
    if (fields?.length) {
      return [...fields]
        .sort((a, b) => a.fieldName.localeCompare(b.fieldName))
        .map((field) => {
          const ancestry =
            declaringClassAncestryByField?.[field.fieldName] ??
            (documentClassFqn ? [documentClassFqn, field.declaredOnClassName] : [field.declaredOnClassName]);
          const resolved = resolveFieldEditorDetailed(field, schema, {
            bundledSchema,
            declaringClassAncestry: ancestry,
            registry,
          });
          return {
            fieldName: field.fieldName,
            required: field.required,
            editor: resolved.editor,
            catalogTarget: resolved.catalogTarget,
          };
        });
    }
    if (syntheticFields?.length) {
      const bundledRoot = isSchemaRecord(bundledSchema) ? bundledSchema : rootSchema;
      return syntheticFields.map((f) => {
        const prop = propertySchemaFromFlattened(schema, f.fieldName);
        return {
          fieldName: f.fieldName,
          required: f.required,
          editor: parsePropertySchema(prop, f.required, bundledRoot),
          catalogTarget: null,
        };
      });
    }
    return [];
  }, [
    fields,
    syntheticFields,
    schema,
    rootSchema,
    bundledSchema,
    registry,
    documentClassFqn,
    declaringClassAncestryByField,
  ]);

  const [primitiveValues, setPrimitiveValues] = useState<Record<string, string>>(() => initPrimitives(plans, initialDocument));
  const [objectValues, setObjectValues] = useState<Record<string, Record<string, unknown>>>(() =>
    initObjects(plans, initialDocument),
  );
  const [arrayValues, setArrayValues] = useState<Record<string, unknown[]>>(() => initArrays(plans, initialDocument));
  const [schemalessValues, setSchemalessValues] = useState<Record<string, string>>(() =>
    initSchemaless(plans, initialDocument),
  );
  const [dialog, setDialog] = useState<DialogState>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const gridClass = embedded ? "g-schema-property-grid g-schema-property-grid--embedded" : "g-schema-property-grid";

  function buildDocument(): Record<string, unknown> | null {
    const document: Record<string, unknown> = {};
    for (const plan of plans) {
      const { fieldName, required, editor } = plan;
      switch (editor.mode) {
        case "typedMetaClass":
        case "typedDataType":
        case "nestedObject": {
          const val = objectValues[fieldName];
          if (!val || Object.keys(val).length === 0) {
            if (!editor.optional && required) {
              setError(`Field ${fieldName} requires a nested object`);
              return null;
            }
            break;
          }
          if (editor.mode === "nestedObject") {
            const subErr = validateSubSchema(editor.objectSchema, val);
            if (subErr) {
              setError(`${fieldName}: ${subErr}`);
              return null;
            }
          }
          document[fieldName] = val;
          break;
        }
        case "nestedArray": {
          const val = arrayValues[fieldName] ?? [];
          if (val.length === 0) {
            if (!editor.optional && required) {
              setError(`Field ${fieldName} requires at least one array item`);
              return null;
            }
            break;
          }
          document[fieldName] = val;
          break;
        }
        case "schemaless": {
          const raw = schemalessValues[fieldName] ?? "";
          if (raw === "") {
            if (!editor.optional && required) {
              setError(`Field ${fieldName} requires a value (schemaless)`);
              return null;
            }
            break;
          }
          try {
            document[fieldName] = JSON.parse(raw);
          } catch {
            setError(`Field ${fieldName} must be valid JSON`);
            return null;
          }
          break;
        }
        default: {
          const raw = primitiveValues[fieldName] ?? "";
          if (raw === "") {
            if (!editor.optional && required) {
              setError(`Field ${fieldName} is required`);
              return null;
            }
            break;
          }
          document[fieldName] = coercePrimitive(editor, raw);
        }
      }
    }
    if (!embedded && isSchemaRecord(schema)) {
      const validationSchema = isSchemaRecord(bundledSchema) ? bundledSchema : schema;
      const rootErr = validateSubSchema(validationSchema, document);
      if (rootErr) {
        setError(rootErr);
        return null;
      }
    }
    return document;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const document = buildDocument();
    if (!document) return;
    onDraftChange?.(document);
    if (!onSubmit) return;
    setBusy(true);
    try {
      await onSubmit(document);
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  function applyDialogSave(value: Record<string, unknown>) {
    if (!dialog) return;
    if (dialog.kind === "object" || dialog.kind === "catalog") {
      if (dialog.kind === "catalog" && dialog.arrayIndex != null) {
        setArrayValues((prev) => {
          const list = [...(prev[dialog.fieldName] ?? [])];
          if (dialog.isNew) {
            list.push(value);
          } else {
            list[dialog.arrayIndex as number] = value;
          }
          return { ...prev, [dialog.fieldName]: list };
        });
      } else {
        setObjectValues((prev) => ({ ...prev, [dialog.fieldName]: value }));
      }
    } else {
      setArrayValues((prev) => {
        const list = [...(prev[dialog.fieldName] ?? [])];
        if (dialog.isNew) {
          list.push(value);
        } else {
          list[dialog.index] = value;
        }
        return { ...prev, [dialog.fieldName]: list };
      });
    }
    setDialog(null);
  }

  function openCatalogDialog(
    fieldName: string,
    catalogTarget: CatalogRef,
    value: Record<string, unknown>,
    arrayIndex?: number,
    isNew?: boolean,
  ) {
    if (!catalogResolver) {
      setError(`Field ${fieldName} requires catalog resolver for ${catalogTarget.kind}`);
      return;
    }
    setDialog({ kind: "catalog", fieldName, catalogTarget, value, arrayIndex, isNew });
  }

  return (
    <>
      <form onSubmit={handleSubmit} className={`g-meta-field-form ${gridClass}`}>
        {headerSlot}
        {!embedded ? (
          <p className="g-host-home__lead">
            Hierarchy-driven property grid: field types resolve through Meta classes and wf.data_type, with nested
            sub-grids loaded from catalog APIs. Schemaless JSON only when a type is genuinely untyped.
          </p>
        ) : null}
        {plans.map((plan) => renderRow(plan))}
        {onSubmit ? (
          <button type="submit" className="g-host-button" disabled={disabled || busy}>
            {submitLabel}
          </button>
        ) : null}
        {error ? <p role="alert">{error}</p> : null}
      </form>
      {dialog?.kind === "catalog" && catalogResolver ? (
        <CatalogNestedSchemaDialog
          title={
            dialog.isNew
              ? `Add ${dialog.fieldName}[${dialog.arrayIndex ?? ""}]`
              : dialog.arrayIndex != null
                ? `Edit ${dialog.fieldName}[${dialog.arrayIndex}]`
                : `Edit ${dialog.fieldName}`
          }
          catalogTarget={dialog.catalogTarget}
          catalogResolver={catalogResolver}
          registry={registry ?? DEFAULT_HIERARCHY_REGISTRY}
          bundledSchema={bundledSchema}
          initialValue={dialog.value}
          depth={depth + 1}
          onSave={applyDialogSave}
          onCancel={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "object" ? (
        <InlineObjectSchemaDialog
          title={`Edit ${dialog.fieldName}`}
          objectSchema={dialog.schema}
          initialValue={dialog.value}
          onSave={applyDialogSave}
          onCancel={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "array-item" ? (
        <NestedSchemaDialog
          title={`${dialog.isNew ? "Add" : "Edit"} ${dialog.fieldName}[${dialog.index}]`}
          objectSchema={dialog.schema}
          rootSchema={isSchemaRecord(bundledSchema) ? bundledSchema : rootSchema}
          bundledSchema={bundledSchema}
          registry={registry ?? DEFAULT_HIERARCHY_REGISTRY}
          catalogResolver={catalogResolver}
          initialValue={dialog.value}
          depth={depth + 1}
          onSave={applyDialogSave}
          onCancel={() => setDialog(null)}
        />
      ) : null}
    </>
  );

  function renderRow(plan: FieldPlan) {
    const { fieldName, editor } = plan;
    const id = `meta-field-${fieldName}`;
    if (editor.mode === "typedMetaClass" || editor.mode === "typedDataType") {
      const val = objectValues[fieldName];
      const target: CatalogRef =
        editor.mode === "typedMetaClass"
          ? { kind: "metaClass", className: editor.className }
          : { kind: "dataType", typeName: editor.typeName };
      return (
        <p key={fieldName} className="g-meta-field-row">
          <span>
            {fieldName}
            {plan.required ? " *" : ""}
          </span>
          <button
            type="button"
            className="g-host-button"
            disabled={disabled || busy}
            onClick={() => {
              const prop = propertySchemaFromFlattened(schema, fieldName);
              const root = isSchemaRecord(bundledSchema) ? bundledSchema : rootSchema;
              const node = isSchemaRecord(prop) ? resolveSchemaNode(prop, root) ?? prop : null;
              if (editor.mode === "typedDataType" && node && isSchemaRecord(node.properties)) {
                setDialog({ kind: "object", fieldName, schema: node, value: val ?? {} });
                return;
              }
              openCatalogDialog(fieldName, target, val ?? {});
            }}
            aria-label={`Edit nested ${fieldName}`}
          >
            Edit nested ({summaryObject(val)})
          </button>
        </p>
      );
    }
    if (editor.mode === "nestedObject") {
      const val = objectValues[fieldName];
      return (
        <p key={fieldName} className="g-meta-field-row">
          <span>
            {fieldName}
            {plan.required ? " *" : ""}
          </span>
          <button
            type="button"
            className="g-host-button"
            disabled={disabled || busy}
            onClick={() =>
              setDialog({
                kind: "object",
                fieldName,
                schema: editor.objectSchema,
                value: val ?? {},
              })
            }
            aria-label={`Edit nested ${fieldName}`}
          >
            Edit nested ({summaryObject(val)})
          </button>
        </p>
      );
    }
    if (editor.mode === "nestedArray" && editor.itemsAreObject) {
      const items = (arrayValues[fieldName] ?? []) as Record<string, unknown>[];
      const itemCatalog = editor.itemsCatalogRef;
      return (
        <p key={fieldName} className="g-meta-field-row g-meta-field-row--array">
          <span>
            {fieldName}
            {plan.required ? " *" : ""}
          </span>
          <ul className="g-schema-array-list">
            {items.map((item, index) => (
              <li key={index}>
                <span>{summaryObject(item)}</span>
                <button
                  type="button"
                  className="g-host-button"
                  onClick={() =>
                    itemCatalog && itemCatalog.kind !== "inline" && catalogResolver
                      ? openCatalogDialog(fieldName, itemCatalog, item, index, false)
                      : setDialog({
                          kind: "array-item",
                          fieldName,
                          index,
                          schema: editor.itemsSchema,
                          value: item,
                          isNew: false,
                        })
                  }
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="g-host-button"
                  onClick={() =>
                    setArrayValues((prev) => ({
                      ...prev,
                      [fieldName]: (prev[fieldName] ?? []).filter((_, i) => i !== index),
                    }))
                  }
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="g-host-button"
            disabled={depth >= SCHEMA_PROPERTY_GRID_MAX_DEPTH}
            onClick={() =>
              itemCatalog && itemCatalog.kind !== "inline" && catalogResolver
                ? openCatalogDialog(fieldName, itemCatalog, {}, items.length, true)
                : setDialog({
                    kind: "array-item",
                    fieldName,
                    index: items.length,
                    schema: editor.itemsSchema,
                    value: {},
                    isNew: true,
                  })
            }
          >
            Add row
          </button>
        </p>
      );
    }
    if (editor.mode === "nestedArray" && !editor.itemsAreObject) {
      return (
        <p key={fieldName} className="g-meta-field-row">
          <label htmlFor={id}>
            {fieldName}
            {plan.required ? " *" : ""}
          </label>
          <input
            id={id}
            className="g-host-input"
            value={(arrayValues[fieldName] ?? []).map(String).join(", ")}
            disabled={disabled || busy}
            onChange={(e) => {
              const parts = e.target.value.split(",").map((s) => s.trim()).filter(Boolean);
              const coerced = parts.map((p) =>
                editor.primitiveItemMode === "integer"
                  ? Math.trunc(Number(p))
                  : editor.primitiveItemMode === "number"
                    ? Number(p)
                    : p,
              );
              setArrayValues((prev) => ({ ...prev, [fieldName]: coerced }));
            }}
          />
        </p>
      );
    }
    if (editor.mode === "schemaless") {
      return (
        <p key={fieldName} className="g-meta-field-row">
          <label htmlFor={id}>
            {fieldName} (schemaless JSON)
            {plan.required ? " *" : ""}
          </label>
          <textarea
            id={id}
            rows={3}
            className="g-host-textarea"
            value={schemalessValues[fieldName] ?? ""}
            disabled={disabled || busy}
            onChange={(e) => setSchemalessValues((prev) => ({ ...prev, [fieldName]: e.target.value }))}
          />
          <span className="g-host-home__lead">{editor.reason}</span>
        </p>
      );
    }
    return renderPrimitiveRow(plan);
  }

  function renderPrimitiveRow(plan: FieldPlan) {
    const { fieldName, editor } = plan;
    const id = `meta-field-${fieldName}`;
    if (editor.mode === "boolean") {
      return (
        <p key={fieldName} className="g-meta-field-row">
          <label htmlFor={id}>
            {fieldName}
            {plan.required ? " *" : ""}
          </label>
          <input
            id={id}
            type="checkbox"
            checked={primitiveValues[fieldName] === "true"}
            disabled={disabled || busy}
            onChange={(e) =>
              setPrimitiveValues((prev) => ({ ...prev, [fieldName]: e.target.checked ? "true" : "false" }))
            }
          />
        </p>
      );
    }
    if (editor.mode === "string" && editor.enumValues) {
      return (
        <p key={fieldName} className="g-meta-field-row">
          <label htmlFor={id}>
            {fieldName}
            {plan.required ? " *" : ""}
          </label>
          <select
            id={id}
            className="g-host-input"
            value={primitiveValues[fieldName] ?? ""}
            disabled={disabled || busy}
            onChange={(e) => setPrimitiveValues((prev) => ({ ...prev, [fieldName]: e.target.value }))}
          >
            <option value="">—</option>
            {editor.enumValues.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </p>
      );
    }
    return (
      <p key={fieldName} className="g-meta-field-row">
        <label htmlFor={id}>
          {fieldName}
          {plan.required ? " *" : ""}
        </label>
        <input
          id={id}
          type={editor.mode === "integer" || editor.mode === "number" ? "number" : "text"}
          className="g-host-input"
          value={primitiveValues[fieldName] ?? ""}
          disabled={disabled || busy}
          onChange={(e) => setPrimitiveValues((prev) => ({ ...prev, [fieldName]: e.target.value }))}
        />
      </p>
    );
  }
}

function coercePrimitive(editor: ParsedFieldEditor, raw: string): unknown {
  if (editor.mode === "boolean") return raw === "true";
  if (editor.mode === "integer") return Math.trunc(Number(raw));
  if (editor.mode === "number") return Number(raw);
  return raw;
}

function InlineObjectSchemaDialog({
  title,
  objectSchema,
  initialValue,
  onSave,
  onCancel,
}: {
  title: string;
  objectSchema: Record<string, unknown>;
  initialValue: Record<string, unknown>;
  onSave: (value: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const props = objectSchema.properties;
  const fieldNames = isSchemaRecord(props)
    ? Object.keys(props).sort()
    : [];
  const required = new Set(
    Array.isArray(objectSchema.required)
      ? objectSchema.required.filter((n): n is string => typeof n === "string")
      : [],
  );
  const [draft, setDraft] = useState<Record<string, string>>(() => {
    const next: Record<string, string> = {};
    for (const name of fieldNames) {
      const raw = initialValue[name];
      next[name] = raw == null ? "" : String(raw);
    }
    return next;
  });

  return createPortal(
    <div className="g-schema-dialog-backdrop" data-testid="schema-nested-dialog">
      <button type="button" className="g-schema-dialog-backdrop__hit" aria-label="Close dialog" onClick={onCancel} />
      <div className="g-schema-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h3 id={titleId}>{title}</h3>
        {fieldNames.map((name) => (
          <p key={name} className="g-meta-field-row">
            <label htmlFor={`inline-${name}`}>
              {name}
              {required.has(name) ? " *" : ""}
            </label>
            <input
              id={`inline-${name}`}
              className="g-host-input"
              value={draft[name] ?? ""}
              onChange={(e) => setDraft((prev) => ({ ...prev, [name]: e.target.value }))}
            />
          </p>
        ))}
        <button
          type="button"
          className="g-host-button"
          onClick={() => {
            const document: Record<string, unknown> = {};
            for (const name of fieldNames) {
              const raw = draft[name] ?? "";
              if (raw !== "") document[name] = raw;
            }
            onSave(document);
          }}
        >
          Save
        </button>
        <button type="button" className="g-host-button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>,
    document.body,
  );
}

function validateSubSchema(schema: Record<string, unknown>, document: Record<string, unknown>): string | null {
  try {
    const validate = compileSchemaValidator(schema);
    const ok = validate(document);
    return ok ? null : validationMessage(validate.errors);
  } catch (e) {
    return e instanceof Error ? e.message : "schema validation error";
  }
}

function initPrimitives(plans: FieldPlan[], doc: Record<string, unknown>): Record<string, string> {
  const next: Record<string, string> = {};
  for (const plan of plans) {
    const raw = doc[plan.fieldName];
    if (
      plan.editor.mode === "nestedObject" ||
      plan.editor.mode === "nestedArray" ||
      plan.editor.mode === "typedMetaClass" ||
      plan.editor.mode === "typedDataType" ||
      plan.editor.mode === "schemaless"
    ) {
      continue;
    }
    next[plan.fieldName] = raw == null ? "" : String(raw);
  }
  return next;
}

function initObjects(plans: FieldPlan[], doc: Record<string, unknown>): Record<string, Record<string, unknown>> {
  const next: Record<string, Record<string, unknown>> = {};
  for (const plan of plans) {
    if (
      plan.editor.mode !== "nestedObject" &&
      plan.editor.mode !== "typedMetaClass" &&
      plan.editor.mode !== "typedDataType"
    ) {
      continue;
    }
    const raw = doc[plan.fieldName];
    next[plan.fieldName] = isSchemaRecord(raw) ? raw : {};
  }
  return next;
}

function initArrays(plans: FieldPlan[], doc: Record<string, unknown>): Record<string, unknown[]> {
  const next: Record<string, unknown[]> = {};
  for (const plan of plans) {
    if (plan.editor.mode !== "nestedArray") continue;
    const raw = doc[plan.fieldName];
    next[plan.fieldName] = Array.isArray(raw) ? raw : [];
  }
  return next;
}

function initSchemaless(plans: FieldPlan[], doc: Record<string, unknown>): Record<string, string> {
  const next: Record<string, string> = {};
  for (const plan of plans) {
    if (plan.editor.mode !== "schemaless") continue;
    const raw = doc[plan.fieldName];
    next[plan.fieldName] = raw == null ? "" : JSON.stringify(raw);
  }
  return next;
}
