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

export class PortalMetaNotFoundError extends Error {
  constructor(message = "meta class not found") {
    super(message);
    this.name = "PortalMetaNotFoundError";
  }
}

export type MetaClassSummaryRow = {
  classId: number;
  className: string;
  parentId: number | null;
  parentName: string | null;
  depth: number;
  isAbstract: boolean;
  catalogTypeName: string;
  schemaFlattenedJson: unknown;
  schemaBundledJson: unknown;
};

export type MetaClassLineageRow = {
  lineageRole: "ancestor" | "self" | "descendant";
  classId: number;
  className: string;
  parentId: number | null;
  depth: number;
  relationDepth: number;
};

export type MetaClassFieldRow = {
  fieldName: string;
  typeId: number | null;
  typeName: string | null;
  required: boolean;
  declaredOnClassId: number;
  declaredOnClassName: string;
  definedAtDepth: number;
  isLocal: boolean;
};

function mapPgPortalError(err: unknown): never {
  const pgCode =
    err && typeof err === "object" && "code" in err ? String((err as { code: string }).code) : "";
  const message = err instanceof Error ? err.message : String(err);
  if (pgCode === "GS401" || message.includes("GS401") || message.includes("session denied")) {
    throw new PortalSessionDeniedError();
  }
  if (pgCode === "GS404" || message.includes("GS404") || message.includes("not found")) {
    throw new PortalMetaNotFoundError();
  }
  throw err;
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

export async function portalSessionOpenForScopeIdentity(
  scopeId: number,
  issuer: string,
  subject: string,
  authSubjectSnapshot: string,
): Promise<{ sessionToken: string; expiresAtUtc: Date; userId: number }> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT session_token, expires_at_utc, user_id
         FROM portal.sp_session_open_for_scope_identity($1, $2, $3, $4)`,
        [scopeId, issuer, subject, authSubjectSnapshot],
      );
      const row = result.rows[0];
      if (!row?.session_token) {
        throw new PortalSessionDeniedError("login denied");
      }
      return {
        sessionToken: String(row.session_token),
        expiresAtUtc: new Date(String(row.expires_at_utc)),
        userId: Number(row.user_id),
      };
    } catch (err) {
      const pgCode =
        err && typeof err === "object" && "code" in err ? String((err as { code: string }).code) : "";
      const message = err instanceof Error ? err.message : String(err);
      if (pgCode === "GS403" || message.includes("GS403") || message.includes("not linked")) {
        throw new PortalSessionDeniedError("external identity is not linked");
      }
      if (pgCode === "GS401" || message.includes("GS401")) {
        throw new PortalSessionDeniedError();
      }
      throw err;
    }
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
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionMetaClassGet(
  sessionToken: string,
  className: string,
): Promise<MetaClassSummaryRow> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT class_id, class_name, parent_id, parent_name, depth, is_abstract,
                catalog_type_name, schema_flattened_json, schema_bundled_json
         FROM portal.sp_session_meta_class_get($1, $2)`,
        [sessionToken, className],
      );
      const row = result.rows[0];
      if (!row) throw new PortalMetaNotFoundError();
      return {
        classId: Number(row.class_id),
        className: String(row.class_name),
        parentId: row.parent_id == null ? null : Number(row.parent_id),
        parentName: row.parent_name == null ? null : String(row.parent_name),
        depth: Number(row.depth),
        isAbstract: Boolean(row.is_abstract),
        catalogTypeName: String(row.catalog_type_name),
        schemaFlattenedJson: row.schema_flattened_json,
        schemaBundledJson: row.schema_bundled_json,
      };
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionMetaClassLineage(
  sessionToken: string,
  className: string,
): Promise<MetaClassLineageRow[]> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT lineage_role, class_id, class_name, parent_id, depth, relation_depth
         FROM portal.sp_session_meta_class_lineage($1, $2)`,
        [sessionToken, className],
      );
      return result.rows.map((row) => ({
        lineageRole: String(row.lineage_role) as MetaClassLineageRow["lineageRole"],
        classId: Number(row.class_id),
        className: String(row.class_name),
        parentId: row.parent_id == null ? null : Number(row.parent_id),
        depth: Number(row.depth),
        relationDepth: Number(row.relation_depth),
      }));
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionMetaClassFields(
  sessionToken: string,
  className: string,
): Promise<MetaClassFieldRow[]> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT field_name, type_id, type_name, required, declared_on_class_id,
                declared_on_class_name, defined_at_depth, is_local
         FROM portal.sp_session_meta_class_fields($1, $2)`,
        [sessionToken, className],
      );
      return result.rows.map((row) => ({
        fieldName: String(row.field_name),
        typeId: row.type_id == null ? null : Number(row.type_id),
        typeName: row.type_name == null ? null : String(row.type_name),
        required: Boolean(row.required),
        declaredOnClassId: Number(row.declared_on_class_id),
        declaredOnClassName: String(row.declared_on_class_name),
        definedAtDepth: Number(row.defined_at_depth),
        isLocal: Boolean(row.is_local),
      }));
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}
