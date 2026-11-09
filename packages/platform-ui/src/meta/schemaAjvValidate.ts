import { Ajv2020 } from "ajv/dist/2020.js";
import type { ErrorObject, ValidateFunction } from "ajv";

function registerCatalogDefs(ajv: Ajv2020, schema: Record<string, unknown>): void {
  const defs = schema.$defs;
  if (defs == null || typeof defs !== "object" || Array.isArray(defs)) return;
  for (const [key, def] of Object.entries(defs as Record<string, unknown>)) {
    if (def == null || typeof def !== "object" || Array.isArray(def)) continue;
    const defRecord = def as Record<string, unknown>;
    const canonicalId =
      typeof defRecord.$id === "string" && defRecord.$id.length > 0 ? defRecord.$id : key;
    try {
      ajv.addSchema({ ...defRecord, $id: canonicalId }, canonicalId);
      if (key !== canonicalId) {
        ajv.addSchema({ ...defRecord, $id: key }, key);
      }
    } catch {
      // Id already registered from an ancestor fragment — still register bundle key alias when needed.
      if (key !== canonicalId) {
        try {
          ajv.addSchema({ ...defRecord, $id: key }, key);
        } catch {
          /* ignore duplicate */
        }
      }
    }
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
