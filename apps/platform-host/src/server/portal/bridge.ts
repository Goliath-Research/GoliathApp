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
  nodePath: string | null;
};

export type MetaClassCatalogRow = {
  classId: number;
  className: string;
  parentId: number | null;
  isAbstract: boolean;
};

export type SemanticEntityRow = {
  id: number;
  namespace: string;
  code: string;
  displayName: string;
  schemaVersion: string;
  metaClassName: string | null;
};

export type OperatorViewRow = {
  viewId: number;
  title: string;
  description: string;
  semanticRequestCode: string | null;
  semanticRequestVersion: string;
  metaClassName: string | null;
  paramsJson: Record<string, unknown>;
  updatedAtUtc: string;
};

export type OperatorDashboardRow = {
  dashboardId: number;
  title: string;
  description: string;
  widgetCount: number;
  updatedAtUtc: string;
};

export type OperatorDashboardWidgetRow = {
  viewId: number;
  title: string;
  semanticRequestCode: string | null;
  metaClassName: string | null;
  paramsJson: Record<string, unknown>;
  sortOrder: number;
  columnSpan: number;
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

export class PortalForbiddenError extends Error {
  constructor(message = "forbidden") {
    super(message);
    this.name = "PortalForbiddenError";
  }
}

export class PortalMetaValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PortalMetaValidationError";
  }
}

export type MetaObjectDocumentRow = {
  objId: number;
  classId: number;
  className: string;
  document: unknown;
};

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
  typeKind: string | null;
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
  if (pgCode === "GS403" || message.includes("GS403") || message.includes("permission denied")) {
    if (
      message.includes("meta permission denied") ||
      message.includes("active scope required for meta instance")
    ) {
      throw new PortalForbiddenError("meta permission denied");
    }
    throw new PortalForbiddenError("forbidden");
  }
  if (
    pgCode === "GS404" ||
    message.includes("GS404") ||
    message.includes("meta object not found") ||
    message.includes("meta object scope denied")
  ) {
    if (
      message.includes("meta object not found") ||
      message.includes("meta object scope denied") ||
      (message.includes("object") && message.includes("not found"))
    ) {
      throw new PortalMetaNotFoundError("meta object not found");
    }
    if (message.includes("meta class")) {
      throw new PortalMetaNotFoundError("meta class not found");
    }
    throw new PortalMetaNotFoundError();
  }
  if (
    message.includes("unknown field") ||
    message.includes("missing required field") ||
    message.includes("ValidationError")
  ) {
    throw new PortalMetaValidationError(message);
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
        `SELECT node_id, parent_id, caption, seq, presentation_kind, node_path
         FROM portal.sp_session_operator_nav_tree($1)`,
        [sessionToken],
      );
      return result.rows.map((row) => ({
        nodeId: Number(row.node_id),
        parentId: row.parent_id == null ? null : Number(row.parent_id),
        caption: String(row.caption),
        seq: Number(row.seq),
        presentationKind: String(row.presentation_kind),
        nodePath: row.node_path == null ? null : String(row.node_path),
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
        `SELECT field_name, type_id, type_name, type_kind, required, declared_on_class_id,
                declared_on_class_name, defined_at_depth, is_local
         FROM portal.sp_session_meta_class_fields($1, $2)`,
        [sessionToken, className],
      );
      return result.rows.map((row) => ({
        fieldName: String(row.field_name),
        typeId: row.type_id == null ? null : Number(row.type_id),
        typeName: row.type_name == null ? null : String(row.type_name),
        typeKind: row.type_kind == null ? null : String(row.type_kind),
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

export async function portalSessionMetaObjInsert(
  sessionToken: string,
  className: string,
  document: unknown,
): Promise<number> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT portal.sp_session_meta_obj_insert($1, $2, $3::jsonb) AS obj_id`,
        [sessionToken, className, JSON.stringify(document ?? {})],
      );
      const objId = result.rows[0]?.obj_id;
      if (objId == null) {
        throw new Error("sp_session_meta_obj_insert returned no row");
      }
      return Number(objId);
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionMetaObjUpdate(
  sessionToken: string,
  objId: number,
  document: unknown,
): Promise<void> {
  return withClient(async (client) => {
    try {
      await client.query(`SELECT portal.sp_session_meta_obj_update($1, $2, $3::jsonb)`, [
        sessionToken,
        objId,
        JSON.stringify(document ?? {}),
      ]);
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export type MetaDataTypeRow = {
  id: number;
  name: string;
  version: string;
  status: string;
  kind: string;
  elementTypeId: number | null;
  elementTypeName: string | null;
  schemaJson: unknown;
};

export async function portalSessionGetDataType(
  sessionToken: string,
  typeName: string,
  version: string | null = null,
): Promise<MetaDataTypeRow> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT id, name, version, status, kind, element_type_id, element_type_name, schema_json
         FROM portal.sp_session_get_data_type($1, $2, $3)`,
        [sessionToken, typeName, version],
      );
      const row = result.rows[0];
      if (!row) throw new PortalMetaNotFoundError("data type not found");
      return {
        id: Number(row.id),
        name: String(row.name),
        version: String(row.version),
        status: String(row.status),
        kind: String(row.kind),
        elementTypeId: row.element_type_id == null ? null : Number(row.element_type_id),
        elementTypeName: row.element_type_name == null ? null : String(row.element_type_name),
        schemaJson: row.schema_json,
      };
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionMetaObjGet(
  sessionToken: string,
  objId: number,
): Promise<MetaObjectDocumentRow> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT obj_id, class_id, class_name, document
         FROM portal.sp_session_meta_obj_get($1, $2)`,
        [sessionToken, objId],
      );
      const row = result.rows[0];
      if (!row) {
        throw new PortalMetaNotFoundError("meta object not found");
      }
      return {
        objId: Number(row.obj_id),
        classId: Number(row.class_id),
        className: String(row.class_name),
        document: row.document,
      };
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionMetaListClasses(sessionToken: string): Promise<MetaClassCatalogRow[]> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT class_id, class_name, parent_id, is_abstract
         FROM portal.sp_session_meta_list_classes($1)`,
        [sessionToken],
      );
      return result.rows.map((row) => ({
        classId: Number(row.class_id),
        className: String(row.class_name),
        parentId: row.parent_id == null ? null : Number(row.parent_id),
        isAbstract: Boolean(row.is_abstract),
      }));
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionSemanticEntities(
  sessionToken: string,
): Promise<SemanticEntityRow[]> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT id, namespace, code, display_name, schema_version, meta_class_name
         FROM portal.sp_session_list_semantic_entities_enriched($1)`,
        [sessionToken],
      );
      return result.rows.map((row) => ({
        id: Number(row.id),
        namespace: String(row.namespace),
        code: String(row.code),
        displayName: String(row.display_name),
        schemaVersion: String(row.schema_version),
        metaClassName: row.meta_class_name == null ? null : String(row.meta_class_name),
      }));
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionPlatformQuery(
  sessionToken: string,
  sql: string,
): Promise<Record<string, unknown>[]> {
  return withClient(async (client) => {
    try {
      const result = await client.query(sql, [sessionToken]);
      return result.rows.map((row) => {
        const out: Record<string, unknown> = {};
        for (const [key, value] of Object.entries(row)) {
          out[key] = value;
        }
        return out;
      });
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionRunSemanticRequest(
  sessionToken: string,
  requestCode: string,
  paramsJson: Record<string, unknown> = {},
  version = "1",
): Promise<Record<string, unknown>[]> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT * FROM portal.sp_run_semantic_request($1, $2, $3, $4::jsonb, NULL::jsonb)`,
        [sessionToken, requestCode, version, JSON.stringify(paramsJson)],
      );
      return result.rows.map((row) => {
        const value = Object.values(row)[0];
        return (typeof value === "object" && value !== null ? value : {}) as Record<string, unknown>;
      });
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionListOperatorViews(sessionToken: string): Promise<OperatorViewRow[]> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT view_id, title, description, semantic_request_code, semantic_request_version,
                meta_class_name, params_json, updated_at_utc
         FROM portal.sp_session_list_operator_views($1)`,
        [sessionToken],
      );
      return result.rows.map((row) => ({
        viewId: Number(row.view_id),
        title: String(row.title),
        description: String(row.description ?? ""),
        semanticRequestCode: row.semantic_request_code == null ? null : String(row.semantic_request_code),
        semanticRequestVersion: String(row.semantic_request_version ?? "1"),
        metaClassName: row.meta_class_name == null ? null : String(row.meta_class_name),
        paramsJson: (row.params_json ?? {}) as Record<string, unknown>,
        updatedAtUtc: String(row.updated_at_utc),
      }));
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionUpsertOperatorView(
  sessionToken: string,
  body: {
    viewId?: number;
    title: string;
    description?: string;
    semanticRequestCode?: string | null;
    semanticRequestVersion?: string;
    metaClassName?: string | null;
    paramsJson?: Record<string, unknown>;
  },
): Promise<number> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT view_id FROM portal.sp_session_upsert_operator_view(
           $1, $2, $3, $4, $5, $6, $7, $8::jsonb
         )`,
        [
          sessionToken,
          body.viewId ?? null,
          body.title,
          body.description ?? "",
          body.semanticRequestCode ?? null,
          body.semanticRequestVersion ?? "1",
          body.metaClassName ?? null,
          JSON.stringify(body.paramsJson ?? {}),
        ],
      );
      return Number(result.rows[0]?.view_id);
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionListOperatorDashboards(
  sessionToken: string,
): Promise<OperatorDashboardRow[]> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT dashboard_id, title, description, widget_count, updated_at_utc
         FROM portal.sp_session_list_operator_dashboards($1)`,
        [sessionToken],
      );
      return result.rows.map((row) => ({
        dashboardId: Number(row.dashboard_id),
        title: String(row.title),
        description: String(row.description ?? ""),
        widgetCount: Number(row.widget_count),
        updatedAtUtc: String(row.updated_at_utc),
      }));
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionUpsertOperatorDashboard(
  sessionToken: string,
  body: { dashboardId?: number; title: string; description?: string },
): Promise<number> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT dashboard_id FROM portal.sp_session_upsert_operator_dashboard($1, $2, $3, $4)`,
        [sessionToken, body.dashboardId ?? null, body.title, body.description ?? ""],
      );
      return Number(result.rows[0]?.dashboard_id);
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionListDashboardWidgets(
  sessionToken: string,
  dashboardId: number,
): Promise<OperatorDashboardWidgetRow[]> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT view_id, title, semantic_request_code, meta_class_name, params_json, sort_order, column_span
         FROM portal.sp_session_list_dashboard_widgets($1, $2)`,
        [sessionToken, dashboardId],
      );
      return result.rows.map((row) => ({
        viewId: Number(row.view_id),
        title: String(row.title),
        semanticRequestCode: row.semantic_request_code == null ? null : String(row.semantic_request_code),
        metaClassName: row.meta_class_name == null ? null : String(row.meta_class_name),
        paramsJson: (row.params_json ?? {}) as Record<string, unknown>,
        sortOrder: Number(row.sort_order),
        columnSpan: Number(row.column_span),
      }));
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionSetDashboardWidgets(
  sessionToken: string,
  dashboardId: number,
  widgets: Array<{ viewId: number; sortOrder: number; columnSpan: number }>,
): Promise<number> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT widget_count FROM portal.sp_session_set_dashboard_widgets($1, $2, $3::jsonb)`,
        [
          sessionToken,
          dashboardId,
          JSON.stringify(
            widgets.map((w) => ({
              view_id: w.viewId,
              sort_order: w.sortOrder,
              column_span: w.columnSpan,
            })),
          ),
        ],
      );
      return Number(result.rows[0]?.widget_count ?? 0);
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}
