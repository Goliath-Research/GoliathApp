"use client";

import type { MetaClassField } from "@goliath/client";
import type { FormEvent, KeyboardEvent, MutableRefObject, ReactNode } from "react";
import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import {
  isSchemaRecord,
  type SyntheticSchemaField,
  SCHEMA_PROPERTY_GRID_MAX_DEPTH,
} from "./jsonSchema.js";
import type { CatalogRef } from "./catalogRef.js";
import {
  PropertyInspectorDialogHost,
  type InspectorDialogRequest,
} from "./PropertyInspectorDialogHost.js";
import { syntheticFieldsFromSchema } from "./jsonSchema.js";
import { resolveFieldRowIcon } from "./resolveFieldRowIcon.js";
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
  /** When set, updated each commit with a snapshot builder for modal OK handlers. */
  commitSnapshotRef?: MutableRefObject<(() => Record<string, unknown>) | undefined>;
};

type FieldPlan = {
  fieldName: string;
  required: boolean;
  editor: ParsedFieldEditor;
  catalogTarget: CatalogRef | null;
};

function inspectorBreadcrumb(base: readonly string[], ...tail: string[]): string[] {
  return [...base, ...tail];
}

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
  commitSnapshotRef,
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
  const [dialog, setDialog] = useState<InspectorDialogRequest>(null);

  const planIdentity = useMemo(
    () => plans.map((p) => `${p.fieldName}:${p.required}:${p.editor.mode}`).join("|"),
    [plans],
  );

  useEffect(() => {
    setPrimitiveValues(initPrimitives(plans, initialDocument));
    setObjectValues(initObjects(plans, initialDocument));
    setArrayValues(initArrays(plans, initialDocument));
  }, [initialDocument, planIdentity, plans]);

  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expandedInline, setExpandedInline] = useState<Set<string>>(() => new Set());
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(() => new Set());
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [focusField, setFocusField] = useState<string | null>(null);

  const fieldByName = useMemo(() => {
    const map = new Map<string, MetaClassField>();
    for (const f of fields ?? []) map.set(f.fieldName, f);
    return map;
  }, [fields]);

  const breadcrumbBase = useMemo(
    () => (documentClassFqn ? [documentClassFqn] : ["Document"]),
    [documentClassFqn],
  );

  const groupedPlans = useMemo(() => {
    const map = new Map<string, FieldPlan[]>();
    for (const plan of plans) {
      const cat = fieldByName.get(plan.fieldName)?.declaredOnClassName ?? "General";
      const list = map.get(cat) ?? [];
      list.push(plan);
      map.set(cat, list);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [plans, fieldByName]);

  const flatFieldOrder = useMemo(() => plans.map((p) => p.fieldName), [plans]);

  const gridClass = embedded ? "g-schema-property-grid g-schema-property-grid--embedded" : "g-schema-property-grid";

  useEffect(() => {
    if (!onDraftChange) return;
    onDraftChange(buildPartialDocument());
  }, [onDraftChange, primitiveValues, objectValues, arrayValues]);

  function buildPartialDocument(): Record<string, unknown> {
    const document: Record<string, unknown> = {};
    for (const plan of plans) {
      const { fieldName, editor } = plan;
      switch (editor.mode) {
        case "typedMetaClass":
        case "typedDataType":
        case "nestedObject": {
          const val = objectValues[fieldName];
          if (val && Object.keys(val).length > 0) document[fieldName] = val;
          break;
        }
        case "nestedArray": {
          const val = arrayValues[fieldName] ?? [];
          if (val.length > 0) document[fieldName] = val;
          break;
        }
        case "schemaless": {
          const val = objectValues[fieldName];
          if (val && Object.keys(val).length > 0) document[fieldName] = val;
          break;
        }
        default: {
          const raw = primitiveValues[fieldName] ?? "";
          if (raw === "") break;
          document[fieldName] = coercePrimitive(editor, raw);
        }
      }
    }
    return document;
  }

  useLayoutEffect(() => {
    if (!commitSnapshotRef) return;
    commitSnapshotRef.current = buildPartialDocument;
  });

  function buildDocument(opts?: { silent?: boolean }): Record<string, unknown> | null {
    const silent = opts?.silent === true;
    const fail = (message: string): null => {
      if (!silent) setError(message);
      return null;
    };
    const hadInitial = (fieldName: string): boolean =>
      Object.prototype.hasOwnProperty.call(initialDocument, fieldName);
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
              return fail(`Field ${fieldName} requires a nested object`);
            }
            if (hadInitial(fieldName)) {
              document[fieldName] = null;
            }
            break;
          }
          if (editor.mode === "nestedObject") {
            const subErr = validateSubSchema(editor.objectSchema, val);
            if (subErr) {
              return fail(`${fieldName}: ${subErr}`);
            }
          }
          document[fieldName] = val;
          break;
        }
        case "nestedArray": {
          const val = arrayValues[fieldName] ?? [];
          if (val.length === 0) {
            if (!editor.optional && required) {
              return fail(`Field ${fieldName} requires at least one array item`);
            }
            if (hadInitial(fieldName)) {
              document[fieldName] = [];
            }
            break;
          }
          document[fieldName] = val;
          break;
        }
        case "schemaless": {
          const val = objectValues[fieldName];
          if (!val || Object.keys(val).length === 0) {
            if (!editor.optional && required) {
              return fail(`Field ${fieldName} requires a nested object`);
            }
            if (hadInitial(fieldName)) {
              document[fieldName] = null;
            }
            break;
          }
          document[fieldName] = val;
          break;
        }
        default: {
          const raw = primitiveValues[fieldName] ?? "";
          if (raw === "") {
            if (!editor.optional && required) {
              return fail(`Field ${fieldName} is required`);
            }
            if (hadInitial(fieldName)) {
              document[fieldName] = null;
            }
            break;
          }
          document[fieldName] = coercePrimitive(editor, raw);
        }
      }
    }
    if (!embedded && isSchemaRecord(schema)) {
      const validationSchema = isSchemaRecord(bundledSchema) ? bundledSchema : schema;
      const forValidation = { ...document };
      for (const key of Object.keys(forValidation)) {
        if (forValidation[key] === null) {
          delete forValidation[key];
        }
      }
      const rootErr = validateSubSchema(validationSchema, forValidation);
      if (rootErr) {
        return fail(rootErr);
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
    if (dialog.kind === "catalog" && dialog.arrayIndex != null) {
      setArrayValues((prev) => {
        const list = [...(prev[dialog.fieldName] ?? [])];
        if (dialog.isNew) list.push(value);
        else list[dialog.arrayIndex as number] = value;
        return { ...prev, [dialog.fieldName]: list };
      });
    } else if (dialog.kind === "catalog" || dialog.kind === "object") {
      setObjectValues((prev) => ({ ...prev, [dialog.fieldName]: value }));
      clearRowError(dialog.fieldName);
    } else if (dialog.kind === "array-item") {
      setArrayValues((prev) => {
        const list = [...(prev[dialog.fieldName] ?? [])];
        if (dialog.isNew) list.push(value);
        else list[dialog.index] = value;
        return { ...prev, [dialog.fieldName]: list };
      });
    }
    setDialog(null);
  }

  function clearRowError(fieldName: string) {
    setRowErrors((prev) => {
      if (!prev[fieldName]) return prev;
      const next = { ...prev };
      delete next[fieldName];
      return next;
    });
  }

  function openCatalogDialog(
    fieldName: string,
    catalogTarget: CatalogRef,
    value: Record<string, unknown>,
    arrayIndex?: number,
    isNew?: boolean,
  ) {
    if (!catalogResolver) {
      setRowErrors((prev) => ({
        ...prev,
        [fieldName]: `Catalog resolver required for ${catalogTarget.kind}`,
      }));
      return;
    }
    const crumb =
      arrayIndex != null
        ? inspectorBreadcrumb(breadcrumbBase, fieldName, String(arrayIndex))
        : inspectorBreadcrumb(breadcrumbBase, fieldName);
    setDialog({ kind: "catalog", fieldName, catalogTarget, value, breadcrumb: crumb, arrayIndex, isNew });
  }

  function openObjectDialog(fieldName: string, objectSchema: Record<string, unknown>, value: Record<string, unknown>) {
    const root = isSchemaRecord(bundledSchema) ? bundledSchema : rootSchema;
    setDialog({
      kind: "object",
      fieldName,
      objectSchema,
      rootSchema: root,
      value,
      breadcrumb: inspectorBreadcrumb(breadcrumbBase, fieldName),
    });
  }

  function openArrayItemDialog(
    fieldName: string,
    objectSchema: Record<string, unknown>,
    value: Record<string, unknown>,
    index: number,
    isNew: boolean,
  ) {
    const root = isSchemaRecord(bundledSchema) ? bundledSchema : rootSchema;
    setDialog({
      kind: "array-item",
      fieldName,
      objectSchema,
      rootSchema: root,
      value,
      index,
      isNew,
      breadcrumb: inspectorBreadcrumb(breadcrumbBase, fieldName, String(index)),
    });
  }

  function toggleInlineExpand(fieldName: string) {
    setExpandedInline((prev) => {
      const next = new Set(prev);
      if (next.has(fieldName)) next.delete(fieldName);
      else next.add(fieldName);
      return next;
    });
  }

  function handleGridKeyDown(e: KeyboardEvent<HTMLTableElement>) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Escape") return;
    if (e.key === "Escape" && focusField) {
      e.preventDefault();
      setFocusField(null);
      return;
    }
    const idx = focusField ? flatFieldOrder.indexOf(focusField) : -1;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = flatFieldOrder[Math.min(idx + 1, flatFieldOrder.length - 1)] ?? flatFieldOrder[0];
      setFocusField(next);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const next = flatFieldOrder[Math.max(idx - 1, 0)];
      setFocusField(next);
    }
  }

  return (
    <>
      <form
        onSubmit={handleSubmit}
        className={`g-meta-field-form ${gridClass}`}
        data-has-catalog-resolver={catalogResolver ? "true" : "false"}
      >
        {headerSlot}
        {!embedded ? (
          <p className="g-host-home__lead">
            Delphi-style property inspector: Meta class hierarchy and wf.data_type drive editors, nesting, and icons.
          </p>
        ) : null}
        <table
          className="g-property-inspector"
          role="grid"
          aria-label="Properties"
          onKeyDown={handleGridKeyDown}
        >
          <thead>
            <tr>
              <th scope="col">Property</th>
              <th scope="col">Value</th>
            </tr>
          </thead>
          <tbody>
            {groupedPlans.map(([category, group]) => {
              const collapsed = collapsedCategories.has(category);
              return (
                <CategorySection
                  key={category}
                  category={category}
                  collapsed={collapsed}
                  onToggle={() =>
                    setCollapsedCategories((prev) => {
                      const next = new Set(prev);
                      if (next.has(category)) next.delete(category);
                      else next.add(category);
                      return next;
                    })
                  }
                >
                  {!collapsed
                    ? group.flatMap((plan) => renderInspectorRows(plan))
                    : null}
                </CategorySection>
              );
            })}
          </tbody>
        </table>
        {onSubmit ? (
          <button type="submit" className="g-host-button" disabled={disabled || busy}>
            {submitLabel}
          </button>
        ) : null}
        {error ? <p role="alert">{error}</p> : null}
        {Object.keys(rowErrors).length > 0 ? (
          <p role="alert" data-testid="property-inspector-row-errors">
            {Object.entries(rowErrors)
              .map(([k, v]) => `${k}: ${v}`)
              .join("; ")}
          </p>
        ) : null}
      </form>
      <PropertyInspectorDialogHost
        request={dialog}
        catalogResolver={catalogResolver}
        registry={registry ?? DEFAULT_HIERARCHY_REGISTRY}
        bundledSchema={bundledSchema}
        depth={depth}
        onCommit={applyDialogSave}
        onDismiss={() => setDialog(null)}
      />
    </>
  );

  function renderInspectorRows(plan: FieldPlan): ReactNode[] {
    const rows: ReactNode[] = [renderInspectorRow(plan)];
    if (expandedInline.has(plan.fieldName)) {
      rows.push(...renderInlineSubRows(plan));
    }
    return rows;
  }

  function renderInspectorRow(plan: FieldPlan): ReactNode {
    return renderRow(plan);
  }

  function renderInlineSubRows(plan: FieldPlan): ReactNode[] {
    const { fieldName, editor } = plan;
    const val = objectValues[fieldName] ?? {};
    if (editor.mode === "nestedObject" && isSchemaRecord(editor.objectSchema)) {
      const childFields = syntheticFieldsFromSchema(
        editor.objectSchema,
        isSchemaRecord(bundledSchema) ? bundledSchema : rootSchema,
      );
      return childFields.map((child) => (
        <tr key={`${fieldName}.${child.fieldName}`} className="g-property-inspector__row g-property-inspector__row--child">
          <td className="g-property-inspector__name">{child.fieldName}</td>
          <td className="g-property-inspector__value">
            <span className="g-property-inspector__summary">{String(val[child.fieldName] ?? "—")}</span>
          </td>
        </tr>
      ));
    }
    return Object.entries(val).map(([key, v]) => (
      <tr key={`${fieldName}.${key}`} className="g-property-inspector__row g-property-inspector__row--child">
        <td className="g-property-inspector__name">{key}</td>
        <td className="g-property-inspector__value">
          <span className="g-property-inspector__summary">{String(v ?? "—")}</span>
        </td>
      </tr>
    ));
  }

  function rowIcon(plan: FieldPlan): string {
    const field = fieldByName.get(plan.fieldName);
    const ancestry =
      declaringClassAncestryByField?.[plan.fieldName] ??
      (documentClassFqn ? [documentClassFqn, field?.declaredOnClassName ?? ""] : [field?.declaredOnClassName ?? ""]);
    return resolveFieldRowIcon(field, plan.editor, plan.catalogTarget, ancestry, registry);
  }

  function inspectorNameCell(plan: FieldPlan, expandable: boolean) {
    const { fieldName } = plan;
    const expanded = expandedInline.has(fieldName);
    return (
      <>
        {expandable ? (
          <button
            type="button"
            className="g-property-inspector__expand"
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse" : "Expand"}
            onClick={() => toggleInlineExpand(fieldName)}
          >
            {expanded ? "−" : "+"}
          </button>
        ) : (
          <span className="g-property-inspector__expand-placeholder" aria-hidden />
        )}
        <span className="g-property-inspector__icon" title={rowIcon(plan)}>
          {rowIcon(plan)}
        </span>
        <span>
          {fieldName}
          {plan.required ? " *" : ""}
        </span>
      </>
    );
  }

  function openNestedEditor(plan: FieldPlan) {
    const { fieldName, editor, catalogTarget } = plan;
    const val = objectValues[fieldName] ?? {};
    if (catalogTarget && catalogTarget.kind !== "inline") {
      openCatalogDialog(fieldName, catalogTarget, val);
      return;
    }
    if (editor.mode === "typedMetaClass") {
      openCatalogDialog(fieldName, { kind: "metaClass", className: editor.className }, val);
      return;
    }
    if (editor.mode === "typedDataType") {
      openCatalogDialog(fieldName, { kind: "dataType", typeName: editor.typeName }, val);
      return;
    }
    if (editor.mode === "nestedObject") {
      openObjectDialog(fieldName, editor.objectSchema, val);
    }
    if (editor.mode === "schemaless") {
      openObjectDialog(fieldName, { type: "object", properties: {} }, val);
    }
  }

  function renderNestedValueRow(plan: FieldPlan, summary: string, expandable = true) {
    const { fieldName } = plan;
    const focused = focusField === fieldName;
    return (
      <tr
        key={fieldName}
        className={`g-property-inspector__row${focused ? " g-property-inspector__row--focused" : ""}`}
        data-testid={`pi-row-${fieldName}`}
        tabIndex={focused ? 0 : -1}
        onFocus={() => setFocusField(fieldName)}
      >
        <td className="g-property-inspector__name">{inspectorNameCell(plan, expandable)}</td>
        <td className="g-property-inspector__value">
          <span className="g-property-inspector__summary">{summary}</span>
          <button
            type="button"
            className="g-property-inspector__ellipsis"
            data-testid={`pi-open-${fieldName}`}
            disabled={disabled}
            aria-label={`Open ${fieldName}`}
            onClick={() => openNestedEditor(plan)}
          >
            Open
          </button>
          {rowErrors[fieldName] ? (
            <span className="g-property-inspector__error" role="alert">
              {rowErrors[fieldName]}
            </span>
          ) : null}
        </td>
      </tr>
    );
  }

  function renderRow(plan: FieldPlan) {
    const { fieldName, editor } = plan;
    if (editor.mode === "typedMetaClass" || editor.mode === "typedDataType") {
      const val = objectValues[fieldName];
      return renderNestedValueRow(plan, summaryObject(val), true);
    }
    if (editor.mode === "nestedObject") {
      const val = objectValues[fieldName];
      return renderNestedValueRow(plan, summaryObject(val), true);
    }
    if (editor.mode === "nestedArray" && editor.itemsAreObject) {
      const items = (arrayValues[fieldName] ?? []) as Record<string, unknown>[];
      const itemCatalog = editor.itemsCatalogRef;
      const focused = focusField === fieldName;
      const moveItem = (from: number, to: number) => {
        if (to < 0 || to >= items.length) return;
        setArrayValues((prev) => {
          const list = [...(prev[fieldName] ?? [])] as Record<string, unknown>[];
          const [row] = list.splice(from, 1);
          list.splice(to, 0, row);
          return { ...prev, [fieldName]: list };
        });
      };
      return (
        <tr
          key={fieldName}
          className={`g-property-inspector__row g-property-inspector__row--array${focused ? " g-property-inspector__row--focused" : ""}`}
          data-testid={`pi-row-${fieldName}`}
          tabIndex={focused ? 0 : -1}
          onFocus={() => setFocusField(fieldName)}
        >
          <td className="g-property-inspector__name">{inspectorNameCell(plan, false)}</td>
          <td className="g-property-inspector__value">
            <ul className="g-schema-array-list">
              {items.map((item, index) => (
                <li key={index}>
                  <span>{summaryObject(item)}</span>
                  <button
                    type="button"
                    className="g-property-inspector__ellipsis"
                    data-testid={`pi-open-${fieldName}-${index}`}
                    aria-label={`Open ${fieldName} item ${index}`}
                    onClick={() =>
                      itemCatalog && itemCatalog.kind !== "inline" && catalogResolver
                        ? openCatalogDialog(fieldName, itemCatalog, item, index, false)
                        : openArrayItemDialog(fieldName, editor.itemsSchema, item, index, false)
                    }
                  >
                    Open
                  </button>
                  <button type="button" className="g-host-button" onClick={() => moveItem(index, index - 1)}>
                    ↑
                  </button>
                  <button type="button" className="g-host-button" onClick={() => moveItem(index, index + 1)}>
                    ↓
                  </button>
                  <button
                    type="button"
                    className="g-host-button"
                    data-testid={`pi-array-remove-${fieldName}-${index}`}
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
              data-testid={`pi-array-add-${fieldName}`}
              disabled={disabled || busy || depth >= SCHEMA_PROPERTY_GRID_MAX_DEPTH}
              onClick={() =>
                itemCatalog && itemCatalog.kind !== "inline" && catalogResolver
                  ? openCatalogDialog(fieldName, itemCatalog, {}, items.length, true)
                  : openArrayItemDialog(fieldName, editor.itemsSchema, {}, items.length, true)
              }
            >
              Add row
            </button>
          </td>
        </tr>
      );
    }
    if (editor.mode === "nestedArray" && !editor.itemsAreObject) {
      const primitiveItems = (arrayValues[fieldName] ?? []) as unknown[];
      const coerceItem = (raw: string): unknown => {
        if (editor.primitiveItemMode === "integer") return Math.trunc(Number(raw));
        if (editor.primitiveItemMode === "number") return Number(raw);
        return raw;
      };
      return (
        <tr key={fieldName} className="g-property-inspector__row" data-testid={`pi-row-${fieldName}`}>
          <td className="g-property-inspector__name">{inspectorNameCell(plan, false)}</td>
          <td className="g-property-inspector__value">
            <ul className="g-schema-array-list">
              {primitiveItems.map((item, index) => (
                <li key={index}>
                  <input
                    className="g-host-input"
                    aria-label={`${fieldName} item ${index}`}
                    value={item == null ? "" : String(item)}
                    disabled={disabled || busy}
                    onChange={(e) =>
                      setArrayValues((prev) => {
                        const list = [...(prev[fieldName] ?? [])];
                        list[index] = coerceItem(e.target.value);
                        return { ...prev, [fieldName]: list };
                      })
                    }
                  />
                  <button
                    type="button"
                    className="g-host-button"
                    data-testid={`pi-array-remove-${fieldName}-${index}`}
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
              data-testid={`pi-array-add-${fieldName}`}
              disabled={disabled || busy}
              onClick={() =>
                setArrayValues((prev) => ({
                  ...prev,
                  [fieldName]: [...(prev[fieldName] ?? []), ""],
                }))
              }
            >
              Add item
            </button>
          </td>
        </tr>
      );
    }
    if (editor.mode === "schemaless") {
      return renderNestedValueRow(
        { ...plan, editor: { mode: "nestedObject", optional: editor.optional, objectSchema: { type: "object", properties: {} } } },
        summaryObject(objectValues[fieldName]),
        true,
      );
    }
    return renderPrimitiveRow(plan);
  }

  function renderPrimitiveRow(plan: FieldPlan) {
    const { fieldName, editor } = plan;
    const id = `meta-field-${fieldName}`;
    if (editor.mode === "boolean") {
      return (
        <tr key={fieldName} className="g-property-inspector__row" data-testid={`pi-row-${fieldName}`}>
          <td className="g-property-inspector__name">{inspectorNameCell(plan, false)}</td>
          <td className="g-property-inspector__value">
            <input
              id={id}
              type="checkbox"
              checked={primitiveValues[fieldName] === "true"}
              disabled={disabled || busy}
              onChange={(e) =>
                setPrimitiveValues((prev) => ({ ...prev, [fieldName]: e.target.checked ? "true" : "false" }))
              }
            />
          </td>
        </tr>
      );
    }
    if (editor.mode === "date") {
      return (
        <tr key={fieldName} className="g-property-inspector__row" data-testid={`pi-row-${fieldName}`}>
          <td className="g-property-inspector__name">{inspectorNameCell(plan, false)}</td>
          <td className="g-property-inspector__value">
            <input
              id={id}
              type={editor.inputType}
              className="g-host-input"
              value={primitiveValues[fieldName] ?? ""}
              disabled={disabled || busy}
              onChange={(e) => setPrimitiveValues((prev) => ({ ...prev, [fieldName]: e.target.value }))}
            />
          </td>
        </tr>
      );
    }
    if (editor.mode === "string" && editor.enumValues) {
      return (
        <tr key={fieldName} className="g-property-inspector__row" data-testid={`pi-row-${fieldName}`}>
          <td className="g-property-inspector__name">{inspectorNameCell(plan, false)}</td>
          <td className="g-property-inspector__value">
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
          </td>
        </tr>
      );
    }
    return (
      <tr key={fieldName} className="g-property-inspector__row" data-testid={`pi-row-${fieldName}`}>
        <td className="g-property-inspector__name">{inspectorNameCell(plan, false)}</td>
        <td className="g-property-inspector__value">
          <input
            id={id}
            type={editor.mode === "integer" || editor.mode === "number" ? "number" : "text"}
            className="g-host-input"
            aria-label={fieldName}
            value={primitiveValues[fieldName] ?? ""}
            disabled={disabled || busy}
            onChange={(e) => {
              setPrimitiveValues((prev) => ({ ...prev, [fieldName]: e.target.value }));
              clearRowError(fieldName);
            }}
            onBlur={() => {
              const raw = primitiveValues[fieldName] ?? "";
              if (raw === "" && !plan.editor.optional && plan.required) {
                setRowErrors((prev) => ({ ...prev, [fieldName]: "Required" }));
              }
            }}
          />
          {rowErrors[fieldName] ? (
            <span className="g-property-inspector__error" role="alert">
              {rowErrors[fieldName]}
            </span>
          ) : null}
        </td>
      </tr>
    );
  }
}

function CategorySection({
  category,
  collapsed,
  onToggle,
  children,
}: {
  category: string;
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <>
      <tr className="g-property-inspector__category">
        <td colSpan={2}>
          <button type="button" className="g-property-inspector__category-toggle" onClick={onToggle}>
            {collapsed ? "▸" : "▾"} {category}
          </button>
        </td>
      </tr>
      {children}
    </>
  );
}

function coercePrimitive(editor: ParsedFieldEditor, raw: string): unknown {
  if (editor.mode === "boolean") return raw === "true";
  if (editor.mode === "integer") return Math.trunc(Number(raw));
  if (editor.mode === "number") return Number(raw);
  if (editor.mode === "date") return coerceDateInputValue(raw, editor.inputType);
  return raw;
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
    if (plan.editor.mode === "date") {
      next[plan.fieldName] = formatDateInputValue(raw, plan.editor.inputType);
    } else {
      next[plan.fieldName] = raw == null ? "" : String(raw);
    }
  }
  return next;
}

function formatDateInputValue(raw: unknown, inputType: "date" | "datetime-local"): string {
  if (raw == null || raw === "") return "";
  const text = typeof raw === "number" ? new Date(raw).toISOString() : String(raw);
  if (inputType === "date") {
    const match = /^(\d{4}-\d{2}-\d{2})/.exec(text);
    return match ? match[1] : text.slice(0, 10);
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

function coerceDateInputValue(raw: string, inputType: "date" | "datetime-local"): string {
  if (raw === "") return raw;
  if (inputType === "date") return raw;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toISOString();
}

function initObjects(plans: FieldPlan[], doc: Record<string, unknown>): Record<string, Record<string, unknown>> {
  const next: Record<string, Record<string, unknown>> = {};
  for (const plan of plans) {
    if (
      plan.editor.mode !== "nestedObject" &&
      plan.editor.mode !== "typedMetaClass" &&
      plan.editor.mode !== "typedDataType" &&
      plan.editor.mode !== "schemaless"
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

