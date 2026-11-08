/** Build-time hook: child apps export this shape from their UI manifest module. */
export type GoliathUiManifest = {
  appId: string;
  classIconOverrides?: Record<string, string>;
  /**
   * Stable editor keys bound to React components in the child bundle (no Python→React loading).
   * Values are opaque ids validated at child compile time.
   */
  editorComponents?: Record<string, string>;
};
