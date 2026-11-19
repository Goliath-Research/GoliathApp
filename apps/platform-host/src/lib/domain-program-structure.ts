/**
 * Read-only structure tree for a stored DomainProgram document (domain/program.py IR).
 * Pure: turns the program's variables, phases, body and event triggers into labelled nodes.
 * Nothing here edits the program.
 */

export type ProgramTreeNode = {
  kind: string;
  label: string;
  detail?: string;
  children: ProgramTreeNode[];
};

type Doc = Record<string, unknown>;

function isObj(v: unknown): v is Doc {
  return v != null && typeof v === "object" && !Array.isArray(v);
}

function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function text(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return "";
}

/** Short "key = value" summary of a step's inputs; nested values are named, not dumped. */
function summarizeInputs(inputs: unknown): string | undefined {
  if (!isObj(inputs)) return undefined;
  const parts = Object.entries(inputs).map(([k, v]) => {
    const t = text(v);
    if (t) return `${k} = ${t.length > 48 ? `${t.slice(0, 45)}…` : t}`;
    if (Array.isArray(v)) return `${k} = list (${v.length})`;
    if (isObj(v)) return `${k} = object`;
    return k;
  });
  return parts.length ? parts.join(", ") : undefined;
}

function foreachLabel(spec: unknown): string {
  if (!isObj(spec)) return "for each";
  const item = text(spec.as) || text(spec.item) || "item";
  let source = text(spec.collection);
  if (!source) {
    const inn = spec.in;
    source = isObj(inn) ? text(inn.var) || text(inn.ref) : text(inn);
  }
  return `for each ${item} in ${source || "?"}${spec.parallel === true ? " (parallel)" : ""}`;
}

function stepsNode(kind: string, label: string, steps: unknown, detail?: string): ProgramTreeNode {
  return { kind, label, detail, children: stepList(steps) };
}

export function stepNode(step: unknown): ProgramTreeNode {
  if (!isObj(step)) return { kind: "unknown", label: "Unrecognised step", children: [] };
  if (typeof step.assign === "string") {
    const using = text(step.using) || text(step.do);
    return {
      kind: "assign",
      label: `${step.assign} ← ${using || "?"}`,
      detail: summarizeInputs(step.with),
      children: [],
    };
  }
  if (typeof step.do === "string" || typeof step.action === "string") {
    const name = text(step.do) || text(step.action);
    const inputs = [summarizeInputs(step.with), summarizeInputs(step.in)].filter(Boolean).join("; ");
    const out = isObj(step.out) ? Object.keys(step.out).join(", ") : "";
    return {
      kind: "action",
      label: name,
      detail: [inputs, out ? `out: ${out}` : "", text(step.node_key) ? `node ${text(step.node_key)}` : ""]
        .filter(Boolean)
        .join(" · ") || undefined,
      children: [],
    };
  }
  if ("if" in step) {
    return {
      kind: "if",
      label: `if ${text(step.if)}`,
      children: [stepsNode("branch", "then", step.then), stepsNode("branch", "else", step.else)].filter(
        (n) => n.children.length > 0 || n.label === "then",
      ),
    };
  }
  if ("switch" in step) {
    const disc = step.switch;
    const on = (isObj(disc) ? text(disc.ref) || text(disc.var) : text(disc)) || "value";
    const cases = isObj(step.cases)
      ? Object.entries(step.cases).map(([k, v]) => stepsNode("branch", `case ${k}`, v))
      : [];
    const def = asList(step.default).length ? [stepsNode("branch", "default", step.default)] : [];
    return { kind: "switch", label: `switch ${on}`, children: [...cases, ...def] };
  }
  if ("while" in step) {
    return stepsNode("while", `while ${text(step.while)}`, asList(step.do).length ? step.do : step.body);
  }
  if ("repeat" in step) {
    const count = isObj(step.repeat) ? text(step.repeat.count) : text(step.repeat);
    return stepsNode("repeat", `repeat ${count || "?"} times`, asList(step.do).length ? step.do : step.body);
  }
  if ("for" in step || "foreach" in step) {
    const body = asList(step.do).length ? step.do : step.steps;
    return stepsNode("foreach", foreachLabel(step.for ?? step.foreach), body);
  }
  if ("parallel" in step) {
    return stepsNode("parallel", "in parallel", step.parallel);
  }
  if (isObj(step.wait)) {
    const corr = text(step.wait.correlation);
    return {
      kind: "wait",
      label: `wait for event ${text(step.wait.event) || "?"}`,
      detail: corr ? `correlation: ${corr}` : undefined,
      children: [],
    };
  }
  return { kind: "unknown", label: "Unrecognised step", detail: Object.keys(step).join(", "), children: [] };
}

function stepList(steps: unknown): ProgramTreeNode[] {
  return asList(steps).map(stepNode);
}

export function programStructureTree(doc: Doc): ProgramTreeNode[] {
  const out: ProgramTreeNode[] = [];
  const vars = isObj(doc.variables) ? doc.variables : {};
  const decls = isObj(doc.declarations) ? doc.declarations : {};
  const varNodes: ProgramTreeNode[] = [
    ...Object.entries(vars).map(([k, v]) => {
      const typed = isObj(v) && (typeof v.schemaRef === "string" || "schema" in v);
      return {
        kind: "variable",
        label: k,
        detail: typed
          ? `type ${text((v as Doc).schemaRef) || "inline schema"}`
          : Array.isArray(v)
            ? `default: list (${v.length})`
            : text(v)
              ? `default: ${text(v)}`
              : undefined,
        children: [],
      };
    }),
    ...Object.keys(decls).map((k) => ({ kind: "variable", label: k, detail: "declared", children: [] })),
  ];
  if (varNodes.length) out.push({ kind: "section", label: "Variables", children: varNodes });
  const triggers = asList(doc.on)
    .filter(isObj)
    .map((t) => ({
      kind: "trigger",
      label: `on ${text(t.event) || "?"}`,
      detail: text(t.mode) || "start_instance",
      children: [],
    }));
  if (triggers.length) out.push({ kind: "section", label: "Event triggers", children: triggers });
  const phases = asList(doc.phases)
    .filter(isObj)
    .map((p) => ({
      kind: "phase",
      label: `Phase ${text(p.name) || "?"}`,
      detail: p.foreach ? foreachLabel(p.foreach) : undefined,
      children: stepList(p.steps),
    }));
  if (phases.length) out.push({ kind: "section", label: "Phases", children: phases });
  const body = stepList(doc.body);
  out.push({ kind: "section", label: "Body", children: body });
  return out;
}

export function countSteps(nodes: ProgramTreeNode[]): number {
  let n = 0;
  for (const node of nodes) {
    if (node.kind === "action" || node.kind === "assign" || node.kind === "wait") n += 1;
    n += countSteps(node.children);
  }
  return n;
}

/** Designer link for a compiled workflow version (WorkflowGraphWorkspace reads `?version=`). */
export function compiledGraphHref(versionId: unknown): string | null {
  const id = Number(versionId);
  return Number.isInteger(id) && id > 0 ? `/app/workflows/definitions?version=${id}` : null;
}

/** Workflow version id from a `?version=` query string, or null. */
export function linkedVersionId(search: string): number | null {
  const raw = new URLSearchParams(search).get("version");
  const id = raw == null || raw === "" ? Number.NaN : Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}
