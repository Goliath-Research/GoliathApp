export type PlatformProductDatabaseEnv = {
  /** Full libpq URL override (e.g. GOLIATH_PRODUCT_GOLIATHAPP_PORTAL_DB). */
  portalDbEnv: string;
  hostEnv: string;
  portEnv: string;
  databaseEnv: string;
  userEnv: string;
  passwordEnv: string;
  sslModeEnv: string;
};

export type PlatformProductDefinition = {
  id: string;
  displayName: string;
  portalSubtitle: string;
  hostnames: string[];
  database: PlatformProductDatabaseEnv;
};

export type PlatformProductRegistry = {
  defaultProductId: string;
  products: PlatformProductDefinition[];
};
