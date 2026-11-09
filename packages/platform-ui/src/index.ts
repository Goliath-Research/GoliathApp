/**
 * Shell/table/tree demo primitives for platform screens.
 * Provenance: list/table layout patterns adapted from Goliath-portal DataTable usage (read-only grids),
 * without copying descendant-product screen switches.
 */
export { DemoNavTree } from "./components/DemoNavTree.js";
export { DemoObjectTable } from "./components/DemoObjectTable.js";
export { PlatformFixtureDemo, FIXTURE_NAV_TREE, FIXTURE_PLATFORM_ROWS } from "./fixture/index.js";
export { OperatorNavList } from "./shell/OperatorNavList.js";
export { MetaClassExplorer } from "./meta/MetaClassExplorer.js";
export { SchemaPropertyGrid } from "./meta/SchemaPropertyGrid.js";
export { MetaGeneratedFieldForm } from "./meta/MetaGeneratedFieldForm.js";
export { MetaSchemaDocumentForm } from "./meta/MetaSchemaDocumentForm.js";
export { parseFlattenedFieldSchema, propertySchemaFromFlattened } from "./meta/parseFlattenedFieldSchema.js";
export { resolveFieldEditor, resolveFieldEditorDetailed } from "./meta/resolveFieldEditor.js";
export {
  resolveHierarchyFieldEditor,
  resolveClassGridPresentation,
  walkRegistryAncestry,
  type HierarchyPresentationRegistry,
  type HierarchyFieldResolveResult,
  type HierarchyResolution,
} from "./meta/metaHierarchyResolver.js";
export type { MetaCatalogResolver, NestedMetaClassContext, NestedDataTypeContext } from "./meta/metaCatalogResolver.js";
export { parseGoliathRef, catalogRefFromFieldTypeName, type CatalogRef } from "./meta/catalogRef.js";
