"use client";

import { useCallback, useEffect, useState } from "react";
import { PlatformRecordTable } from "@goliath/platform-ui";

type CatalogEntry = {
  requestCode: string;
  displayName: string;
  namespace: string;
  entityCode: string;
};

type SavedView = {
  viewId: number;
  title: string;
  description: string;
  semanticRequestCode: string | null;
  metaClassName: string | null;
};

type Props = {
  catalog: CatalogEntry[];
  metaClasses: string[];
  initialViews: SavedView[];
  runViewId?: number;
};

export function OperatorViewsWorkspace({ catalog, metaClasses, initialViews, runViewId }: Props) {
  const [views, setViews] = useState(initialViews);
  const [title, setTitle] = useState("");
  const [requestCode, setRequestCode] = useState(catalog[0]?.requestCode ?? "");
  const [metaClass, setMetaClass] = useState(metaClasses[0] ?? "portal/NavNode");
  const [sourceKind, setSourceKind] = useState<"semantic" | "meta">("semantic");
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [previewCols, setPreviewCols] = useState<{ key: string; label: string }[]>([]);
  const [status, setStatus] = useState<string | null>(null);

  const refreshViews = useCallback(async () => {
    const res = await fetch("/api/portal/views", { credentials: "same-origin" });
    if (!res.ok) return;
    const body = (await res.json()) as { views: SavedView[] };
    setViews(body.views);
  }, []);

  const runPreview = useCallback(
    async (view: SavedView) => {
      if (view.semanticRequestCode) {
        const res = await fetch("/api/portal/semantic/run", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ requestCode: view.semanticRequestCode, params: { limit: 25 } }),
        });
        if (!res.ok) {
          setStatus("Could not run view");
          return;
        }
        const body = (await res.json()) as { rows: Record<string, unknown>[] };
        const rows = body.rows;
        setPreviewRows(rows);
        setPreviewCols(
          rows.length
            ? Object.keys(rows[0] ?? {}).map((k) => ({ key: k, label: k.replace(/_/g, " ") }))
            : [],
        );
      } else if (view.metaClassName) {
        window.location.href = `/app/meta?class=${encodeURIComponent(view.metaClassName)}`;
      }
    },
    [],
  );

  useEffect(() => {
    const view = views.find((v) => v.viewId === runViewId);
    if (view) void runPreview(view);
  }, [runViewId, views, runPreview]);

  async function saveView(e: React.FormEvent) {
    e.preventDefault();
    setStatus(null);
    const res = await fetch("/api/portal/views", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: title.trim(),
        semanticRequestCode: sourceKind === "semantic" ? requestCode : null,
        metaClassName: sourceKind === "meta" ? metaClass : null,
        paramsJson: { limit: 50 },
      }),
    });
    if (!res.ok) {
      setStatus("Save failed");
      return;
    }
    setTitle("");
    setStatus("View saved");
    await refreshViews();
  }

  return (
    <div className="g-portal-views">
      <section aria-labelledby="define-view-heading">
        <h3 id="define-view-heading">Define a view</h3>
        <p className="g-host-home__lead">
          Views bind to the same semantic requests and Meta classes as individual editors. Saved views can be placed on
          dashboards.
        </p>
        <form className="g-portal-view-form" onSubmit={(e) => void saveView(e)}>
          <label>
            Title
            <input value={title} onChange={(ev) => setTitle(ev.target.value)} required />
          </label>
          <fieldset>
            <legend>Entity source</legend>
            <label>
              <input
                type="radio"
                name="source"
                checked={sourceKind === "semantic"}
                onChange={() => setSourceKind("semantic")}
              />
              Semantic request
            </label>
            <label>
              <input
                type="radio"
                name="source"
                checked={sourceKind === "meta"}
                onChange={() => setSourceKind("meta")}
              />
              Meta class (opens workbench)
            </label>
          </fieldset>
          {sourceKind === "semantic" ? (
            <label>
              Request
              <select value={requestCode} onChange={(ev) => setRequestCode(ev.target.value)}>
                {catalog.map((c) => (
                  <option key={c.requestCode} value={c.requestCode}>
                    {c.displayName} ({c.requestCode})
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label>
              Meta class
              <select value={metaClass} onChange={(ev) => setMetaClass(ev.target.value)}>
                {metaClasses.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button type="submit" className="g-host-button">
            Save view
          </button>
          {status ? <p role="status">{status}</p> : null}
        </form>
      </section>

      <section aria-labelledby="saved-views-heading">
        <h3 id="saved-views-heading">Saved views (this scope)</h3>
        <ul className="g-operator-nav">
          {views.map((v) => (
            <li key={v.viewId}>
              <button type="button" className="g-host-button" onClick={() => void runPreview(v)}>
                {v.title}
              </button>
              {v.metaClassName ? <span> · Meta {v.metaClassName}</span> : null}
              {v.semanticRequestCode ? <span> · {v.semanticRequestCode}</span> : null}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="platform-views-heading">
        <h3 id="platform-views-heading">Platform semantic views</h3>
        <table className="g-host-table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Request</th>
            </tr>
          </thead>
          <tbody>
            {catalog.map((c) => (
              <tr key={c.requestCode}>
                <td>{c.displayName}</td>
                <td>
                  <code>{c.requestCode}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {previewCols.length > 0 ? (
        <section aria-labelledby="view-preview-heading">
          <h3 id="view-preview-heading">View preview</h3>
          <PlatformRecordTable caption="View data" columns={previewCols} rows={previewRows} />
        </section>
      ) : null}
    </div>
  );
}
