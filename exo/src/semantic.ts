import postgres from "npm:postgres@3.4.5";

import type { PortalAuthContext } from "./exograph";

type SemanticRow = { result: unknown };

/**
 * Dispatch to portal.sp_run_semantic_request using a direct PostgreSQL client.
 * Exograph's injected Exograph.executeQuery is GraphQL-only and cannot call stored procedures.
 */
export async function runSemanticRequest(
  requestCode: string,
  params: Record<string, unknown> | null,
  version: string,
  auth: PortalAuthContext,
): Promise<unknown> {
  const sessionToken = auth.session_token?.trim();
  if (!sessionToken) {
    throw new Error("missing session_token in JWT context");
  }

  const url = Deno.env.get("EXO_POSTGRES_URL");
  if (!url) {
    throw new Error("EXO_POSTGRES_URL is required");
  }

  const paramsJson = JSON.stringify(params ?? {});
  const versionText = version?.trim() ? version.trim() : "1";

  const sql = postgres(url, { max: 1, prepare: false });
  try {
    const rows = await sql<SemanticRow[]>`
      SELECT r AS result
      FROM portal.sp_run_semantic_request(
        ${sessionToken},
        ${requestCode},
        ${versionText},
        ${sql.json(JSON.parse(paramsJson) as postgres.JSONValue)},
        NULL::jsonb
      ) AS r
    `;
    return rows.map((row) => row.result);
  } finally {
    await sql.end({ timeout: 5 });
  }
}
