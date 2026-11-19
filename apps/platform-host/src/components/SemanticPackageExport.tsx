"use client";

import { useState } from "react";

/** Download the semantic + Meta model rows of one class namespace as package SQL. */
export function SemanticPackageExport({ prefixes }: { prefixes: string[] }) {
  const [prefix, setPrefix] = useState(prefixes[0] ?? "your_app/");
  const [status, setStatus] = useState<string | null>(null);

  async function exportPackage() {
    setStatus(null);
    try {
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
    <div className="g-record-grid__toolbar">
      <label>
        Class namespace{" "}
        <select value={prefix} onChange={(e) => setPrefix(e.target.value)}>
          {prefixes.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="g-host-button" onClick={() => void exportPackage()}>
        Export as package SQL
      </button>
      {status ? <span role="status">{status}</span> : null}
    </div>
  );
}
