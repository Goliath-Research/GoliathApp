"use client";

import Ajv from "ajv";
import type { FormEvent } from "react";
import { useMemo, useState } from "react";

export type MetaJsonDocumentEditorProps = {
  flattenedSchema: unknown;
  unsupportedNotes?: readonly string[];
};

const DEFAULT_UNSUPPORTED: readonly string[] = [
  "$ref across goliath:meta/class/* bundles is validated using the flattened schema only.",
  "unevaluatedProperties and multi-branch allOf may not match server Meta.sp_obj_* validation exactly.",
];

export function MetaJsonDocumentEditor({
  flattenedSchema,
  unsupportedNotes = DEFAULT_UNSUPPORTED,
}: MetaJsonDocumentEditorProps) {
  const [documentText, setDocumentText] = useState("{}");
  const [validationMessage, setValidationMessage] = useState<string | null>(null);
  const [valid, setValid] = useState<boolean | null>(null);

  const ajv = useMemo(
    () => new (Ajv as unknown as typeof Ajv)({ allErrors: true, strict: false }),
    [],
  );

  function handleValidate(event: FormEvent) {
    event.preventDefault();
    setValidationMessage(null);
    setValid(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(documentText);
    } catch (e) {
      setValid(false);
      setValidationMessage(e instanceof Error ? e.message : "invalid JSON");
      return;
    }
    if (!flattenedSchema || typeof flattenedSchema !== "object") {
      setValid(false);
      setValidationMessage("flattened schema unavailable — server validation required");
      return;
    }
    try {
      const validate = ajv.compile(flattenedSchema as object);
      const ok = validate(parsed);
      if (ok) {
        setValid(true);
        setValidationMessage("Document matches flattened schema (client check).");
        return;
      }
      setValid(false);
      setValidationMessage(
        ajv.errorsText(validate.errors ?? undefined, { dataVar: "document" }) || "validation failed",
      );
    } catch (e) {
      setValid(false);
      setValidationMessage(
        e instanceof Error ? e.message : "schema compiler error — unsupported construct",
      );
    }
  }

  return (
    <form onSubmit={handleValidate} className="g-meta-editor">
      <label htmlFor="meta-document-json">Instance JSON</label>
      <textarea
        id="meta-document-json"
        rows={8}
        className="g-host-textarea"
        value={documentText}
        onChange={(e) => setDocumentText(e.target.value)}
        spellCheck={false}
      />
      <button type="submit" className="g-host-button">
        Validate (client, flattened schema)
      </button>
      {valid != null ? (
        <p role={valid ? "status" : "alert"}>
          {valid ? "Valid" : "Invalid"}: {validationMessage}
        </p>
      ) : null}
      <details>
        <summary>Validation limitations</summary>
        <ul>
          {unsupportedNotes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </details>
    </form>
  );
}
