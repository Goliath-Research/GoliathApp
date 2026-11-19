import "server-only";

import { portalSessionCall } from "./bridge";

/** Read-only program structure (portal.sp_session_get_domain_program_structure). */
export async function getDomainProgramStructure(
  token: string,
  name: string,
  version: string,
): Promise<Record<string, unknown>> {
  const rows = await portalSessionCall(
    token,
    "SELECT portal.sp_session_get_domain_program_structure($1, $2, $3) AS doc",
    [name, version],
  );
  const value = rows[0] ? Object.values(rows[0])[0] : null;
  return (value ?? {}) as Record<string, unknown>;
}
