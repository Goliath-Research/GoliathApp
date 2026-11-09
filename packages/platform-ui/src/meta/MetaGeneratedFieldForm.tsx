"use client";

import type { MetaClassField } from "@goliath/client";
import { SchemaPropertyGrid } from "./SchemaPropertyGrid.js";

export type MetaGeneratedFieldFormProps = {
  fields: MetaClassField[];
  flattenedSchema?: unknown;
  initialDocument?: Record<string, unknown>;
  onSubmit: (document: Record<string, unknown>) => void | Promise<void>;
  submitLabel?: string;
  disabled?: boolean;
};

/** Back-compat alias: delegates to {@link SchemaPropertyGrid} (vertical schema-driven grid). */
export function MetaGeneratedFieldForm({
  fields,
  flattenedSchema,
  ...rest
}: MetaGeneratedFieldFormProps) {
  return <SchemaPropertyGrid fields={fields} flattenedSchema={flattenedSchema ?? {}} {...rest} />;
}
