import "server-only";

import type { Pool, PoolClient, QueryResultRow } from "pg";
import { Pool as PgPool } from "pg";
import { isAnyProductBridgeConfigured } from "../product/portal-db";
import { getRequestProductDefinition } from "../product/request-product";
import { resolvePortalBridgeConfig } from "./env";

export type ResolvedPortalSession = {
  sessionId: number;
  userId: number;
  email: string;
  fullName: string;
  activeScopeId: number | null;
  activeRoleId: number | null;
  activeRoleName: string | null;
  expiresAtUtc: Date;
  revoked: boolean;
};

export type PortalActiveRoleState = {
  activeRoleId: number | null;
  activeRoleName: string | null;
  selectableCount: number;
  needsSelection: boolean;
};

export type SelectablePortalRole = {
  roleId: number;
  roleName: string;
};

export type OperatorNavRow = {
  nodeId: number;
  parentId: number | null;
  caption: string;
  seq: number;
  presentationKind: string;
  nodePath: string | null;
  navInfoName: string | null;
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
  visibility: string;
  metaObjId: number | null;
  updatedAtUtc: string;
};

export type OperatorDashboardRow = {
  dashboardId: number;
  title: string;
  description: string;
  layoutJson: Record<string, unknown>;
  visibility: string;
  metaObjId: number | null;
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
  gridX: number;
  gridY: number;
  gridW: number;
  gridH: number;
  widgetTitle: string;
  vizOverrideJson: Record<string, unknown>;
};

export type SemanticFieldRow = {
  fieldCode: string;
  columnName: string;
  jsonType: string;
  role: string;
};

const pools = new Map<string, Pool>();

export function isPortalBridgeConfigured(): boolean {
  return isAnyProductBridgeConfigured();
}

async function getPool(): Promise<Pool> {
  const product = await getRequestProductDefinition();
  const cfg = resolvePortalBridgeConfig(product);
  if (!cfg) {
    throw new PortalBridgeMisconfiguredError();
  }
  let pool = pools.get(cfg.productId);
  if (!pool) {
    pool = new PgPool({ connectionString: cfg.connString, max: 5 });
    pools.set(cfg.productId, pool);
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

export class PortalMetaConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PortalMetaConflictError";
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

export function portalBridgeErrorMessage(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err);
  const gs = message.match(/\bGS\d{3}\b[:\s]+(.+)/i);
  if (gs?.[1]) {
    return gs[1].trim();
  }
  if (message.includes("BusinessRule:")) {
    return message.split("BusinessRule:")[1]?.trim() ?? message;
  }
  if (message.includes("ValidationError:")) {
    return message.split("ValidationError:")[1]?.trim() ?? message;
  }
  return message;
}

export function logPortalBridgeError(context: string, err: unknown): void {
  const pgCode =
    err && typeof err === "object" && "code" in err ? String((err as { code: string }).code) : "";
  const detail =
    err && typeof err === "object" && "detail" in err ? String((err as { detail?: string }).detail ?? "") : "";
  const safeMessage = portalBridgeErrorMessage(err).slice(0, 500);
  console.error(`[portal-bridge] ${context}`, {
    pgCode: pgCode || undefined,
    detail: detail || undefined,
    message: safeMessage,
  });
}

function mapPgPortalError(err: unknown): never {
  const pgCode =
    err && typeof err === "object" && "code" in err ? String((err as { code: string }).code) : "";
  const message = err instanceof Error ? err.message : String(err);
  const friendly = portalBridgeErrorMessage(err);
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
    throw new PortalForbiddenError(friendly);
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
  if (pgCode === "GS400" || message.includes("GS400")) {
    throw new PortalMetaValidationError(friendly);
  }
  if (pgCode === "GS409" || message.includes("GS409") || message.includes("already exists")) {
    throw new PortalMetaConflictError(friendly);
  }
  if (pgCode === "23502" || pgCode === "23503" || pgCode === "23505") {
    throw new PortalMetaValidationError(
      pgCode === "23505" ? "a conflicting record already exists" : "invalid or incomplete data",
    );
  }
  if (
    message.includes("unknown field") ||
    message.includes("missing required field") ||
    message.includes("ValidationError")
  ) {
    throw new PortalMetaValidationError(friendly);
  }
  if (message.includes("BusinessRule:")) {
    throw new PortalMetaValidationError(friendly);
  }
  logPortalBridgeError("unmapped database error", err);
  throw err;
}

async function withClient<T>(fn: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await (await getPool()).connect();
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
    activeRoleId: row.active_role_id == null ? null : Number(row.active_role_id),
    activeRoleName: row.active_role_name == null ? null : String(row.active_role_name),
    expiresAtUtc: new Date(String(row.expires_at_utc)),
    revoked: Boolean(row.revoked),
  };
}

export async function portalSessionResolve(sessionToken: string): Promise<ResolvedPortalSession | null> {
  return withClient(async (client) => {
    const result = await client.query(
      `SELECT session_id, user_id, email, full_name, active_scope_id,
              active_role_id, active_role_name, expires_at_utc, revoked
       FROM portal.fn_session_resolve($1) LIMIT 1`,
      [sessionToken],
    );
    return mapSessionRow(result.rows[0]);
  });
}

export async function portalActiveRoleState(sessionToken: string): Promise<PortalActiveRoleState> {
  return withClient(async (client) => {
    const result = await client.query(
      `SELECT active_role_id, active_role_name, selectable_count, needs_selection
       FROM portal.sp_session_get_active_role_state($1)`,
      [sessionToken],
    );
    const row = result.rows[0];
    if (!row) {
      throw new PortalSessionDeniedError();
    }
    return {
      activeRoleId: row.active_role_id == null ? null : Number(row.active_role_id),
      activeRoleName: row.active_role_name == null ? null : String(row.active_role_name),
      selectableCount: Number(row.selectable_count ?? 0),
      needsSelection: Boolean(row.needs_selection),
    };
  });
}

export async function portalAutoSelectActiveRole(sessionToken: string): Promise<void> {
  await withClient(async (client) => {
    await client.query(`SELECT role_id, auto_selected FROM portal.sp_session_auto_select_active_role($1)`, [
      sessionToken,
    ]);
  });
}

export async function portalListSelectableRoles(sessionToken: string): Promise<SelectablePortalRole[]> {
  return withClient(async (client) => {
    const result = await client.query(
      `SELECT role_id, role_name FROM portal.sp_session_list_selectable_roles($1)`,
      [sessionToken],
    );
    return result.rows.map((row) => ({
      roleId: Number(row.role_id),
      roleName: String(row.role_name ?? ""),
    }));
  });
}

export async function portalSetActiveRole(
  sessionToken: string,
  roleId: number,
): Promise<{ roleId: number; roleName: string }> {
  return withClient(async (client) => {
    const result = await client.query(
      `SELECT role_id, role_name FROM portal.sp_session_set_active_role($1, $2)`,
      [sessionToken, roleId],
    );
    const row = result.rows[0];
    if (!row) {
      throw new PortalSessionDeniedError("active role not set");
    }
    return {
      roleId: Number(row.role_id),
      roleName: String(row.role_name ?? ""),
    };
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
        `SELECT node_id, parent_id, caption, seq, presentation_kind, node_path, nav_info_name
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
        navInfoName: row.nav_info_name == null ? null : String(row.nav_info_name),
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
                meta_class_name, params_json, visibility, meta_obj_id, updated_at_utc
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
        visibility: String(row.visibility ?? "scope"),
        metaObjId: row.meta_obj_id == null ? null : Number(row.meta_obj_id),
        updatedAtUtc: String(row.updated_at_utc),
      }));
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionGetOperatorView(
  sessionToken: string,
  viewId: number,
): Promise<OperatorViewRow> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT view_id, title, description, semantic_request_code, semantic_request_version,
                meta_class_name, params_json, visibility, meta_obj_id, updated_at_utc
         FROM portal.sp_session_get_operator_view($1, $2)`,
        [sessionToken, viewId],
      );
      const row = result.rows[0];
      if (!row) {
        throw new PortalMetaNotFoundError("operator view not found");
      }
      return {
        viewId: Number(row.view_id),
        title: String(row.title),
        description: String(row.description ?? ""),
        semanticRequestCode: row.semantic_request_code == null ? null : String(row.semantic_request_code),
        semanticRequestVersion: String(row.semantic_request_version ?? "1"),
        metaClassName: row.meta_class_name == null ? null : String(row.meta_class_name),
        paramsJson: (row.params_json ?? {}) as Record<string, unknown>,
        visibility: String(row.visibility ?? "scope"),
        metaObjId: row.meta_obj_id == null ? null : Number(row.meta_obj_id),
        updatedAtUtc: String(row.updated_at_utc),
      };
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionDeleteOperatorView(
  sessionToken: string,
  viewId: number,
): Promise<boolean> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT deleted FROM portal.sp_session_delete_operator_view($1, $2)`,
        [sessionToken, viewId],
      );
      return Boolean(result.rows[0]?.deleted);
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
    visibility?: string;
  },
): Promise<number> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT view_id FROM portal.sp_session_upsert_operator_view(
           $1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9
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
          body.visibility ?? null,
        ],
      );
      return Number(result.rows[0]?.view_id);
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionSemanticFieldsForRequest(
  sessionToken: string,
  requestCode: string,
): Promise<SemanticFieldRow[]> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT field_code, column_name, json_type, role
         FROM portal.sp_session_semantic_fields_for_request($1, $2)`,
        [sessionToken, requestCode],
      );
      return result.rows.map((row) => ({
        fieldCode: String(row.field_code),
        columnName: String(row.column_name),
        jsonType: String(row.json_type),
        role: String(row.role),
      }));
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
        `SELECT dashboard_id, title, description, layout_json, visibility, meta_obj_id,
                widget_count, updated_at_utc
         FROM portal.sp_session_list_operator_dashboards($1)`,
        [sessionToken],
      );
      return result.rows.map((row) => ({
        dashboardId: Number(row.dashboard_id),
        title: String(row.title),
        description: String(row.description ?? ""),
        layoutJson: (row.layout_json ?? {}) as Record<string, unknown>,
        visibility: String(row.visibility ?? "scope"),
        metaObjId: row.meta_obj_id == null ? null : Number(row.meta_obj_id),
        widgetCount: Number(row.widget_count),
        updatedAtUtc: String(row.updated_at_utc),
      }));
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionGetOperatorDashboard(
  sessionToken: string,
  dashboardId: number,
): Promise<OperatorDashboardRow> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT dashboard_id, title, description, layout_json, visibility, meta_obj_id, updated_at_utc
         FROM portal.sp_session_get_operator_dashboard($1, $2)`,
        [sessionToken, dashboardId],
      );
      const row = result.rows[0];
      if (!row) {
        throw new PortalMetaNotFoundError("dashboard not found");
      }
      return {
        dashboardId: Number(row.dashboard_id),
        title: String(row.title),
        description: String(row.description ?? ""),
        layoutJson: (row.layout_json ?? {}) as Record<string, unknown>,
        visibility: String(row.visibility ?? "scope"),
        metaObjId: row.meta_obj_id == null ? null : Number(row.meta_obj_id),
        widgetCount: 0,
        updatedAtUtc: String(row.updated_at_utc),
      };
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionDeleteOperatorDashboard(
  sessionToken: string,
  dashboardId: number,
): Promise<boolean> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT deleted FROM portal.sp_session_delete_operator_dashboard($1, $2)`,
        [sessionToken, dashboardId],
      );
      return Boolean(result.rows[0]?.deleted);
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionUpsertOperatorDashboard(
  sessionToken: string,
  body: {
    dashboardId?: number;
    title: string;
    description?: string;
    layoutJson?: Record<string, unknown>;
    visibility?: string;
  },
): Promise<number> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT dashboard_id FROM portal.sp_session_upsert_operator_dashboard(
           $1, $2, $3, $4, $5::jsonb, $6
         )`,
        [
          sessionToken,
          body.dashboardId ?? null,
          body.title,
          body.description ?? "",
          JSON.stringify(body.layoutJson ?? {}),
          body.visibility ?? null,
        ],
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
        `SELECT view_id, title, semantic_request_code, meta_class_name, params_json, sort_order, column_span,
                grid_x, grid_y, grid_w, grid_h, widget_title, viz_override_json
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
        gridX: Number(row.grid_x ?? 0),
        gridY: Number(row.grid_y ?? 0),
        gridW: Number(row.grid_w ?? 4),
        gridH: Number(row.grid_h ?? 2),
        widgetTitle: String(row.widget_title ?? ""),
        vizOverrideJson: (row.viz_override_json ?? {}) as Record<string, unknown>,
      }));
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionSetDashboardWidgets(
  sessionToken: string,
  dashboardId: number,
  widgets: Array<{
    viewId: number;
    sortOrder: number;
    columnSpan: number;
    gridX?: number;
    gridY?: number;
    gridW?: number;
    gridH?: number;
    widgetTitle?: string;
    vizOverride?: Record<string, unknown>;
  }>,
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
              grid_x: w.gridX ?? 0,
              grid_y: w.gridY ?? 0,
              grid_w: w.gridW ?? 4,
              grid_h: w.gridH ?? 2,
              widget_title: w.widgetTitle ?? "",
              viz_override: w.vizOverride ?? {},
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

export async function portalSessionExportModelPackage(
  sessionToken: string,
  classPrefix: string,
): Promise<string> {
  return withClient(async (client) => {
    try {
      const result = await client.query(
        `SELECT package_sql FROM portal.sp_session_export_model_package($1, $2)`,
        [sessionToken, classPrefix],
      );
      return String(result.rows[0]?.package_sql ?? "");
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionModelAuthoring(
  sessionToken: string,
  action: string,
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return withClient(async (client) => {
    try {
      switch (action) {
        case "meta_class_create": {
          const result = await client.query(
            `SELECT class_id, class_name FROM portal.sp_session_meta_class_create($1, $2, $3)`,
            [sessionToken, String(body.className ?? ""), body.parentClassName ?? null],
          );
          return { classId: result.rows[0]?.class_id, className: result.rows[0]?.class_name };
        }
        case "meta_field_upsert": {
          const result = await client.query(
            `SELECT field_id FROM portal.sp_session_meta_field_upsert($1, $2, $3, $4, $5, $6)`,
            [
              sessionToken,
              String(body.className ?? ""),
              String(body.fieldName ?? ""),
              String(body.typeName ?? "portal/nav/Caption"),
              String(body.typeVersion ?? "1.0"),
              Boolean(body.required),
            ],
          );
          return { fieldId: result.rows[0]?.field_id };
        }
        case "meta_field_retire": {
          await client.query(`SELECT ok FROM portal.sp_session_meta_field_retire($1, $2, $3)`, [
            sessionToken,
            String(body.className ?? ""),
            String(body.fieldName ?? ""),
          ]);
          return { ok: true };
        }
        case "semantic_register_entity": {
          const result = await client.query(
            `SELECT entity_id FROM portal.sp_session_semantic_register_entity($1, $2, $3, $4, $5, $6)`,
            [
              sessionToken,
              String(body.namespace ?? ""),
              String(body.code ?? ""),
              String(body.displayName ?? ""),
              String(body.description ?? ""),
              body.metaClassName ?? null,
            ],
          );
          return { entityId: result.rows[0]?.entity_id };
        }
        case "semantic_register_attribute": {
          await client.query(
            `SELECT ok FROM portal.sp_session_semantic_register_attribute($1, $2, $3, $4, $5, $6, $7)`,
            [
              sessionToken,
              Number(body.entityId),
              String(body.code ?? ""),
              String(body.columnName ?? ""),
              String(body.jsonType ?? "string"),
              String(body.role ?? "dimension"),
              Array.isArray(body.filterableOps) ? body.filterableOps : ["eq"],
            ],
          );
          return { ok: true };
        }
        case "nav_register_node": {
          const result = await client.query(
            `SELECT node_id FROM portal.sp_session_nav_register_node($1, $2, $3, $4, $5)`,
            [
              sessionToken,
              body.parentNavId == null ? null : Number(body.parentNavId),
              String(body.caption ?? ""),
              Number(body.seq ?? 50),
              body.nodePath == null ? null : String(body.nodePath),
            ],
          );
          return { nodeId: result.rows[0]?.node_id };
        }
        case "grant_role_nav_node": {
          await client.query(`SELECT ok FROM portal.sp_session_grant_role_nav_node($1, $2, $3)`, [
            sessionToken,
            Number(body.roleId),
            Number(body.nodeId),
          ]);
          return { ok: true };
        }
        case "grant_user_role": {
          const result = await client.query(
            `SELECT inserted, grant_id FROM portal.sp_session_grant_user_role_scoped($1, $2, $3)`,
            [sessionToken, Number(body.targetUserId), Number(body.roleId)],
          );
          return { inserted: result.rows[0]?.inserted, grantId: result.rows[0]?.grant_id };
        }
        default:
          throw new Error("unknown model authoring action");
      }
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}

export async function portalSessionSecurity(
  sessionToken: string,
  action: string,
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return withClient(async (client) => {
    try {
      switch (action) {
        case "upsert_user": {
          const result = await client.query(
            `SELECT user_id FROM portal.sp_session_upsert_user($1, $2, $3, $4)`,
            [sessionToken, String(body.email ?? ""), String(body.fullName ?? ""), Number(body.active ?? 1)],
          );
          return { userId: result.rows[0]?.user_id };
        }
        case "grant_user_role": {
          const result = await client.query(
            `SELECT inserted, grant_id FROM portal.sp_session_grant_user_role_admin($1, $2, $3)`,
            [sessionToken, Number(body.targetUserId), Number(body.roleId)],
          );
          return { inserted: result.rows[0]?.inserted, grantId: result.rows[0]?.grant_id };
        }
        case "list_user_role_grants": {
          const result = await client.query(
            `SELECT grant_id, user_id, role_id, role_name, grant_type, scope_id, scope_name
             FROM portal.sp_session_list_user_role_grants_scoped($1, $2)`,
            [sessionToken, Number(body.targetUserId)],
          );
          return { grants: result.rows };
        }
        case "revoke_user_role_grant": {
          const grantId = Number(body.grantId);
          if (!Number.isFinite(grantId) || grantId <= 0) {
            throw new PortalMetaValidationError("grant id is required");
          }
          const result = await client.query(
            `SELECT revoked FROM portal.sp_session_revoke_user_role_grant($1, $2)`,
            [sessionToken, grantId],
          );
          return { revoked: result.rows[0]?.revoked };
        }
        case "list_scope_identity_providers": {
          const result = await client.query(
            `SELECT provider_id, provider_name, issuer FROM portal.sp_session_list_scope_identity_providers($1)`,
            [sessionToken],
          );
          return { providers: result.rows };
        }
        case "list_users_admin": {
          const result = await client.query(
            `SELECT user_id, full_name, email, active, scoped_role_count, sign_in_status,
                    identity_provider_name, active_roles_summary
             FROM portal.sp_session_list_users_admin($1)`,
            [sessionToken],
          );
          return { users: result.rows };
        }
        case "invite_user": {
          const roleId = Number(body.defaultRoleId);
          if (!Number.isFinite(roleId) || roleId <= 0) {
            throw new PortalMetaValidationError("default role is required");
          }
          const providerRaw = body.expectedProviderId;
          const providerId =
            providerRaw == null || providerRaw === ""
              ? null
              : Number(providerRaw);
          if (providerId != null && (!Number.isFinite(providerId) || providerId <= 0)) {
            throw new PortalMetaValidationError("invalid identity provider");
          }
          const result = await client.query(
            `SELECT invitation_id FROM portal.sp_session_create_invitation_scoped($1, $2, $3, $4)`,
            [sessionToken, String(body.email ?? ""), roleId, providerId],
          );
          return { invitationId: result.rows[0]?.invitation_id };
        }
        case "create_role": {
          const result = await client.query(`SELECT role_id FROM portal.sp_session_create_role($1, $2)`, [
            sessionToken,
            String(body.name ?? ""),
          ]);
          return { roleId: result.rows[0]?.role_id };
        }
        case "set_role_permission": {
          const result = await client.query(
            `SELECT granted FROM portal.sp_session_set_role_permission($1, $2, $3, $4)`,
            [sessionToken, Number(body.roleId), String(body.permissionName ?? ""), Boolean(body.granted)],
          );
          return { granted: result.rows[0]?.granted };
        }
        case "upsert_class_access": {
          const result = await client.query(
            `SELECT access_id FROM portal.sp_session_upsert_class_role_access($1, $2, $3, $4, $5)`,
            [
              sessionToken,
              String(body.className ?? ""),
              Number(body.roleId),
              String(body.metaAction ?? "read"),
              String(body.effect ?? "allow"),
            ],
          );
          return { accessId: result.rows[0]?.access_id };
        }
        case "list_class_access": {
          const result = await client.query(
            `SELECT access_id, role_id, role_name, class_id, class_name, action, effect, declared_depth
             FROM portal.sp_session_list_class_role_access($1, $2)`,
            [sessionToken, String(body.className ?? "")],
          );
          return { rows: result.rows };
        }
        case "upsert_object_access": {
          const result = await client.query(
            `SELECT access_id FROM portal.sp_session_upsert_object_access($1, $2, $3, $4, $5, $6)`,
            [
              sessionToken,
              Number(body.objId),
              body.roleId != null ? Number(body.roleId) : null,
              body.userId != null ? Number(body.userId) : null,
              String(body.metaAction ?? "read"),
              String(body.effect ?? "deny"),
            ],
          );
          return { accessId: result.rows[0]?.access_id };
        }
        case "list_object_access": {
          const result = await client.query(
            `SELECT access_id, role_id, role_name, user_id, user_name, action, effect
             FROM portal.sp_session_list_object_access($1, $2)`,
            [sessionToken, Number(body.objId)],
          );
          return { rows: result.rows };
        }
        case "effective_check": {
          const result = await client.query(
            `SELECT allowed, resolution_summary FROM portal.sp_session_effective_permissions_check($1, $2, $3, NULL, $4)`,
            [
              sessionToken,
              Number(body.targetUserId),
              body.className != null ? String(body.className) : null,
              String(body.metaAction ?? "read"),
            ],
          );
          return {
            allowed: result.rows[0]?.allowed,
            summary: result.rows[0]?.resolution_summary,
          };
        }
        default:
          throw new Error("unknown security action");
      }
    } catch (err) {
      mapPgPortalError(err);
    }
  });
}
