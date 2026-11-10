export type ScopedRoleGrantRow = {
  grant_id: number;
  role_name: string;
  scope_name?: string | null;
};

export function formatRoleGrantLabel(grant: ScopedRoleGrantRow): string {
  const scope = grant.scope_name?.trim() || "Scope";
  return `${grant.role_name} (${scope})`;
}

export function formatRoleGrantsSummary(grants: ScopedRoleGrantRow[]): string {
  if (grants.length === 0) {
    return "None — grant role";
  }
  return grants.map(formatRoleGrantLabel).join(", ");
}
