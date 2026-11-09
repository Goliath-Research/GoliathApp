import {
  createPlatformBffClient,
  type MetaClassField,
  type MetaClassLineageNode,
} from "@goliath/client";
import type { MetaCatalogResolver } from "@goliath/platform-ui";

export function createHostMetaCatalogResolver(
  client = createPlatformBffClient(),
): MetaCatalogResolver {
  return {
    async loadMetaClass(className: string) {
      const [summary, fields, lineage] = await Promise.all([
        client.getMetaClass(className),
        client.getMetaClassFields(className),
        client.getMetaClassLineage(className),
      ]);
      return {
        className,
        fields: fields as MetaClassField[],
        flattenedSchema: summary.schemaFlattenedJson,
        bundledSchema: summary.schemaBundledJson,
        lineage: lineage as MetaClassLineageNode[],
      };
    },
    async loadDataType(typeName: string, version?: string) {
      const row = await client.getMetaDataType(typeName, version);
      return {
        typeName: row.name,
        kind: row.kind,
        schemaJson: row.schemaJson,
        elementTypeName: row.elementTypeName,
      };
    },
  };
}
