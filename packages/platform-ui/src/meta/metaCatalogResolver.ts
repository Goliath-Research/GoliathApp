import type { MetaClassField, MetaClassLineageNode } from "@goliath/client";

export type NestedMetaClassContext = {
  className: string;
  fields: MetaClassField[];
  flattenedSchema: unknown;
  bundledSchema: unknown;
  lineage: MetaClassLineageNode[];
};

export type NestedDataTypeContext = {
  typeName: string;
  kind: string;
  schemaJson: unknown;
  elementTypeName?: string | null;
};

/** Loads Meta classes and wf.data_type entries for nested SchemaPropertyGrid dialogs. */
export type MetaCatalogResolver = {
  loadMetaClass(className: string): Promise<NestedMetaClassContext>;
  loadDataType(typeName: string, version?: string): Promise<NestedDataTypeContext>;
};
