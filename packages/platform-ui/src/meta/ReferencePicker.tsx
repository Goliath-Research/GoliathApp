"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { useReferenceResolver, type ReferenceOption } from "./ReferenceResolverContext.js";

export type ReferencePickerProps = {
  fieldName: string;
  kind: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  optional?: boolean;
  /** Debounce in ms before searching (tests pass 0). */
  debounceMs?: number;
};

/**
 * Searchable picker of existing catalog rows. Users never type raw identifiers or JSON:
 * they search, then pick a row from the list.
 */
export function ReferencePicker({
  fieldName,
  kind,
  value,
  onChange,
  disabled = false,
  optional = true,
  debounceMs = 200,
}: ReferencePickerProps) {
  const resolver = useReferenceResolver();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<ReferenceOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);

  useEffect(() => {
    if (!resolver) return;
    let cancelled = false;
    const handle = setTimeout(() => {
      setLoading(true);
      setError(null);
      resolver
        .search(kind, query, { limit: 50 })
        .then((rows) => {
          if (!cancelled) setOptions(rows);
        })
        .catch((e: unknown) => {
          if (!cancelled) setError(e instanceof Error ? e.message : "search failed");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, debounceMs);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [resolver, kind, query, debounceMs]);

  const current = useMemo(() => options.find((o) => o.value === value) ?? null, [options, value]);

  useEffect(() => {
    if (current) setSelectedLabel(current.label);
    else if (value === "") setSelectedLabel(null);
  }, [current, value]);

  if (!resolver) {
    return (
      <span role="alert" className="g-property-inspector__error">
        Reference picker unavailable for {kind}
      </span>
    );
  }

  const listOptions = value !== "" && !current ? [{ value, label: selectedLabel ?? value, detail: "current" }, ...options] : options;

  return (
    <div className="g-reference-picker" data-testid={`pi-ref-${fieldName}`} data-ref-kind={kind}>
      <input
        type="search"
        className="g-host-input"
        aria-label={`Search ${fieldName}`}
        aria-controls={listId}
        placeholder={`Search ${kind.replace(/_/g, " ")}…`}
        value={query}
        disabled={disabled}
        onChange={(e) => setQuery(e.target.value)}
      />
      <select
        id={listId}
        className="g-host-input"
        aria-label={fieldName}
        value={value}
        disabled={disabled}
        onChange={(e) => {
          const next = e.target.value;
          const picked = listOptions.find((o) => o.value === next);
          setSelectedLabel(picked?.label ?? null);
          onChange(next);
        }}
      >
        <option value="">{optional ? "— none —" : "— select —"}</option>
        {listOptions.map((o) => (
          <option key={o.value} value={o.value}>
            {o.detail ? `${o.label} (${o.detail})` : o.label}
          </option>
        ))}
      </select>
      {loading ? <span className="g-reference-picker__status">Searching…</span> : null}
      {error ? (
        <span role="alert" className="g-property-inspector__error">
          {error}
        </span>
      ) : null}
    </div>
  );
}
