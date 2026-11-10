import Link from "next/link";
import { PlatformRecordTable } from "@goliath/platform-ui";
import {
  portalSessionPlatformQuery,
  portalSessionRunSemanticRequest,
  portalSessionSemanticEntities,
  type SemanticEntityRow,
} from "@/server/portal/bridge";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";
import { cookies } from "next/headers";

export type SemanticCatalogEntry = {
  requestCode: string;
  version: string;
  namespace: string;
  entityCode: string;
  displayName: string;
  requiredPermission: string | null;
};

async function loadCatalog(token: string): Promise<SemanticCatalogEntry[]> {
  const rows = await portalSessionPlatformQuery(
    token,
    `SELECT request_code, version, namespace, entity_code, display_name, required_permission
     FROM portal.sp_list_semantic_catalog($1)`,
  );
  return rows.map((row) => ({
    requestCode: String(row.request_code),
    version: String(row.version),
    namespace: String(row.namespace),
    entityCode: String(row.entity_code),
    displayName: String(row.display_name),
    requiredPermission: row.required_permission == null ? null : String(row.required_permission),
  }));
}

function entityByKey(entities: SemanticEntityRow[], namespace: string, entityCode: string) {
  return entities.find((e) => e.namespace === namespace && e.code === entityCode);
}

function columnsFromRows(rows: Record<string, unknown>[]) {
  if (rows.length === 0) return [];
  return Object.keys(rows[0] ?? {}).map((key) => ({
    key,
    label: key.replace(/_/g, " "),
  }));
}

/** Single semantic request presented as a read-only view (same rows as list/admin surfaces). */
export async function SemanticRequestView({
  requestCode,
  title,
  entities,
}: {
  requestCode: string;
  title: string;
  entities: SemanticEntityRow[];
}) {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) return null;

  const rows = await portalSessionRunSemanticRequest(token, requestCode, { limit: 25 });
  const columns = columnsFromRows(rows);
  const catalog = await loadCatalog(token);
  const entry = catalog.find((c) => c.requestCode === requestCode);
  const entity =
    entry != null ? entityByKey(entities, entry.namespace, entry.entityCode) : undefined;

  return (
    <section className="g-portal-view-widget" aria-labelledby={`view-${requestCode}`}>
      <div className="g-portal-view-widget__head">
        <h3 id={`view-${requestCode}`}>{title}</h3>
        {entity?.metaClassName ? (
          <p>
            Meta class:{" "}
            <Link href={`/app/meta?class=${encodeURIComponent(entity.metaClassName)}`}>{entity.metaClassName}</Link>
          </p>
        ) : null}
      </div>
      <PlatformRecordTable caption={title} columns={columns} rows={rows} />
    </section>
  );
}

/** Dashboard grid: composes authorized semantic requests (platform + inv + child). */
export async function SemanticDashboard({ focusRequests }: { focusRequests?: string[] }) {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) return null;

  const catalog = await loadCatalog(token);
  const entities = await portalSessionSemanticEntities(token);
  const picks =
    focusRequests ??
    catalog
      .filter((c) => !c.requestCode.includes("restricted"))
      .slice(0, 6)
      .map((c) => c.requestCode);

  return (
    <div className="g-portal-dashboard">
      <p className="g-host-home__lead">
        Dashboard widgets run the same <code>portal.sp_run_semantic_request</code> paths as list screens. Open the
        backing Meta class to inspect or edit schema and instances.
      </p>
      <div className="g-portal-dashboard__grid">
        {picks.map((code) => {
          const entry = catalog.find((c) => c.requestCode === code);
          const title = entry?.displayName ?? code;
          return <SemanticRequestView key={code} requestCode={code} title={title} entities={entities} />;
        })}
      </div>
    </div>
  );
}

/** Catalog of runnable views (one semantic request each). */
export async function SemanticViewCatalog() {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) return null;

  const catalog = await loadCatalog(token);
  const entities = await portalSessionSemanticEntities(token);

  return (
    <div className="g-portal-stage">
      <table className="g-host-table" aria-label="Semantic views">
        <thead>
          <tr>
            <th scope="col">View</th>
            <th scope="col">Request</th>
            <th scope="col">Entity</th>
            <th scope="col">Meta class</th>
            <th scope="col">Open</th>
          </tr>
        </thead>
        <tbody>
          {catalog.map((entry) => {
            const entity = entityByKey(entities, entry.namespace, entry.entityCode);
            return (
              <tr key={`${entry.requestCode}@${entry.version}`}>
                <td>{entry.displayName}</td>
                <td>
                  <code>{entry.requestCode}</code>
                </td>
                <td>
                  {entry.namespace}/{entry.entityCode}
                </td>
                <td>
                  {entity?.metaClassName ? (
                    <Link href={`/app/meta?class=${encodeURIComponent(entity.metaClassName)}`}>
                      {entity.metaClassName}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  <Link href={`/app/views/list?request=${encodeURIComponent(entry.requestCode)}`}>Run view</Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
