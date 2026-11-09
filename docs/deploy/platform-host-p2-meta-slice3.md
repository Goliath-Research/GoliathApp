# Platform host — P2 Meta slice 3 (SchemaPropertyGrid + authenticated E2E)

## Governing principle (Meta class hierarchy)

The **Meta class hierarchy** is the foundation of schema-driven editing in GoliathApp — not a generic JSON Schema renderer with class lookups bolted on.

1. **Types are hierarchical.** A field’s `TypeID` points at a `wf.data_type` or Meta class catalog entry. Nested shapes resolve by loading that type/class and the **merged schema** the database already computes for the class lineage (`Meta.fn_class_json_schema_flattened` / `schema_bundled_json` with `goliath:meta/class/…` and `goliath:type/…` in `$defs`).
2. **Presentation walks ancestry.** Editor components, nested-grid chrome, icons, and labels resolve by walking class FQN ancestry (**most specific wins**, then ancestors, then optional `dataTypeEditorComponents`, then schema-only constraints, then generic fallback). Single implementation: `packages/platform-ui/src/meta/metaHierarchyResolver.ts` (`walkRegistryAncestry`, `resolveHierarchyFieldEditor`, `resolveClassGridPresentation`). Host `resolve-meta-editor.ts` delegates to the same walk.
3. **Primitives are catalog types.** String/int/bool editors bind to `wf.data_type` via `typeKind` / `typeName`, not raw JSON Schema `type` alone; JSON Schema on the flattened property supplies constraints (e.g. `enum`) only after the catalog decision.
4. **Child apps extend the hierarchy.** They register `editorComponents`, `classIconOverrides`, and optional `dataTypeEditorComponents` on class / type FQNs; nested `SchemaPropertyGrid` dialogs load sub-classes through the host BFF (`GET /api/meta/classes/*`, `GET /api/meta/types/*` → `portal.sp_session_*`).

Public **goliath-portal** has no `SchemaPropertyGrid` source (read-only audit: `src/components/screen.tsx` start-grid layout, `data-table.tsx` JSON viewers only). This slice implements the SQL-named contract in `@goliath/platform-ui`.

Follows merged PR #62 (scoped instance APIs + anti-oracle 404/403 rules) and PR #63 (authenticated E2E, dev-establish allowlist).

## SchemaPropertyGrid (canonical editor)

SQL contract (`workflow_engine/sql_pg/wf_data_type.sql`):

```sql
-- schema_json is the JSON Schema document SchemaPropertyGrid binds.
```

Implementation (`packages/platform-ui/src/meta/SchemaPropertyGrid.tsx` → `SchemaPropertyGridSurface`):

- **Delphi Object Inspector layout (rebuilt in GoliathApp):** two-column table `g-property-inspector` (property name | value), fields grouped by declaring Meta class (collapsible category rows), per-row icons from `resolveFieldRowIcon` (registry ancestry → type-kind fallback).
- **Nested values:** summary cell, `+` inline expand (read-only sub-rows), `…` button (`data-testid="pi-open-<field>"`) opens `PropertyInspectorModal` (portal to `document.body`, OK/Cancel, breadcrumb). Catalog types load through `PropertyInspectorDialogHost` → `CatalogNestedSchemaDialog` + `MetaCatalogResolver` (never raw JSON for schema-typed fields).
- **Arrays of schema-typed items:** list editor with add/remove/reorder; each item uses the same nested modal stack.
- **Reference (read-only):** Goliath-Research `uniGUI-CookBook` — `D4WGridDesignerFrm.pas` / `IQGridDesignerFrm.pas` (`TUniPropertyGrid` categorized two-column inspector). Public goliath-portal had no surviving grid source.
- **Schemaless JSON textarea:** only when the type is genuinely untyped (`schemaless` mode) and no catalog ref resolves.

Aliases: `MetaGeneratedFieldForm`, `MetaSchemaDocumentForm` delegate to `SchemaPropertyGrid`.

## Authenticated E2E (CI)

1. `scripts/ci/platform_host_e2e_pg_seed.py` — `e2e/NestedParent` → `e2e/NestedChild` inheritance, data-type / class-typed / array fields on `e2e/NestedCarrier`, scoped `meta.*` grants, `apps/platform-host/.e2e/ci.env`.
2. `PLAYWRIGHT_AUTH_E2E=1` — `auth.setup.ts`, `host.meta.authenticated.spec.ts`, `host.meta.nested-grid.spec.ts`.
3. Dev login allowlist (`resolveDevEstablishUserId`) unchanged from PR #63.

Nested E2E page: `/app/nested-e2e`. Screenshots: `platform-host-e2e-screenshots`.

## Gaps (honest)

Production OIDC Playwright path; full Delphi designer chrome (drag-drop layout) is out of scope — only the property-inspector editing pattern is ported.

## Not in this slice (P3+)

Workflow designer/monitor unchanged.
