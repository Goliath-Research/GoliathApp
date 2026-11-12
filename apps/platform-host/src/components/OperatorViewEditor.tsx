"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { MetaClassListRow } from "@goliath/platform-ui";
import { MetaClassHierarchyList } from "@goliath/platform-ui";
import {
  DEFAULT_VIEW_DEFINITION,
  buildSemanticRunParams,
  parseViewDefinition,
  type ColumnFormat,
  type FilterOperator,
  type ViewColumn,
  type ViewDefinition,
  type ViewFilter,
  type ViewSort,
  type ViewVisibility,
  type VisualizationType,
} from "@/lib/operator-view-definition";
import { ViewVisualizationPreview } from "@/components/ViewVisualizationPreview";

type CatalogEntry = {
  requestCode: string;
  displayName: string;
  namespace: string;
  entityCode: string;
};

type SavedViewSummary = {
  viewId: number;
  title: string;
  description: string;
  semanticRequestCode: string | null;
  metaClassName: string | null;
  visibility: string;
};

type SourceField = { field: string; label: string; jsonType: string };

type Props = {
  catalog: CatalogEntry[];
  metaClasses: MetaClassListRow[];
  initialViews: SavedViewSummary[];
  initialViewId?: number;
};

const FILTER_OPS: FilterOperator[] = [
  "eq",
  "neq",
  "contains",
  "starts_with",
  "gt",
  "gte",
  "lt",
  "lte",
  "is_null",
];

const VIZ_TYPES: VisualizationType[] = ["table", "bar", "line", "pie", "kpi"];

const FORMATS: ColumnFormat[] = ["text", "number", "date", "currency"];

export function OperatorViewEditor({ catalog, metaClasses, initialViews, initialViewId }: Props) {
  const [views, setViews] = useState(initialViews);
  const [selectedId, setSelectedId] = useState<number | "new">(initialViewId ?? "new");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [sourceKind, setSourceKind] = useState<"semantic" | "meta">("semantic");
  const [requestCode, setRequestCode] = useState(catalog[0]?.requestCode ?? "");
  const [metaClass, setMetaClass] = useState(metaClasses[0]?.className ?? "platform/Document");
  const [definition, setDefinition] = useState<ViewDefinition>({ ...DEFAULT_VIEW_DEFINITION });
  const [visibility, setVisibility] = useState<ViewVisibility>("scope");
  const [sourceFields, setSourceFields] = useState<SourceField[]>([]);
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  const hierarchyClasses = useMemo(() => metaClasses, [metaClasses]);

  const refreshViews = useCallback(async () => {
    const res = await fetch("/api/portal/views", { credentials: "same-origin" });
    if (!res.ok) return;
    const body = (await res.json()) as { views: SavedViewSummary[] };
    setViews(body.views);
  }, []);

  const loadSourceFields = useCallback(async () => {
    const params = new URLSearchParams();
    if (sourceKind === "semantic" && requestCode) {
      params.set("semanticRequestCode", requestCode);
    } else if (sourceKind === "meta" && metaClass) {
      params.set("metaClassName", metaClass);
    } else {
      setSourceFields([]);
      return;
    }
    const res = await fetch(`/api/portal/views/source-fields?${params}`, { credentials: "same-origin" });
    if (!res.ok) {
      setSourceFields([]);
      return;
    }
    const body = (await res.json()) as { fields: SourceField[] };
    setSourceFields(body.fields);
  }, [sourceKind, requestCode, metaClass]);

  const runPreview = useCallback(async () => {
    setStatus(null);
    if (sourceKind === "semantic" && requestCode) {
      const params = buildSemanticRunParams(definition);
      const res = await fetch("/api/portal/semantic/run", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ requestCode, params }),
      });
      if (!res.ok) {
        setStatus("Preview failed");
        setPreviewRows([]);
        return;
      }
      const body = (await res.json()) as { rows: Record<string, unknown>[] };
      setPreviewRows(body.rows);
    } else if (sourceKind === "meta" && metaClass) {
      const res = await fetch(`/api/meta/classes/${encodeURIComponent(metaClass)}/objects`, {
        credentials: "same-origin",
      });
      if (!res.ok) {
        setStatus("Preview failed");
        setPreviewRows([]);
        return;
      }
      const body = (await res.json()) as {
        objects: Array<{ document: Record<string, unknown> }>;
      };
      const docs = body.objects.slice(0, definition.limit).map((o) => flattenDocument(o.document));
      setPreviewRows(docs);
    }
  }, [sourceKind, requestCode, metaClass, definition]);

  const loadView = useCallback(
    async (viewId: number) => {
      const res = await fetch(`/api/portal/views/${viewId}`, { credentials: "same-origin" });
      if (!res.ok) {
        setStatus("Could not load view");
        return;
      }
      const body = (await res.json()) as {
        view: {
          title: string;
          description: string;
          semanticRequestCode: string | null;
          metaClassName: string | null;
          paramsJson: Record<string, unknown>;
          visibility: string;
        };
      };
      const v = body.view;
      setTitle(v.title);
      setDescription(v.description);
      if (v.semanticRequestCode) {
        setSourceKind("semantic");
        setRequestCode(v.semanticRequestCode);
      } else if (v.metaClassName) {
        setSourceKind("meta");
        setMetaClass(v.metaClassName);
      }
      setDefinition(parseViewDefinition(v.paramsJson));
      setVisibility(
        v.visibility === "organization" || v.visibility === "private" ? v.visibility : "scope",
      );
      setDirty(false);
    },
    [],
  );

  useEffect(() => {
    void loadSourceFields();
  }, [loadSourceFields]);

  useEffect(() => {
    if (selectedId === "new") {
      setTitle("");
      setDescription("");
      setDefinition({ ...DEFAULT_VIEW_DEFINITION });
      setVisibility("scope");
      setDirty(false);
      return;
    }
    void loadView(selectedId);
  }, [selectedId, loadView]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      void runPreview();
    }, 400);
    return () => window.clearTimeout(t);
  }, [runPreview, definition, sourceKind, requestCode, metaClass]);

  function markDirty() {
    setDirty(true);
  }

  function updateDefinition(patch: Partial<ViewDefinition>) {
    setDefinition((d) => ({ ...d, ...patch }));
    markDirty();
  }

  function addColumn(field: string) {
    if (definition.columns.some((c) => c.field === field)) return;
    const col: ViewColumn = { field, label: field.replace(/_/g, " "), format: "text" };
    updateDefinition({ columns: [...definition.columns, col] });
  }

  function addFilter() {
    const field = sourceFields[0]?.field ?? "id";
    const f: ViewFilter = { field, operator: "eq", value: "" };
    updateDefinition({ filters: [...definition.filters, f] });
  }

  function addSort() {
    const field = sourceFields[0]?.field ?? "id";
    const s: ViewSort = { field, direction: "asc" };
    updateDefinition({ sort: [...definition.sort, s] });
  }

  async function persist(saveAs: boolean) {
    setStatus(null);
    const payload = {
      viewId: saveAs || selectedId === "new" ? undefined : selectedId,
      title: title.trim(),
      description: description.trim(),
      semanticRequestCode: sourceKind === "semantic" ? requestCode : null,
      metaClassName: sourceKind === "meta" ? metaClass : null,
      paramsJson: definition,
      visibility,
    };
    const res = await fetch("/api/portal/views", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      setStatus("Save failed");
      return;
    }
    const body = (await res.json()) as { viewId: number };
    setStatus(saveAs ? "Saved as new view" : "View saved");
    setSelectedId(body.viewId);
    setDirty(false);
    await refreshViews();
  }

  async function removeView() {
    if (selectedId === "new") return;
    if (!window.confirm("Delete this view?")) return;
    const res = await fetch(`/api/portal/views/${selectedId}`, {
      method: "DELETE",
      credentials: "same-origin",
    });
    if (!res.ok) {
      setStatus("Delete failed");
      return;
    }
    setSelectedId("new");
    await refreshViews();
    setStatus("View deleted");
  }

  return (
    <div className="g-portal-views g-portal-view-editor">
      <section aria-labelledby="view-picker-heading">
        <h3 id="view-picker-heading">Views in this scope</h3>
        <div className="g-portal-view-editor__toolbar">
          <button
            type="button"
            className="g-host-button"
            aria-pressed={selectedId === "new"}
            onClick={() => setSelectedId("new")}
          >
            New view
          </button>
          <ul className="g-operator-nav g-portal-view-editor__view-list">
            {views.map((v) => (
              <li key={v.viewId}>
                <button
                  type="button"
                  className="g-host-button"
                  aria-pressed={selectedId === v.viewId}
                  onClick={() => setSelectedId(v.viewId)}
                >
                  {v.title}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section aria-labelledby="view-editor-heading" className="g-portal-view-editor__main">
        <h3 id="view-editor-heading">View editor</h3>
        <p className="g-host-home__lead">
          Configure columns, filters, sort, and visualization with typed controls. Changes preview live below.
        </p>

        <div className="g-portal-view-form g-portal-view-editor__form">
          <label>
            Title
            <input
              type="text"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                markDirty();
              }}
              required
            />
          </label>
          <label>
            Description
            <input
              type="text"
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
                markDirty();
              }}
            />
          </label>
          <label>
            Visibility
            <select
              value={visibility}
              onChange={(e) => {
                setVisibility(e.target.value as ViewVisibility);
                markDirty();
              }}
            >
              <option value="scope">Everyone in this organization scope</option>
              <option value="organization">All scopes in organization</option>
              <option value="private">Only me</option>
            </select>
          </label>

          <fieldset>
            <legend>Data source</legend>
            <label>
              <input
                type="radio"
                name="source"
                checked={sourceKind === "semantic"}
                onChange={() => {
                  setSourceKind("semantic");
                  markDirty();
                }}
              />
              Semantic request
            </label>
            <label>
              <input
                type="radio"
                name="source"
                checked={sourceKind === "meta"}
                onChange={() => {
                  setSourceKind("meta");
                  markDirty();
                }}
              />
              Meta class
            </label>
          </fieldset>

          {sourceKind === "semantic" ? (
            <label>
              Semantic request
              <select
                value={requestCode}
                onChange={(e) => {
                  setRequestCode(e.target.value);
                  markDirty();
                }}
              >
                {catalog.map((c) => (
                  <option key={c.requestCode} value={c.requestCode}>
                    {c.displayName} ({c.requestCode})
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="g-portal-view-editor__meta-picker">
              <label>
                Selected Meta class
                <input type="text" readOnly value={metaClass} aria-readonly />
              </label>
              <MetaClassHierarchyList
                classes={hierarchyClasses}
                selectedClassName={metaClass}
                semanticHighlight="platform/"
              />
              <ul className="g-operator-nav">
                {metaClasses.map((row) => (
                  <li key={row.classId}>
                    <button
                      type="button"
                      className="g-host-button"
                      aria-pressed={metaClass === row.className}
                      onClick={() => {
                        setMetaClass(row.className);
                        markDirty();
                      }}
                    >
                      Use {row.className}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <fieldset>
            <legend>Columns</legend>
            <ul className="g-portal-view-editor__column-list">
              {definition.columns.map((col, idx) => (
                <li key={col.field}>
                  <span>{col.field}</span>
                  <input
                    type="text"
                    aria-label={`Label for ${col.field}`}
                    value={col.label}
                    onChange={(e) => {
                      const next = [...definition.columns];
                      next[idx] = { ...col, label: e.target.value };
                      updateDefinition({ columns: next });
                    }}
                  />
                  <select
                    aria-label={`Format for ${col.field}`}
                    value={col.format ?? "text"}
                    onChange={(e) => {
                      const next = [...definition.columns];
                      next[idx] = { ...col, format: e.target.value as ColumnFormat };
                      updateDefinition({ columns: next });
                    }}
                  >
                    {FORMATS.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="g-host-button"
                    onClick={() =>
                      updateDefinition({
                        columns: definition.columns.filter((c) => c.field !== col.field),
                      })
                    }
                  >
                    Remove
                  </button>
                  <button
                    type="button"
                    className="g-host-button"
                    disabled={idx === 0}
                    onClick={() => {
                      const next = [...definition.columns];
                      const tmp = next[idx - 1]!;
                      next[idx - 1] = next[idx]!;
                      next[idx] = tmp;
                      updateDefinition({ columns: next });
                    }}
                  >
                    Up
                  </button>
                  <button
                    type="button"
                    className="g-host-button"
                    disabled={idx === definition.columns.length - 1}
                    onClick={() => {
                      const next = [...definition.columns];
                      const tmp = next[idx + 1]!;
                      next[idx + 1] = next[idx]!;
                      next[idx] = tmp;
                      updateDefinition({ columns: next });
                    }}
                  >
                    Down
                  </button>
                </li>
              ))}
            </ul>
            <label>
              Add field
              <select
                defaultValue=""
                onChange={(e) => {
                  if (e.target.value) addColumn(e.target.value);
                  e.target.value = "";
                }}
              >
                <option value="">Choose field…</option>
                {sourceFields.map((f) => (
                  <option key={f.field} value={f.field}>
                    {f.label} ({f.jsonType})
                  </option>
                ))}
              </select>
            </label>
          </fieldset>

          <fieldset>
            <legend>Filters</legend>
            {definition.filters.map((filt, idx) => (
              <div key={idx} className="g-portal-view-editor__filter-row">
                <select
                  value={filt.field}
                  onChange={(e) => {
                    const next = [...definition.filters];
                    next[idx] = { ...filt, field: e.target.value };
                    updateDefinition({ filters: next });
                  }}
                >
                  {sourceFields.map((f) => (
                    <option key={f.field} value={f.field}>
                      {f.field}
                    </option>
                  ))}
                </select>
                <select
                  value={filt.operator}
                  onChange={(e) => {
                    const next = [...definition.filters];
                    next[idx] = { ...filt, operator: e.target.value as FilterOperator };
                    updateDefinition({ filters: next });
                  }}
                >
                  {FILTER_OPS.map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
                {filt.operator !== "is_null" ? (
                  <input
                    type="text"
                    aria-label="Filter value"
                    value={filt.value == null ? "" : String(filt.value)}
                    onChange={(e) => {
                      const next = [...definition.filters];
                      next[idx] = { ...filt, value: e.target.value };
                      updateDefinition({ filters: next });
                    }}
                  />
                ) : null}
                <button
                  type="button"
                  className="g-host-button"
                  onClick={() =>
                    updateDefinition({ filters: definition.filters.filter((_, i) => i !== idx) })
                  }
                >
                  Remove
                </button>
              </div>
            ))}
            <button type="button" className="g-host-button" onClick={addFilter}>
              Add filter
            </button>
          </fieldset>

          <fieldset>
            <legend>Sort</legend>
            {definition.sort.map((s, idx) => (
              <div key={idx} className="g-portal-view-editor__filter-row">
                <select
                  value={s.field}
                  onChange={(e) => {
                    const next = [...definition.sort];
                    next[idx] = { ...s, field: e.target.value };
                    updateDefinition({ sort: next });
                  }}
                >
                  {sourceFields.map((f) => (
                    <option key={f.field} value={f.field}>
                      {f.field}
                    </option>
                  ))}
                </select>
                <select
                  value={s.direction}
                  onChange={(e) => {
                    const next = [...definition.sort];
                    next[idx] = { ...s, direction: e.target.value as "asc" | "desc" };
                    updateDefinition({ sort: next });
                  }}
                >
                  <option value="asc">Ascending</option>
                  <option value="desc">Descending</option>
                </select>
                <button
                  type="button"
                  className="g-host-button"
                  onClick={() => updateDefinition({ sort: definition.sort.filter((_, i) => i !== idx) })}
                >
                  Remove
                </button>
              </div>
            ))}
            <button type="button" className="g-host-button" onClick={addSort}>
              Add sort
            </button>
          </fieldset>

          <label>
            Row limit
            <input
              type="number"
              min={1}
              max={500}
              value={definition.limit}
              onChange={(e) => updateDefinition({ limit: Number(e.target.value) || 50 })}
            />
          </label>

          <fieldset>
            <legend>Group by</legend>
            <select
              multiple
              size={Math.min(6, Math.max(3, sourceFields.length))}
              value={definition.groupBy}
              onChange={(e) => {
                const selected = Array.from(e.target.selectedOptions).map((o) => o.value);
                updateDefinition({ groupBy: selected });
              }}
            >
              {sourceFields.map((f) => (
                <option key={f.field} value={f.field}>
                  {f.field}
                </option>
              ))}
            </select>
          </fieldset>

          <fieldset>
            <legend>Visualization</legend>
            <label>
              Chart type
              <select
                value={definition.visualization.type}
                onChange={(e) =>
                  updateDefinition({
                    visualization: {
                      ...definition.visualization,
                      type: e.target.value as VisualizationType,
                    },
                  })
                }
              >
                {VIZ_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            {definition.visualization.type !== "table" ? (
              <>
                <label>
                  Category / X axis field
                  <select
                    value={definition.visualization.categoryField ?? ""}
                    onChange={(e) =>
                      updateDefinition({
                        visualization: {
                          ...definition.visualization,
                          categoryField: e.target.value || undefined,
                        },
                      })
                    }
                  >
                    <option value="">Auto</option>
                    {sourceFields.map((f) => (
                      <option key={f.field} value={f.field}>
                        {f.field}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Value / Y axis field
                  <select
                    value={definition.visualization.valueField ?? ""}
                    onChange={(e) =>
                      updateDefinition({
                        visualization: {
                          ...definition.visualization,
                          valueField: e.target.value || undefined,
                        },
                      })
                    }
                  >
                    <option value="">Auto</option>
                    {sourceFields.map((f) => (
                      <option key={f.field} value={f.field}>
                        {f.field}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            ) : null}
          </fieldset>

          <div className="g-portal-view-editor__actions">
            <button
              type="button"
              className="g-host-button"
              disabled={!title.trim() || (!dirty && selectedId !== "new")}
              onClick={() => void persist(false)}
            >
              Save
            </button>
            <button
              type="button"
              className="g-host-button"
              disabled={!title.trim()}
              onClick={() => void persist(true)}
            >
              Save as new
            </button>
            <button
              type="button"
              className="g-host-button"
              disabled={selectedId === "new"}
              onClick={() => void removeView()}
            >
              Delete
            </button>
            <button type="button" className="g-host-button" onClick={() => void runPreview()}>
              Refresh preview
            </button>
          </div>
          {status ? <p role="status">{status}</p> : null}
        </div>
      </section>

      <section aria-labelledby="view-live-preview-heading">
        <h3 id="view-live-preview-heading">Live preview</h3>
        <ViewVisualizationPreview definition={definition} rows={previewRows} caption={title || "Preview"} />
      </section>
    </div>
  );
}

function flattenDocument(doc: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(doc)) {
    if (value != null && typeof value === "object" && !Array.isArray(value)) {
      for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
        out[`${key}.${k}`] = v;
      }
    } else {
      out[key] = value;
    }
  }
  return out;
}
