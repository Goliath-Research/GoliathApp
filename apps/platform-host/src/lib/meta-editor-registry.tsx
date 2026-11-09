import type { ReactNode } from "react";
import type { MetaClassField } from "@goliath/client";

export type MetaEditorComponentProps = {
  className: string;
  fields: MetaClassField[];
  matchedClassFqn?: string;
  resolution?: string;
};

const REGISTRY: Record<string, (props: MetaEditorComponentProps) => ReactNode> = {
  ExampleStudyManifestEditor: ({ className, matchedClassFqn, resolution }) => (
    <p role="status">
      Child editor slot <code>ExampleStudyManifestEditor</code> for <code>{className}</code>
      {matchedClassFqn ? (
        <>
          {" "}
          via manifest on <code>{matchedClassFqn}</code> ({resolution ?? "resolved"})
        </>
      ) : (
        " (host stub)"
      )}
    </p>
  ),
};

export function resolveMetaEditorComponent(
  manifestKey: string | undefined,
  props: MetaEditorComponentProps,
): ReactNode | null {
  if (!manifestKey) return null;
  const factory = REGISTRY[manifestKey];
  if (!factory) {
    return (
      <p role="alert">
        Unknown editorComponents key <code>{manifestKey}</code> — not registered in host bundle.
      </p>
    );
  }
  return factory(props);
}
