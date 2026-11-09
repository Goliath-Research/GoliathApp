import { Ajv2020 } from "ajv/dist/2020.js";
import type { ErrorObject, ValidateFunction } from "ajv";

function registerCatalogDefs(ajv: Ajv2020, schema: Record<string, unknown>): void {
  const defs = schema.$defs;
  if (defs == null || typeof defs !== "object" || Array.isArray(defs)) return;
  for (const [id, def] of Object.entries(defs as Record<string, unknown>)) {
    if (def == null || typeof def !== "object" || Array.isArray(def)) continue;
    const defRecord = def as Record<string, unknown>;
    if (defRecord.$id === id) continue;
    ajv.addSchema({ ...defRecord, $id: id }, id);
  }
}

export function compileSchemaValidator(schema: object): ValidateFunction {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  if (schema != null && typeof schema === "object" && !Array.isArray(schema)) {
    registerCatalogDefs(ajv, schema as Record<string, unknown>);
  }
  return ajv.compile(schema);
}

const ajv = new Ajv2020({ allErrors: true, strict: false });

export function validationMessage(errors: ErrorObject[] | null | undefined): string {
  return ajv.errorsText(errors ?? undefined, { dataVar: "document" }) || "validation failed";
}
