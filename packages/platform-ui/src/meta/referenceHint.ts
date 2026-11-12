/**
 * Reference picker schema hint.
 *
 * A string or integer property annotated with `x-goliath-ref` is edited by picking an
 * existing row from a catalog (searchable list) instead of typing a raw identifier:
 *
 *   { "type": "string",  "x-goliath-ref": "action" }
 *   { "type": "integer", "x-goliath-ref": { "kind": "workflow_version" } }
 *
 * Kinds are resolved by the host's {@link ReferenceResolver}; the platform host ships
 * `action`, `workflow_def`, `workflow_version`, `event_type`, `cluster`, `worker`,
 * `data_type`, `meta_class`, `meta_method` and `study`. Descendant apps may add kinds.
 */

export const REFERENCE_HINT_KEY = "x-goliath-ref";

export type ReferenceHint = {
  kind: string;
};

export function parseReferenceHint(schema: unknown): ReferenceHint | null {
  if (schema == null || typeof schema !== "object" || Array.isArray(schema)) return null;
  const raw = (schema as Record<string, unknown>)[REFERENCE_HINT_KEY];
  if (typeof raw === "string" && raw.trim() !== "") {
    return { kind: raw.trim() };
  }
  if (raw != null && typeof raw === "object" && !Array.isArray(raw)) {
    const kind = (raw as Record<string, unknown>).kind;
    if (typeof kind === "string" && kind.trim() !== "") {
      return { kind: kind.trim() };
    }
  }
  return null;
}
