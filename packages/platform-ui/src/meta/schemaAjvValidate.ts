import { Ajv2020 } from "ajv/dist/2020.js";
import type { ErrorObject, ValidateFunction } from "ajv";

const ajv = new Ajv2020({ allErrors: true, strict: false });

export function compileSchemaValidator(schema: object): ValidateFunction {
  return ajv.compile(schema);
}

export function validationMessage(errors: ErrorObject[] | null | undefined): string {
  return ajv.errorsText(errors ?? undefined, { dataVar: "document" }) || "validation failed";
}
