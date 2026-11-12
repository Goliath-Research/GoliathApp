/** Time-range options for the operator Workflow runs page (`?range=`). */

export type WorkflowRunsRangeKey = "24h" | "7d" | "30d" | "all";

export interface WorkflowRunsRange {
  key: WorkflowRunsRangeKey;
  label: string;
  /** Lower bound in hours; `null` means no lower bound (all runs). */
  hoursBack: number | null;
}

export const WORKFLOW_RUNS_RANGES: readonly WorkflowRunsRange[] = [
  { key: "24h", label: "Last 24 hours", hoursBack: 24 },
  { key: "7d", label: "Last 7 days", hoursBack: 168 },
  { key: "30d", label: "Last 30 days", hoursBack: 720 },
  { key: "all", label: "All runs", hoursBack: null },
];

export const DEFAULT_WORKFLOW_RUNS_RANGE: WorkflowRunsRangeKey = "7d";

/** Default and maximum page size; the session function clamps to the same ceiling. */
export const DEFAULT_WORKFLOW_RUNS_LIMIT = 200;
export const MAX_WORKFLOW_RUNS_LIMIT = 500;

export function resolveWorkflowRunsRange(raw: string | null | undefined): WorkflowRunsRange {
  const key = (raw ?? "").trim().toLowerCase();
  const match = WORKFLOW_RUNS_RANGES.find((r) => r.key === key);
  if (match) {
    return match;
  }
  return WORKFLOW_RUNS_RANGES.find((r) => r.key === DEFAULT_WORKFLOW_RUNS_RANGE)!;
}

export function resolveWorkflowRunsLimit(raw: string | number | null | undefined): number {
  const n = typeof raw === "number" ? raw : Number.parseInt(String(raw ?? ""), 10);
  if (!Number.isFinite(n) || n < 1) {
    return DEFAULT_WORKFLOW_RUNS_LIMIT;
  }
  return Math.min(Math.trunc(n), MAX_WORKFLOW_RUNS_LIMIT);
}

export function workflowRunsRangeHref(pathname: string, key: WorkflowRunsRangeKey): string {
  return `${pathname}?range=${encodeURIComponent(key)}`;
}
