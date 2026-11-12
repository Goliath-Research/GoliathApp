"use client";

import { createContext, useContext, type ReactNode } from "react";

/** One selectable existing row for a reference field. */
export type ReferenceOption = {
  /** Stored value (string form; integer refs are coerced on save). */
  value: string;
  label: string;
  detail?: string | null;
};

/** Host-provided catalog search used by reference pickers at any nesting depth. */
export type ReferenceResolver = {
  search(kind: string, query: string, options?: { limit?: number }): Promise<ReferenceOption[]>;
};

const ReferenceResolverContext = createContext<ReferenceResolver | null>(null);

export function ReferenceResolverProvider({
  resolver,
  children,
}: {
  resolver: ReferenceResolver;
  children: ReactNode;
}) {
  return <ReferenceResolverContext.Provider value={resolver}>{children}</ReferenceResolverContext.Provider>;
}

export function useReferenceResolver(): ReferenceResolver | null {
  return useContext(ReferenceResolverContext);
}
