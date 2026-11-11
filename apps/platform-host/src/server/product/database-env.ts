import type { PlatformProductDatabaseEnv, PlatformProductDefinition } from "./types";

export function databaseEnvForProduct(productId: string): PlatformProductDatabaseEnv {
  const normalized = productId.replace(/[^a-z0-9]/gi, "_").toUpperCase();
  return {
    portalDbEnv: `GOLIATH_PRODUCT_${normalized}_PORTAL_DB`,
    hostEnv: `GOLIATH_PRODUCT_${normalized}_PGHOST`,
    portEnv: `GOLIATH_PRODUCT_${normalized}_PGPORT`,
    databaseEnv: `GOLIATH_PRODUCT_${normalized}_PGDATABASE`,
    userEnv: `GOLIATH_PRODUCT_${normalized}_GOLIATH_PORTAL_USER`,
    passwordEnv: `GOLIATH_PRODUCT_${normalized}_GOLIATH_PORTAL_PASSWORD`,
    sslModeEnv: `GOLIATH_PRODUCT_${normalized}_PGSSLMODE`,
  };
}

export function defaultGoliathAppProduct(): PlatformProductDefinition {
  return {
    id: "goliathapp",
    displayName: "Goliath",
    portalSubtitle: "Platform portal",
    hostnames: ["localhost", "127.0.0.1"],
    database: {
      portalDbEnv: "GOLIATH_PORTAL_DB",
      hostEnv: "PGHOST",
      portEnv: "PGPORT",
      databaseEnv: "PGDATABASE",
      userEnv: "GOLIATH_PORTAL_USER",
      passwordEnv: "GOLIATH_PORTAL_PASSWORD",
      sslModeEnv: "PGSSLMODE",
    },
  };
}
