import { describe, expect, it } from "vitest";
import {
  DEFAULT_WORKFLOW_RUNS_LIMIT,
  MAX_WORKFLOW_RUNS_LIMIT,
  WORKFLOW_RUNS_RANGES,
  resolveWorkflowRunsLimit,
  resolveWorkflowRunsRange,
  workflowRunsRangeHref,
} from "./workflow-runs-range";

describe("resolveWorkflowRunsRange", () => {
  it("defaults to the last 7 days", () => {
    expect(resolveWorkflowRunsRange(undefined)).toMatchObject({ key: "7d", hoursBack: 168 });
    expect(resolveWorkflowRunsRange("")).toMatchObject({ key: "7d", hoursBack: 168 });
    expect(resolveWorkflowRunsRange("bogus")).toMatchObject({ key: "7d", hoursBack: 168 });
  });

  it("maps each option to its lower bound", () => {
    expect(resolveWorkflowRunsRange("24h").hoursBack).toBe(24);
    expect(resolveWorkflowRunsRange("30d").hoursBack).toBe(720);
    expect(resolveWorkflowRunsRange("ALL").hoursBack).toBeNull();
  });

  it("offers 24h, 7d, 30d and all", () => {
    expect(WORKFLOW_RUNS_RANGES.map((r) => r.key)).toEqual(["24h", "7d", "30d", "all"]);
  });
});

describe("resolveWorkflowRunsLimit", () => {
  it("defaults invalid input and clamps to the ceiling", () => {
    expect(resolveWorkflowRunsLimit(undefined)).toBe(DEFAULT_WORKFLOW_RUNS_LIMIT);
    expect(resolveWorkflowRunsLimit("0")).toBe(DEFAULT_WORKFLOW_RUNS_LIMIT);
    expect(resolveWorkflowRunsLimit("-4")).toBe(DEFAULT_WORKFLOW_RUNS_LIMIT);
    expect(resolveWorkflowRunsLimit("abc")).toBe(DEFAULT_WORKFLOW_RUNS_LIMIT);
    expect(resolveWorkflowRunsLimit("50")).toBe(50);
    expect(resolveWorkflowRunsLimit(10_000)).toBe(MAX_WORKFLOW_RUNS_LIMIT);
  });
});

describe("workflowRunsRangeHref", () => {
  it("builds a range query link", () => {
    expect(workflowRunsRangeHref("/app/workflows/runs", "all")).toBe("/app/workflows/runs?range=all");
  });
});
