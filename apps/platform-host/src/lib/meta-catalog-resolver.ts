import {
  createPlatformBffClient,
  type MetaClassField,
  type MetaClassLineageNode,
} from "@goliath/client";
import type { MetaCatalogResolver, NestedMetaClassContext } from "@goliath/platform-ui";

export type MetaCatalogClassFixture = Omit<NestedMetaClassContext, "className">;

export function createHostMetaCatalogResolver(
  client = createPlatformBffClient(),
  classFixtures: Record<string, MetaCatalogClassFixture> = {},
): MetaCatalogResolver {
  return {
    async loadMetaClass(className: string) {
      const fixture = classFixtures[className];
      if (fixture) {
        return { className, ...fixture };
      }
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
