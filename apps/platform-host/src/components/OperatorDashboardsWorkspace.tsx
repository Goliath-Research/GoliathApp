"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PlatformRecordTable } from "@goliath/platform-ui";

type Dashboard = { dashboardId: number; title: string; widgetCount: number };
type ViewOption = { viewId: number; title: string; semanticRequestCode: string | null; metaClassName: string | null };
type Widget = {
  viewId: number;
  title: string;
  semanticRequestCode: string | null;
  sortOrder: number;
  columnSpan: number;
};
type WidgetPreview = { title: string; columns: { key: string; label: string }[]; rows: Record<string, unknown>[] };

type Props = {
  initialDashboards: Dashboard[];
  initialViews: ViewOption[];
  selectedDashboardId?: number;
};

export function OperatorDashboardsWorkspace({
  initialDashboards,
  initialViews,
  selectedDashboardId,
}: Props) {
  const [dashboards, setDashboards] = useState(initialDashboards);
  const [views] = useState(initialViews);
  const [activeDashboardId, setActiveDashboardId] = useState<number | null>(
    selectedDashboardId ?? initialDashboards[0]?.dashboardId ?? null,
  );
  const [dashboardTitle, setDashboardTitle] = useState("");
  const [widgets, setWidgets] = useState<Widget[]>([]);
  const [widgetPreviews, setWidgetPreviews] = useState<WidgetPreview[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const activeDashboardIdRef = useRef(activeDashboardId);
  activeDashboardIdRef.current = activeDashboardId;

  const loadWidgets = useCallback(async (dashboardId: number) => {
    const stillCurrent = () => activeDashboardIdRef.current === dashboardId;
    const res = await fetch(`/api/portal/dashboards/${dashboardId}/widgets`, { credentials: "same-origin" });
    if (!stillCurrent()) return;
    if (!res.ok) {
      setWidgets([]);
      setWidgetPreviews([]);
      return;
    }
    const body = (await res.json()) as { widgets: Widget[] };
    if (!stillCurrent()) return;
    setWidgets(body.widgets);
    const previews: WidgetPreview[] = [];
    for (const w of body.widgets) {
      if (!stillCurrent()) return;
      if (!w.semanticRequestCode) {
        previews.push({ title: w.title, columns: [], rows: [] });
        continue;
      }
      const run = await fetch("/api/portal/semantic/run", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ requestCode: w.semanticRequestCode, params: { limit: 10 } }),
      });
      if (!stillCurrent()) return;
      if (!run.ok) continue;
      const data = (await run.json()) as { rows: Record<string, unknown>[] };
      if (!stillCurrent()) return;
      const rows = data.rows;
      previews.push({
        title: w.title,
        rows,
        columns: rows.length
          ? Object.keys(rows[0] ?? {}).map((k) => ({ key: k, label: k.replace(/_/g, " ") }))
          : [],
      });
    }
    if (!stillCurrent()) return;
    setWidgetPreviews(previews);
  }, []);

  useEffect(() => {
    if (activeDashboardId == null) return;
    setWidgets([]);
    setWidgetPreviews([]);
    void loadWidgets(activeDashboardId);
  }, [activeDashboardId, loadWidgets]);

  async function createDashboard(e: React.FormEvent) {
    e.preventDefault();
    const res = await fetch("/api/portal/dashboards", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: dashboardTitle.trim() }),
    });
    if (!res.ok) {
      setStatus("Could not create dashboard");
      return;
    }
    const body = (await res.json()) as { dashboardId: number };
    const list = await fetch("/api/portal/dashboards", { credentials: "same-origin" });
    const listed = (await list.json()) as { dashboards: Dashboard[] };
    setDashboards(listed.dashboards);
    setActiveDashboardId(body.dashboardId);
    setDashboardTitle("");
    setStatus("Dashboard created");
  }

  function moveWidget(index: number, delta: number) {
    const next = [...widgets];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    const tmp = next[index]!;
    next[index] = next[target]!;
    next[target] = tmp;
    setWidgets(next.map((w, i) => ({ ...w, sortOrder: (i + 1) * 10 })));
  }

  function toggleAddView(viewId: number) {
    if (widgets.some((w) => w.viewId === viewId)) {
      setWidgets(widgets.filter((w) => w.viewId !== viewId));
      return;
    }
    const view = views.find((v) => v.viewId === viewId);
    if (!view) return;
    setWidgets([
      ...widgets,
      {
        viewId: view.viewId,
        title: view.title,
        semanticRequestCode: view.semanticRequestCode,
        sortOrder: (widgets.length + 1) * 10,
        columnSpan: 1,
      },
    ]);
  }

  async function saveArrangement() {
    if (activeDashboardId == null) return;
    const res = await fetch(`/api/portal/dashboards/${activeDashboardId}/widgets`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        widgets: widgets.map((w) => ({
          viewId: w.viewId,
          sortOrder: w.sortOrder,
          columnSpan: w.columnSpan,
        })),
      }),
    });
    if (!res.ok) {
      setStatus("Could not save arrangement");
      return;
    }
    setStatus("Dashboard arrangement saved");
    await loadWidgets(activeDashboardId);
  }

  return (
    <div className="g-portal-dashboards">
      <section aria-labelledby="create-dashboard-heading">
        <h3 id="create-dashboard-heading">Create dashboard</h3>
        <form onSubmit={(e) => void createDashboard(e)} className="g-portal-view-form">
          <label>
            Title
            <input value={dashboardTitle} onChange={(e) => setDashboardTitle(e.target.value)} required />
          </label>
          <button type="submit" className="g-host-button">
            Create
          </button>
        </form>
        {status ? <p role="status">{status}</p> : null}
      </section>

      <section aria-labelledby="pick-dashboard-heading">
        <h3 id="pick-dashboard-heading">Dashboards</h3>
        <ul className="g-operator-nav">
          {dashboards.map((d) => (
            <li key={d.dashboardId}>
              <button
                type="button"
                className="g-host-button"
                onClick={() => setActiveDashboardId(d.dashboardId)}
                aria-pressed={activeDashboardId === d.dashboardId}
              >
                {d.title} ({d.widgetCount} widgets)
              </button>
            </li>
          ))}
        </ul>
      </section>

      {activeDashboardId != null ? (
        <section aria-labelledby="arrange-heading">
          <h3 id="arrange-heading">Arrange views</h3>
          <p className="g-host-home__lead">Add saved views and reorder them. Layout is stored per organization scope.</p>
          <ul className="g-operator-nav">
            {views.map((v) => (
              <li key={v.viewId}>
                <label>
                  <input
                    type="checkbox"
                    checked={widgets.some((w) => w.viewId === v.viewId)}
                    onChange={() => toggleAddView(v.viewId)}
                  />
                  {v.title}
                </label>
              </li>
            ))}
          </ul>
          <ol className="g-operator-nav">
            {widgets.map((w, idx) => (
              <li key={w.viewId}>
                {w.title}
                <button type="button" className="g-host-button" onClick={() => moveWidget(idx, -1)} disabled={idx === 0}>
                  Up
                </button>
                <button
                  type="button"
                  className="g-host-button"
                  onClick={() => moveWidget(idx, 1)}
                  disabled={idx === widgets.length - 1}
                >
                  Down
                </button>
              </li>
            ))}
          </ol>
          <button type="button" className="g-host-button" onClick={() => void saveArrangement()}>
            Save arrangement
          </button>
        </section>
      ) : null}

      {widgetPreviews.length > 0 ? (
        <section aria-labelledby="dash-preview-heading">
          <h3 id="dash-preview-heading">Dashboard preview</h3>
          <div className="g-portal-dashboard__grid">
            {widgetPreviews.map((p) => (
              <div key={p.title} className="g-portal-view-widget">
                <h4>{p.title}</h4>
                {p.columns.length ? (
                  <PlatformRecordTable caption={p.title} columns={p.columns} rows={p.rows} />
                ) : (
                  <p>Open linked Meta class in the workbench.</p>
                )}
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
