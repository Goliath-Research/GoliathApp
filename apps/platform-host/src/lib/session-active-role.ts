export type RoleGateInput = {
  activeRoleId: number | null;
  selectableCount: number;
  needsSelection: boolean;
};

export function shouldRedirectToRoleSelection(state: RoleGateInput): boolean {
  if (state.activeRoleId != null) {
    return false;
  }
  return state.needsSelection || state.selectableCount > 1;
}

export function shouldRedirectToNoRole(state: RoleGateInput): boolean {
  return state.activeRoleId == null && state.selectableCount === 0;
}
