import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { MetaClassExplorer } from "@goliath/platform-ui";
import { MetaInstanceWorkbench } from "@/components/MetaInstanceWorkbench";
import { EXAMPLE_CHILD_EXTENSION } from "@/lib/child-extension";
import { resolveMetaEditorComponent } from "@/lib/meta-editor-registry";
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
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";

export const dynamic = "force-dynamic";

const DEFAULT_CLASS = "portal/NavNode";

export default async function MetaExplorerPage({
  searchParams,
}: {
  searchParams: Promise<{ class?: string }>;
}) {
  const params = await searchParams;
  const className = (params.class ?? DEFAULT_CLASS).trim();

  try {
    await requirePortalSession();
    const cookieStore = await cookies();
    const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
    if (!token) {
      redirect("/login");
    }
    const [summary, lineage, fields] = await Promise.all([
      portalSessionMetaClassGet(token, className),
      portalSessionMetaClassLineage(token, className),
      portalSessionMetaClassFields(token, className),
    ]);
    return (
      <div className="g-host-app">
        <p className="kicker">[P2 Meta hierarchy — session-gated]</p>
        <h2>Inherited Meta class browser</h2>
        <p className="g-host-home__lead">
          Reads and writes through <code>portal.sp_session_meta_*</code> with <code>meta.*</code> RBAC (session
          alone is not authorization). Unknown top-level JSON keys are rejected server-side (
          <code>Meta.fn_reject_unknown_document_keys</code>).
        </p>
        <MetaClassExplorer
          summary={summary}
          lineage={lineage}
          fields={fields}
          classIconOverrides={EXAMPLE_CHILD_EXTENSION.manifest.classIconOverrides}
          editorSlot={
            <>
              {resolveMetaEditorComponent(
                EXAMPLE_CHILD_EXTENSION.manifest.editorComponents?.[className],
                { className, fields },
              )}
              <MetaInstanceWorkbench
                className={className}
                fields={fields}
                flattenedSchema={summary.schemaFlattenedJson}
              />
            </>
          }
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
    if (err instanceof PortalForbiddenError) {
      return (
        <div className="g-host-app" role="alert">
          <h2>Meta access denied</h2>
          <p>
            Signed in, but this session lacks <code>meta.schema.read</code> (and related) permissions.
          </p>
        </div>
      );
    }
    if (err instanceof PortalMetaNotFoundError) {
      return (
        <div className="g-host-app" role="alert">
          <h2>Meta class not found</h2>
          <p>
            <code>{className}</code> is not in Meta.Classes. Try{" "}
            <a href={`/app/meta?class=${encodeURIComponent(DEFAULT_CLASS)}`}>{DEFAULT_CLASS}</a>.
          </p>
        </div>
      );
    }
    throw err;
  }
}
