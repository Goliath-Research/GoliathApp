"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  compiledGraphHref,
  countSteps,
  programStructureTree,
  type ProgramTreeNode,
} from "@/lib/domain-program-structure";
import { fetchRecordRows } from "@/lib/record-editor-client";

type ProgramRow = { name: string; version: string; status: string };

function TreeList({ nodes }: { nodes: ProgramTreeNode[] }) {
  if (nodes.length === 0) return null;
  return (
    <ul className="g-program-tree">
      {nodes.map((n, i) => (
        <li key={`${n.kind}-${i}`} data-kind={n.kind}>
          <span className="g-program-tree__label">{n.label}</span>
          {n.detail ? <span className="g-program-tree__detail"> — {n.detail}</span> : null}
          <TreeList nodes={n.children} />
        </li>
      ))}
    </ul>
  );
}

/**
 * Read-only view of a domain program version: its structure tree (variables, triggers, phases,
 * body) and a link to the compiled workflow graph. Structural changes stay in the program's
 * seed; this panel never writes.
 */
export function DomainProgramStructurePanel() {
  const [programs, setPrograms] = useState<ProgramRow[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [structure, setStructure] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    void (async () => {
      try {
        const rows = await fetchRecordRows("domain_program");
        setPrograms(
          rows.map((r) => ({ name: String(r.name ?? ""), version: String(r.version ?? ""), status: String(r.status ?? "") })),
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  const open = useCallback(async (key: string) => {
    setSelected(key);
    setStructure(null);
    setError(null);
    if (!key) return;
    const s = ++seq.current;
    const at = key.lastIndexOf("@");
    const params = new URLSearchParams({ name: key.slice(0, at), version: key.slice(at + 1) });
    try {
      const res = await fetch(`/api/portal/domain-programs/structure?${params}`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      const body = (await res.json().catch(() => ({}))) as { structure?: Record<string, unknown>; error?: string };
      if (!res.ok) throw new Error(body.error ?? `Request failed (${res.status})`);
      if (s === seq.current) setStructure(body.structure ?? {});
    } catch (e) {
      if (s === seq.current) setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const tree = structure ? programStructureTree(structure) : [];
  const graphHref = structure ? compiledGraphHref(structure.compiled_workflow_version_id) : null;

  return (
    <section className="g-record-editor" aria-label="Program structure" data-testid="domain-program-structure">
      <header className="g-record-editor__toolbar">
        <h3>Program structure</h3>
        <label>
          <span className="sr-only">Program version</span>
          <select value={selected} onChange={(e) => void open(e.target.value)} aria-label="Program version">
            <option value="">Choose a program version…</option>
            {programs.map((p) => (
              <option key={`${p.name}@${p.version}`} value={`${p.name}@${p.version}`}>
                {p.name} v{p.version} ({p.status})
              </option>
            ))}
          </select>
        </label>
      </header>
      {error ? (
        <p role="alert" className="g-record-editor__error">
          {error}
        </p>
      ) : null}
      {structure ? (
        <div>
          <p className="g-host-home__lead">
            {String(structure.description ?? "")} {countSteps(tree)} step{countSteps(tree) === 1 ? "" : "s"}.
          </p>
          {graphHref ? (
            <p>
              <a href={graphHref} data-testid="domain-program-open-graph">
                Open graph
              </a>{" "}
              — compiled as {String(structure.compiled_workflow_name ?? "workflow")} v
              {String(structure.compiled_version ?? "")}
              {structure.compiled_is_active === true ? " (active)" : " (inactive)"}
            </p>
          ) : (
            <p role="status">This version has no compiled workflow yet.</p>
          )}
          <TreeList nodes={tree} />
        </div>
      ) : null}
    </section>
  );
}
