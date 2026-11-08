import "server-only";

import type { Pool, PoolClient, QueryResultRow } from "pg";
import { Pool as PgPool } from "pg";
import { resolvePortalBridgeConfig } from "./env";

export type ResolvedPortalSession = {
  sessionId: number;
  userId: number;
  email: string;
  fullName: string;
  activeScopeId: number | null;
  expiresAtUtc: Date;
  revoked: boolean;
};

export type OperatorNavRow = {
  nodeId: number;
  parentId: number | null;
  caption: string;
  seq: number;
  presentationKind: string;
};

let pool: Pool | null = null;

export function isPortalBridgeConfigured(): boolean {
  return resolvePortalBridgeConfig() !== null;
}

function getPool(): Pool {
  const cfg = resolvePortalBridgeConfig();
  if (!cfg) {
    throw new PortalBridgeMisconfiguredError();
  }
  if (!pool) {
    pool = new PgPool({ connectionString: cfg.connString, max: 5 });
  }
  return pool;
}

export class PortalBridgeMisconfiguredError extends Error {
  constructor() {
    super("Portal database bridge is not configured");
    this.name = "PortalBridgeMisconfiguredError";
  }
}

export class PortalSessionDeniedError extends Error {
  constructor(message = "session denied") {
    super(message);
    this.name = "PortalSessionDeniedError";
  }
}

async function withClient<T>(fn: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await getPool().connect();
  try {
    return await fn(client);
  } finally {
    client.release();
  }
}

function mapSessionRow(row: QueryResultRow | undefined): ResolvedPortalSession | null {
  if (!row || row.session_id == null) return null;
  if (row.revoked) return null;
  return {
    sessionId: Number(row.session_id),
    userId: Number(row.user_id),
    email: String(row.email ?? ""),
    fullName: String(row.full_name ?? ""),
    activeScopeId: row.active_scope_id == null ? null : Number(row.active_scope_id),
    expiresAtUtc: new Date(String(row.expires_at_utc)),
    revoked: Boolean(row.revoked),
  };
}

export async function portalSessionResolve(sessionToken: string): Promise<ResolvedPortalSession | null> {
  return withClient(async (client) => {
    const result = await client.query(
      `SELECT session_id, user_id, email, full_name, active_scope_id, expires_at_utc, revoked
       FROM portal.fn_session_resolve($1) LIMIT 1`,
      [sessionToken],
    );
    return mapSessionRow(result.rows[0]);
  });
}

export async function portalSessionOpen(
  userId: number,
  activeScopeId?: number | null,
): Promise<{ sessionToken: string; expiresAtUtc: Date }> {
  return withClient(async (client) => {
    const result = await client.query(
      `SELECT session_token, expires_at_utc
       FROM portal.sp_session_open($1, $2, NULL, NULL)`,
      [userId, activeScopeId ?? null],
    );
    const row = result.rows[0];
    if (!row?.session_token) {
      throw new Error("sp_session_open returned no row");
    }
    return {
      sessionToken: String(row.session_token),
      expiresAtUtc: new Date(String(row.expires_at_utc)),
    };
  });
}

export async function portalSessionTouch(sessionToken: string): Promise<boolean> {
  return withClient(async (client) => {
    const result = await client.query(`SELECT portal.sp_session_touch($1) AS ok`, [sessionToken]);
    return Boolean(result.rows[0]?.ok);
  });
}

export async function portalSessionRevoke(sessionToken: string): Promise<boolean> {
  return withClient(async (client) => {
    const result = await client.query(`SELECT revoked FROM portal.sp_session_revoke($1)`, [sessionToken]);
    return Boolean(result.rows[0]?.revoked);
  });
}

export async function portalOperatorNavTree(sessionToken: string): Promise<OperatorNavRow[]> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT node_id, parent_id, caption, seq, presentation_kind
         FROM portal.sp_session_operator_nav_tree($1)`,
        [sessionToken],
      );
      return result.rows.map((row) => ({
        nodeId: Number(row.node_id),
        parentId: row.parent_id == null ? null : Number(row.parent_id),
        caption: String(row.caption),
        seq: Number(row.seq),
        presentationKind: String(row.presentation_kind),
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes("GS401")) {
        throw new PortalSessionDeniedError();
      }
      throw err;
    }
  });
}
