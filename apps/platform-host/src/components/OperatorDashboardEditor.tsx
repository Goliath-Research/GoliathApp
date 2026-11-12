"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  applyViewFilters,
  buildSemanticRunParams,
  DEFAULT_VIEW_DEFINITION,
  mergeVizOverride,
  parseViewDefinition,
  type DashboardFilter,
  type ViewVisualization,
} from "@/lib/operator-view-definition";
import { ViewVisualizationPreview } from "@/components/ViewVisualizationPreview";

type DashboardSummary = {
  dashboardId: number;
  title: string;
  widgetCount: number;
  visibility: string;
};

type ViewOption = {
  viewId: number;
  title: string;
  semanticRequestCode: string | null;
  metaClassName: string | null;
};

type GridWidget = {
  viewId: number;
  title: string;
  semanticRequestCode: string | null;
  metaClassName: string | null;
  paramsJson: Record<string, unknown>;
  sortOrder: number;
  columnSpan: number;
  gridX: number;
  gridY: number;
  gridW: number;
  gridH: number;
  widgetTitle: string;
  vizOverrideJson: Record<string, unknown>;
};

type WidgetPreview = {
  widget: GridWidget;
  rows: Record<string, unknown>[];
  definition: ReturnType<typeof parseViewDefinition>;
  viz: ViewVisualization;
};

type Props = {
  initialDashboards: DashboardSummary[];
  initialViews: ViewOption[];
  selectedDashboardId?: number;
  viewMode?: boolean;
};

const GRID_COLS = 12;

export function OperatorDashboardEditor({
  initialDashboards,
  initialViews,
  selectedDashboardId,
  viewMode: initialViewMode,
}: Props) {
  const [dashboards, setDashboards] = useState(initialDashboards);
  const [views] = useState(initialViews);
  const [activeDashboardId, setActiveDashboardId] = useState<number | null>(
    selectedDashboardId ?? initialDashboards[0]?.dashboardId ?? null,
  );
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<"scope" | "organization" | "private">("scope");
  const [dashboardFilters, setDashboardFilters] = useState<DashboardFilter[]>([]);
  const [widgets, setWidgets] = useState<GridWidget[]>([]);
  const [previews, setPreviews] = useState<WidgetPreview[]>([]);
  const [viewMode, setViewMode] = useState(Boolean(initialViewMode));
  const [status, setStatus] = useState<string | null>(null);
  const [dragViewId, setDragViewId] = useState<number | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  const refreshDashboards = useCallback(async () => {
    const res = await fetch("/api/portal/dashboards", { credentials: "same-origin" });
    if (!res.ok) return;
    const body = (await res.json()) as { dashboards: DashboardSummary[] };
    setDashboards(
      body.dashboards.map((d) => ({
        dashboardId: d.dashboardId,
        title: d.title,
        widgetCount: d.widgetCount,
        visibility: d.visibility,
      })),
    );
  }, []);

  const loadDashboard = useCallback(async (dashboardId: number) => {
    const dashRes = await fetch(`/api/portal/dashboards/${dashboardId}`, { credentials: "same-origin" });
    const widgetRes = await fetch(`/api/portal/dashboards/${dashboardId}/widgets`, {
      credentials: "same-origin",
    });
    if (!dashRes.ok || !widgetRes.ok) {
      setWidgets([]);
      return;
    }
    const dashBody = (await dashRes.json()) as {
      dashboard: {
        title: string;
        description: string;
        layoutJson: Record<string, unknown>;
        visibility: string;
      };
    };
    const widgetBody = (await widgetRes.json()) as { widgets: GridWidget[] };
    setTitle(dashBody.dashboard.title);
    setDescription(dashBody.dashboard.description);
    setVisibility(
      dashBody.dashboard.visibility === "organization" || dashBody.dashboard.visibility === "private"
        ? dashBody.dashboard.visibility
        : "scope",
    );
    const layout = dashBody.dashboard.layoutJson ?? {};
    setDashboardFilters(Array.isArray(layout.dashboardFilters) ? (layout.dashboardFilters as DashboardFilter[]) : []);
    setWidgets(widgetBody.widgets);
  }, []);

  const loadPreviews = useCallback(async (widgetList: GridWidget[], filters: DashboardFilter[]) => {
    const next: WidgetPreview[] = [];
    for (const w of widgetList) {
      const definition = parseViewDefinition(w.paramsJson);
      const viz = mergeVizOverride(
        definition.visualization,
        w.vizOverrideJson as Partial<ViewVisualization>,
      );
      let rows: Record<string, unknown>[] = [];
      if (w.semanticRequestCode) {
        const params = buildSemanticRunParams({
          ...definition,
          filters: [...definition.filters, ...filters],
        });
        const res = await fetch("/api/portal/semantic/run", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            requestCode: w.semanticRequestCode,
            params,
          }),
        });
        if (res.ok) {
          const body = (await res.json()) as { rows: Record<string, unknown>[] };
          rows = body.rows;
        }
      } else if (w.metaClassName) {
        const res = await fetch(`/api/meta/classes/${encodeURIComponent(w.metaClassName)}/objects`, {
          credentials: "same-origin",
        });
        if (res.ok) {
          const body = (await res.json()) as {
            objects: Array<{ document: Record<string, unknown> }>;
          };
          const mergedFilters = [...definition.filters, ...filters];
          const flattened = body.objects.map((o) => flattenMetaDocument(o.document));
          rows = applyViewFilters(flattened, mergedFilters).slice(0, definition.limit);
        }
      }
      next.push({ widget: w, rows, definition: { ...definition, visualization: viz }, viz });
    }
    setPreviews(next);
  }, []);

  useEffect(() => {
    if (activeDashboardId == null) return;
    void loadDashboard(activeDashboardId);
  }, [activeDashboardId, loadDashboard]);

  useEffect(() => {
    void loadPreviews(widgets, dashboardFilters);
  }, [widgets, dashboardFilters, loadPreviews]);

  const maxRow = useMemo(() => {
    if (widgets.length === 0) return 4;
    return Math.max(...widgets.map((w) => w.gridY + w.gridH), 4);
  }, [widgets]);

  function cellKey(x: number, y: number) {
    return `${x},${y}`;
  }

  function widgetAt(x: number, y: number): GridWidget | undefined {
    return widgets.find(
      (w) => x >= w.gridX && x < w.gridX + w.gridW && y >= w.gridY && y < w.gridY + w.gridH,
    );
  }

  async function addWidgetFromView(viewId: number, x: number, y: number) {
    if (widgets.some((w) => w.viewId === viewId)) return;
    const view = views.find((v) => v.viewId === viewId);
    if (!view) return;
    let paramsJson: Record<string, unknown> = DEFAULT_VIEW_DEFINITION as unknown as Record<string, unknown>;
    const detailRes = await fetch(`/api/portal/views/${viewId}`, { credentials: "same-origin" });
    if (detailRes.ok) {
      const detail = (await detailRes.json()) as { view: { paramsJson: Record<string, unknown> } };
      paramsJson = detail.view.paramsJson;
    }
    const w: GridWidget = {
      viewId: view.viewId,
      title: view.title,
      semanticRequestCode: view.semanticRequestCode,
      metaClassName: view.metaClassName,
      paramsJson,
      sortOrder: (widgets.length + 1) * 10,
      columnSpan: 1,
      gridX: x,
      gridY: y,
      gridW: 4,
      gridH: 2,
      widgetTitle: view.title,
      vizOverrideJson: {},
    };
    setWidgets((prev) => [...prev, w]);
  }

  function onGridDrop(x: number, y: number) {
    if (dragViewId == null) return;
    if (widgetAt(x, y)) return;
    void addWidgetFromView(dragViewId, x, y);
    setDragViewId(null);
  }

  function resizeWidget(viewId: number, deltaW: number, deltaH: number) {
    setWidgets(
      widgets.map((w) => {
        if (w.viewId !== viewId) return w;
        const gridW = Math.min(GRID_COLS, Math.max(2, w.gridW + deltaW));
        const gridH = Math.max(1, w.gridH + deltaH);
        return { ...w, gridW, gridH };
      }),
    );
  }

  function moveWidget(viewId: number, dx: number, dy: number) {
    setWidgets(
      widgets.map((w) => {
        if (w.viewId !== viewId) return w;
        return {
          ...w,
          gridX: Math.max(0, Math.min(GRID_COLS - w.gridW, w.gridX + dx)),
          gridY: Math.max(0, w.gridY + dy),
        };
      }),
    );
  }

  function removeWidget(viewId: number) {
    setWidgets(widgets.filter((w) => w.viewId !== viewId));
  }

  async function saveDashboardMeta() {
    if (activeDashboardId == null && !title.trim()) {
      setStatus("Title required");
      return;
    }
    const res = await fetch("/api/portal/dashboards", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dashboardId: activeDashboardId ?? undefined,
        title: title.trim(),
        description: description.trim(),
        visibility,
        layoutJson: { dashboardFilters },
      }),
    });
    if (!res.ok) {
      setStatus("Could not save dashboard");
      return;
    }
    const body = (await res.json()) as { dashboardId: number };
    const dashId = body.dashboardId;
    const isNewDashboard = activeDashboardId == null;
    await refreshDashboards();
    const widgetRes = await fetch(`/api/portal/dashboards/${dashId}/widgets`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        widgets: widgets.map((w) => ({
          viewId: w.viewId,
          sortOrder: w.sortOrder,
          columnSpan: w.columnSpan,
          gridX: w.gridX,
          gridY: w.gridY,
          gridW: w.gridW,
          gridH: w.gridH,
          widgetTitle: w.widgetTitle,
          vizOverride: w.vizOverrideJson,
        })),
      }),
    });
    if (!widgetRes.ok) {
      setStatus("Dashboard saved; widget layout failed");
      return;
    }
    if (isNewDashboard) {
      setActiveDashboardId(dashId);
    }
    setStatus("Dashboard saved");
    await loadDashboard(dashId);
  }

  async function deleteDashboard() {
    if (activeDashboardId == null) return;
    if (!window.confirm("Delete this dashboard?")) return;
    const res = await fetch(`/api/portal/dashboards/${activeDashboardId}`, {
      method: "DELETE",
      credentials: "same-origin",
    });
    if (!res.ok) {
      setStatus("Delete failed");
      return;
    }
    setActiveDashboardId(null);
    setWidgets([]);
    await refreshDashboards();
    setStatus("Dashboard deleted");
  }

  function addDashboardFilter() {
    setDashboardFilters([...dashboardFilters, { field: "name", operator: "contains", value: "" }]);
  }

  return (
    <div className={`g-portal-dashboards g-portal-dashboard-editor${viewMode ? " g-portal-dashboard-editor--view" : ""}`}>
      {!viewMode ? (
        <section aria-labelledby="dash-picker-heading">
          <h3 id="dash-picker-heading">Dashboards</h3>
          <div className="g-portal-view-editor__toolbar">
            <button
              type="button"
              className="g-host-button"
              onClick={() => {
                setActiveDashboardId(null);
                setTitle("");
                setDescription("");
                setWidgets([]);
              }}
            >
              New dashboard
            </button>
            <ul className="g-operator-nav">
              {dashboards.map((d) => (
                <li key={d.dashboardId}>
                  <button
                    type="button"
                    className="g-host-button"
                    aria-pressed={activeDashboardId === d.dashboardId}
                    onClick={() => setActiveDashboardId(d.dashboardId)}
                  >
                    {d.title} ({d.widgetCount})
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <form
            className="g-portal-view-form"
            onSubmit={(e) => {
              e.preventDefault();
              void saveDashboardMeta();
            }}
          >
            <label>
              Title
              <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} required />
            </label>
            <label>
              Description
              <input type="text" value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
            <label>
              Visibility
              <select
                value={visibility}
                onChange={(e) => setVisibility(e.target.value as typeof visibility)}
              >
                <option value="scope">Everyone in this organization scope</option>
                <option value="organization">All scopes in organization</option>
                <option value="private">Only me</option>
              </select>
            </label>
            <fieldset>
              <legend>Dashboard-level filters</legend>
              {dashboardFilters.map((f, idx) => (
                <div key={idx} className="g-portal-view-editor__filter-row">
                  <input
                    type="text"
                    aria-label="Filter field"
                    value={f.field}
                    onChange={(e) => {
                      const next = [...dashboardFilters];
                      next[idx] = { ...f, field: e.target.value };
                      setDashboardFilters(next);
                    }}
                  />
                  <input
                    type="text"
                    aria-label="Filter value"
                    value={f.value == null ? "" : String(f.value)}
                    onChange={(e) => {
                      const next = [...dashboardFilters];
                      next[idx] = { ...f, value: e.target.value };
                      setDashboardFilters(next);
                    }}
                  />
                  <button
                    type="button"
                    className="g-host-button"
                    onClick={() => setDashboardFilters(dashboardFilters.filter((_, i) => i !== idx))}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <button type="button" className="g-host-button" onClick={addDashboardFilter}>
                Add dashboard filter
              </button>
            </fieldset>
            <button type="submit" className="g-host-button">
              Save dashboard
            </button>
            <button
              type="button"
              className="g-host-button"
              disabled={activeDashboardId == null}
              onClick={() => void deleteDashboard()}
            >
              Delete dashboard
            </button>
          </form>
        </section>
      ) : null}

      <section aria-labelledby="dash-layout-heading">
        <div className="g-portal-dashboard-editor__mode-bar">
          <h3 id="dash-layout-heading">{viewMode ? "Dashboard view" : "Layout canvas"}</h3>
          <button type="button" className="g-host-button" onClick={() => setViewMode((v) => !v)}>
            {viewMode ? "Edit layout" : "View mode"}
          </button>
        </div>

        {!viewMode ? (
          <aside aria-labelledby="widget-palette-heading" className="g-portal-dashboard-editor__palette">
            <h4 id="widget-palette-heading">Saved views (drag onto grid)</h4>
            <ul className="g-operator-nav">
              {views.map((v) => (
                <li key={v.viewId}>
                  <button
                    type="button"
                    className="g-host-button g-portal-dashboard-editor__drag-source"
                    draggable
                    onDragStart={() => setDragViewId(v.viewId)}
                    onDragEnd={() => setDragViewId(null)}
                  >
                    {v.title}
                  </button>
                </li>
              ))}
            </ul>
          </aside>
        ) : null}

        <div
          ref={gridRef}
          className="g-portal-dashboard-editor__grid"
          style={{
            gridTemplateColumns: `repeat(${GRID_COLS}, 1fr)`,
            gridTemplateRows: `repeat(${maxRow}, minmax(72px, auto))`,
          }}
        >
          {Array.from({ length: maxRow }, (_, y) =>
            Array.from({ length: GRID_COLS }, (_, x) => {
              const w = widgetAt(x, y);
              const isOrigin = w && w.gridX === x && w.gridY === y;
              if (w && !isOrigin) return null;
              if (isOrigin && w) {
                const preview = previews.find((p) => p.widget.viewId === w.viewId);
                return (
                  <div
                    key={cellKey(x, y)}
                    className="g-portal-view-widget g-portal-dashboard-editor__widget"
                    style={{
                      gridColumn: `${x + 1} / span ${w.gridW}`,
                      gridRow: `${y + 1} / span ${w.gridH}`,
                    }}
                  >
                    <header className="g-portal-dashboard-editor__widget-head">
                      <input
                        type="text"
                        aria-label="Widget title"
                        value={w.widgetTitle}
                        readOnly={viewMode}
                        onChange={(e) =>
                          setWidgets(
                            widgets.map((wi) =>
                              wi.viewId === w.viewId ? { ...wi, widgetTitle: e.target.value } : wi,
                            ),
                          )
                        }
                      />
                      {!viewMode ? (
                        <div className="g-portal-dashboard-editor__widget-controls">
                          <button type="button" className="g-host-button" onClick={() => moveWidget(w.viewId, -1, 0)}>
                            ←
                          </button>
                          <button type="button" className="g-host-button" onClick={() => moveWidget(w.viewId, 1, 0)}>
                            →
                          </button>
                          <button type="button" className="g-host-button" onClick={() => moveWidget(w.viewId, 0, -1)}>
                            ↑
                          </button>
                          <button type="button" className="g-host-button" onClick={() => moveWidget(w.viewId, 0, 1)}>
                            ↓
                          </button>
                          <button type="button" className="g-host-button" onClick={() => resizeWidget(w.viewId, 1, 0)}>
                            Wider
                          </button>
                          <button type="button" className="g-host-button" onClick={() => resizeWidget(w.viewId, -1, 0)}>
                            Narrower
                          </button>
                          <button type="button" className="g-host-button" onClick={() => resizeWidget(w.viewId, 0, 1)}>
                            Taller
                          </button>
                          <button type="button" className="g-host-button" onClick={() => resizeWidget(w.viewId, 0, -1)}>
                            Shorter
                          </button>
                          <button type="button" className="g-host-button" onClick={() => removeWidget(w.viewId)}>
                            Remove
                          </button>
                          <label>
                            Viz override
                            <select
                              value={(w.vizOverrideJson.type as string) ?? ""}
                              onChange={(e) => {
                                const val = e.target.value;
                                setWidgets(
                                  widgets.map((wi) =>
                                    wi.viewId === w.viewId
                                      ? {
                                          ...wi,
                                          vizOverrideJson: val
                                            ? { type: val }
                                            : {},
                                        }
                                      : wi,
                                  ),
                                );
                              }}
                            >
                              <option value="">Use view default</option>
                              <option value="table">table</option>
                              <option value="bar">bar</option>
                              <option value="line">line</option>
                              <option value="pie">pie</option>
                              <option value="kpi">kpi</option>
                            </select>
                          </label>
                        </div>
                      ) : null}
                    </header>
                    {preview ? (
                      <ViewVisualizationPreview
                        definition={preview.definition}
                        rows={preview.rows}
                        caption={w.widgetTitle}
                      />
                    ) : (
                      <p>No preview data</p>
                    )}
                  </div>
                );
              }
              if (viewMode) return null;
              return (
                <GridDropCell
                  key={cellKey(x, y)}
                  x={x}
                  y={y}
                  onDrop={() => onGridDrop(x, y)}
                />
              );
            }),
          )}
        </div>
      </section>
      {status ? <p role="status">{status}</p> : null}
    </div>
  );
}

function GridDropCell({
  x,
  y,
  onDrop,
}: {
  x: number;
  y: number;
  onDrop: () => void;
}) {
  return (
    <div
      className="g-portal-dashboard-editor__cell"
      style={{ gridColumn: x + 1, gridRow: y + 1 }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        onDrop();
      }}
    />
  );
}

function flattenMetaDocument(doc: Record<string, unknown>): Record<string, unknown> {
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
