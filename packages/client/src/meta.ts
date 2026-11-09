export type MetaClassSummary = {
  classId: number;
  className: string;
  parentId: number | null;
  parentName: string | null;
  depth: number;
  isAbstract: boolean;
  catalogTypeName: string;
  schemaFlattenedJson: unknown;
  schemaBundledJson: unknown;
};

export type MetaClassLineageNode = {
  lineageRole: "ancestor" | "self" | "descendant";
  classId: number;
  className: string;
  parentId: number | null;
  depth: number;
  relationDepth: number;
};

export type MetaClassField = {
  fieldName: string;
  typeId: number | null;
  typeName: string | null;
  typeKind: string | null;
  required: boolean;
  declaredOnClassId: number;
  declaredOnClassName: string;
  definedAtDepth: number;
  isLocal: boolean;
};

export type MetaObjectDocument = {
  objId: number;
  classId: number;
  className: string;
  document: Record<string, unknown>;
};
