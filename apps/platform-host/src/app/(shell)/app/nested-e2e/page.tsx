import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { MetaInstanceWorkbench } from "@/components/MetaInstanceWorkbench";
import {
  PortalBridgeMisconfiguredError,
  PortalForbiddenError,
  PortalMetaNotFoundError,
  PortalSessionDeniedError,
  portalSessionMetaClassFields,
  portalSessionMetaClassGet,
  portalSessionMetaClassLineage,
} from "@/server/portal/bridge";
import { requirePortalSession } from "@/server/session/require";

export const dynamic = "force-dynamic";

const NESTED_E2E_CLASS = "e2e/NestedCarrier";
const NESTED_CHILD_CLASS = "e2e/NestedChild";

export default async function NestedE2eMetaPage() {
  try {
    await requirePortalSession();
    const cookieStore = await cookies();
    if (!cookieStore.get(process.env.GOLIATH_PLATFORM_SESSION_COOKIE?.trim() || "goliath_platform_session")) {
      redirect("/login");
    }
    const token = cookieStore.get(process.env.GOLIATH_PLATFORM_SESSION_COOKIE?.trim() || "goliath_platform_session")!
      .value;
    const [summary, fields, lineage, childSummary, childFields, childLineage] = await Promise.all([
      portalSessionMetaClassGet(token, NESTED_E2E_CLASS),
      portalSessionMetaClassFields(token, NESTED_E2E_CLASS),
      portalSessionMetaClassLineage(token, NESTED_E2E_CLASS),
      portalSessionMetaClassGet(token, NESTED_CHILD_CLASS),
      portalSessionMetaClassFields(token, NESTED_CHILD_CLASS),
      portalSessionMetaClassLineage(token, NESTED_CHILD_CLASS),
    ]);
    return (
      <div className="g-host-app">
        <p className="kicker">[E2E nested SchemaPropertyGrid]</p>
        <h2>{NESTED_E2E_CLASS}</h2>
        <MetaInstanceWorkbench
          className={NESTED_E2E_CLASS}
          fields={fields}
          flattenedSchema={summary.schemaFlattenedJson}
          bundledSchema={summary.schemaBundledJson}
          lineage={lineage}
          catalogClassFixtures={{
            [NESTED_CHILD_CLASS]: {
              fields: childFields,
              flattenedSchema: childSummary.schemaFlattenedJson,
              bundledSchema: childSummary.schemaBundledJson,
              lineage: childLineage,
            },
          }}
        />
      </div>
    );
  } catch (err) {
    if (err instanceof PortalBridgeMisconfiguredError) {
      redirect("/?auth=unconfigured");
    }
    if (err instanceof PortalSessionDeniedError) {
      redirect("/login");
    }
    if (err instanceof PortalForbiddenError || err instanceof PortalMetaNotFoundError) {
      return (
        <div className="g-host-app" role="alert">
          <h2>Nested E2E class unavailable</h2>
          <p>
            <code>{NESTED_E2E_CLASS}</code> is missing — run CI seed (<code>platform_host_e2e_pg_seed.py</code>).
          </p>
        </div>
      );
    }
    throw err;
  }
}
