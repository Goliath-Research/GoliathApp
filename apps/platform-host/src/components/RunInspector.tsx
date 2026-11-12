"use client";

import { ReferencePicker } from "@goliath/platform-ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchRecordDocument, runRecordEditorAction } from "@/lib/record-editor-client";
import { canCancelRun, canRetryNode } from "@/lib/workflow-graph-schemas";

type RunRow = { instance_id: number; workflow_def_name: string; status: string; started_at_utc: string | null };

type RunDoc = {
  workflow_instance_id: number;
  workflow_def_name: string;
  version: string;
  status: string;
  started_at_utc: string | null;
  completed_at_utc: string | null;
  nodes: {
    node_execution_id: number;
    node_key: string;
    node_type: string;
    action_name: string | null;
    status: string;
    attempt_no: number | null;
    iteration_no: number | null;
    started_at_utc: string | null;
    ended_at_utc: string | null;
    error_message: string | null;
  }[];
  variables: { scope_node_execution_id: number | null; name: string; value: unknown }[];
  study: { study_row_id: number; study_id: string | null; name: string | null } | null;
};

function renderValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** Run inspector: pick a recent run, see nodes / variables / study, cancel, retry or link a study. */
export function RunInspector() {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runId, setRunId] = useState<string>("");
  const [doc, setDoc] = useState<RunDoc | null>(null);
  const [studyValue, setStudyValue] = useState<string>("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch("/api/portal/workflows/runs?range=30d&limit=200", {
          credentials: "same-origin",
          cache: "no-store",
        });
        if (!res.ok) throw new Error(`Runs request failed (${res.status})`);
        const body = (await res.json()) as { rows: Record<string, unknown>[] };
        setRuns(
          (body.rows ?? []).map((r) => ({
            instance_id: Number(r.instance_id),
            workflow_def_name: String(r.workflow_def_name ?? ""),
            status: String(r.status ?? ""),
            started_at_utc: r.started_at_utc ? String(r.started_at_utc) : null,
          })),
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  const load = useCallback(async (id: string) => {
    const s = ++seq.current;
    setError(null);
    if (!id) {
      setDoc(null);
      return;
    }
    setDoc(null);
    try {
      const data = (await fetchRecordDocument("workflow_run", id)) as unknown as RunDoc;
      if (s === seq.current) setDoc(data);
    } catch (e) {
      if (s === seq.current) setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const act = useCallback(
    async (action: string, key: string, message: string, document?: Record<string, unknown>) => {
      setError(null);
      try {
        await runRecordEditorAction("workflow_run", action, key, document);
        setStatus(message);
        await load(runId);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [load, runId],
  );

  return (
    <section className="g-record-editor g-run-inspector" data-testid="run-inspector">
      <header className="g-record-editor__toolbar">
        <h3>Run inspector</h3>
        <label>
          <span>Run</span>{" "}
          <select
            aria-label="Run to inspect"
            value={runId}
            onChange={(e) => {
              setRunId(e.target.value);
              setStatus(null);
              void load(e.target.value);
            }}
          >
            <option value="">Select a run (last 30 days)…</option>
            {runs.map((r) => (
              <option key={r.instance_id} value={String(r.instance_id)}>
                #{r.instance_id} {r.workflow_def_name} · {r.status}
                {r.started_at_utc ? ` · ${new Date(r.started_at_utc).toLocaleString()}` : ""}
              </option>
            ))}
          </select>
        </label>
        {doc ? (
          <button type="button" onClick={() => void load(runId)}>
            Refresh
          </button>
        ) : null}
      </header>
      {error ? (
        <p role="alert" className="g-record-editor__error">
          {error}
        </p>
      ) : null}
      {status ? <p role="status">{status}</p> : null}
      {doc ? (
        <div className="g-run-inspector__body">
          <dl className="g-run-inspector__summary">
            <dt>Workflow</dt>
            <dd>
              {doc.workflow_def_name} v{doc.version}
            </dd>
            <dt>Status</dt>
            <dd data-testid="run-status">{doc.status}</dd>
            <dt>Started</dt>
            <dd>{doc.started_at_utc ? new Date(doc.started_at_utc).toLocaleString() : "—"}</dd>
            <dt>Completed</dt>
            <dd>{doc.completed_at_utc ? new Date(doc.completed_at_utc).toLocaleString() : "—"}</dd>
          </dl>
          {canCancelRun(doc.status) ? (
            <button
              type="button"
              onClick={() => {
                if (window.confirm(`Cancel run #${doc.workflow_instance_id}? Queued work is dropped.`)) {
                  void act("cancel", String(doc.workflow_instance_id), `Cancelled run #${doc.workflow_instance_id}`);
                }
              }}
            >
              Cancel run
            </button>
          ) : null}

          <h4>Nodes</h4>
          <table className="g-record-editor__table">
            <thead>
              <tr>
                <th scope="col">Node</th>
                <th scope="col">Type</th>
                <th scope="col">Action</th>
                <th scope="col">Status</th>
                <th scope="col">Attempt</th>
                <th scope="col">Error</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {doc.nodes.length === 0 ? (
                <tr>
                  <td colSpan={7}>No node executions</td>
                </tr>
              ) : (
                doc.nodes.map((n) => (
                  <tr key={n.node_execution_id}>
                    <td>
                      {n.node_key}
                      {n.iteration_no != null ? ` [${n.iteration_no}]` : ""}
                    </td>
                    <td>{n.node_type}</td>
                    <td>{n.action_name ?? "—"}</td>
                    <td>{n.status}</td>
                    <td>{n.attempt_no ?? "—"}</td>
                    <td>{n.error_message ?? ""}</td>
                    <td>
                      {canRetryNode(n.status) ? (
                        <button
                          type="button"
                          aria-label={`Retry ${n.node_key}`}
                          onClick={() =>
                            void act("retry", String(n.node_execution_id), `Queued retry of ${n.node_key}`)
                          }
                        >
                          Retry
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          <h4>Variables</h4>
          <table className="g-record-editor__table">
            <thead>
              <tr>
                <th scope="col">Scope</th>
                <th scope="col">Name</th>
                <th scope="col">Value</th>
              </tr>
            </thead>
            <tbody>
              {doc.variables.length === 0 ? (
                <tr>
                  <td colSpan={3}>No variables</td>
                </tr>
              ) : (
                doc.variables.map((v) => (
                  <tr key={`${v.scope_node_execution_id ?? "root"}:${v.name}`}>
                    <td>{v.scope_node_execution_id ?? "instance"}</td>
                    <td>{v.name}</td>
                    <td>
                      <code className="g-run-inspector__value">{renderValue(v.value)}</code>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          <h4>Study</h4>
          {doc.study ? (
            <p data-testid="run-study">
              {doc.study.name ?? doc.study.study_id ?? `#${doc.study.study_row_id}`}
              {doc.study.study_id ? ` (${doc.study.study_id})` : ""}
            </p>
          ) : (
            <div className="g-run-inspector__link-study">
              <ReferencePicker
                fieldName="study"
                kind="study"
                value={studyValue}
                onChange={(v) => setStudyValue(v)}
              />
              <button
                type="button"
                disabled={!studyValue}
                onClick={() =>
                  void act("link_study", String(doc.workflow_instance_id), "Linked study", {
                    study_row_id: Number(studyValue),
                  })
                }
              >
                Link study
              </button>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
