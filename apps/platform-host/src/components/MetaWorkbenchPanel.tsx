import { MetaClassExplorer } from "@goliath/platform-ui";
import { MetaInstanceWorkbench } from "@/components/MetaInstanceWorkbench";
import { EXAMPLE_CHILD_EXTENSION } from "@/lib/child-extension";
import { resolveMetaEditorManifestKey } from "@/lib/resolve-meta-editor";
import { resolveMetaEditorComponent } from "@/lib/meta-editor-registry";
import {
  PortalForbiddenError,
  PortalMetaNotFoundError,
  portalSessionMetaClassFields,
  portalSessionMetaClassGet,
  portalSessionMetaClassLineage,
} from "@/server/portal/bridge";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";
import { cookies } from "next/headers";

export async function MetaWorkbenchPanel({ className }: { className: string }) {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) {
    return null;
  }
  let summary;
  let lineage;
  let fields;
  try {
    [summary, lineage, fields] = await Promise.all([
      portalSessionMetaClassGet(token, className),
      portalSessionMetaClassLineage(token, className),
      portalSessionMetaClassFields(token, className),
    ]);
  } catch (err) {
    if (err instanceof PortalForbiddenError) {
      return (
        <div className="g-portal-stage" role="alert">
          <h2>Access denied</h2>
          <p>Your session lacks permission for this Meta class.</p>
        </div>
      );
    }
    if (err instanceof PortalMetaNotFoundError) {
      return (
        <div className="g-portal-stage" role="alert">
          <h2>Meta class not found</h2>
          <p>Open the class hierarchy and pick a registered Meta class.</p>
        </div>
      );
    }
    throw err;
  }
  const classAncestry = lineage
    .filter((node) => node.lineageRole === "ancestor" || node.lineageRole === "self")
    .sort((a, b) => b.depth - a.depth)
    .map((node) => node.className);
  const editorResolved = resolveMetaEditorManifestKey(
    className,
    classAncestry,
    EXAMPLE_CHILD_EXTENSION.manifest.editorComponents,
  );

  return (
    <MetaClassExplorer
      summary={{
        classId: summary.classId,
        className: summary.className,
        parentId: summary.parentId,
        parentName: summary.parentName,
        depth: summary.depth,
        isAbstract: summary.isAbstract,
        catalogTypeName: summary.catalogTypeName,
        schemaFlattenedJson: summary.schemaFlattenedJson,
        schemaBundledJson: summary.schemaBundledJson,
      }}
      lineage={lineage.map((node) => ({
        lineageRole: node.lineageRole,
        classId: node.classId,
        className: node.className,
        parentId: node.parentId,
        depth: node.depth,
        relationDepth: node.relationDepth,
      }))}
      fields={fields.map((f) => ({
        fieldName: f.fieldName,
        typeId: f.typeId,
        typeName: f.typeName,
        typeKind: f.typeKind,
        required: f.required,
        declaredOnClassId: f.declaredOnClassId,
        declaredOnClassName: f.declaredOnClassName,
        definedAtDepth: f.definedAtDepth,
        isLocal: f.isLocal,
      }))}
      classIconOverrides={EXAMPLE_CHILD_EXTENSION.manifest.classIconOverrides}
      editorSlot={
        <>
          {resolveMetaEditorComponent(editorResolved.manifestKey, {
            className,
            fields,
            matchedClassFqn: editorResolved.matchedClassFqn,
            resolution: editorResolved.resolution,
          })}
          <MetaInstanceWorkbench
            className={className}
            fields={fields}
            flattenedSchema={summary.schemaFlattenedJson}
            bundledSchema={summary.schemaBundledJson}
            lineage={lineage}
          />
        </>
      }
    />
  );
}
