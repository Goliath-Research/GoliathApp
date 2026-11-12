/**
 * Shell/table/tree demo primitives for platform screens.
 * Provenance: list/table layout patterns adapted from Goliath-portal DataTable usage (read-only grids),
 * without copying descendant-product screen switches.
 */
export { DemoNavTree } from "./components/DemoNavTree.js";
export { DemoObjectTable } from "./components/DemoObjectTable.js";
export { PlatformFixtureDemo, FIXTURE_NAV_TREE, FIXTURE_PLATFORM_ROWS } from "./fixture/index.js";
export { OperatorNavList } from "./shell/OperatorNavList.js";
export { OperatorNavTree } from "./shell/OperatorNavTree.js";
export { buildOperatorNavTree, type OperatorNavTreeNode } from "./shell/buildOperatorNavTree.js";
export { PlatformRecordTable } from "./shell/PlatformRecordTable.js";
export { MetaClassHierarchyList, type MetaClassListRow } from "./meta/MetaClassHierarchyList.js";
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
export { parseReferenceHint, REFERENCE_HINT_KEY, type ReferenceHint } from "./meta/referenceHint.js";
export {
  ReferenceResolverProvider,
  useReferenceResolver,
  type ReferenceOption,
  type ReferenceResolver,
} from "./meta/ReferenceResolverContext.js";
export { ReferencePicker } from "./meta/ReferencePicker.js";
export { PropertyInspectorModal } from "./meta/PropertyInspectorModal.js";
