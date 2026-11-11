import type { PlatformProductDatabaseEnv, PlatformProductDefinition } from "./types";
import { defaultGoliathAppProduct } from "./database-env";
import { getPlatformProductRegistry } from "./registry";

function envValue(name: string): string | undefined {
  const v = process.env[name]?.trim();
  return v || undefined;
}

function readWithFallback(primary: string, fallbacks: string[]): string | undefined {
  for (const key of [primary, ...fallbacks]) {
    const v = envValue(key);
    if (v) return v;
  }
  return undefined;
}

export function resolvePortalBridgeConfigForProduct(
  product: PlatformProductDefinition,
): { connString: string } | null {
  const db: PlatformProductDatabaseEnv = product.database;
  const override = envValue(db.portalDbEnv);
  if (override) {
    return { connString: override };
  }

  const isDefaultApp =
    product.id === defaultGoliathAppProduct().id &&
    db.portalDbEnv === defaultGoliathAppProduct().database.portalDbEnv;

  const host = readWithFallback(db.hostEnv, isDefaultApp ? ["POSTGRES_HOST"] : []);
  const port = readWithFallback(db.portEnv, isDefaultApp ? ["POSTGRES_PORT"] : []) ?? "5432";
  const database = readWithFallback(db.databaseEnv, isDefaultApp ? ["POSTGRES_DB"] : []);
  const user = readWithFallback(db.userEnv, []) ?? "goliath_portal";
  const password = readWithFallback(db.passwordEnv, isDefaultApp ? ["PGPASSWORD", "POSTGRES_PASSWORD"] : []);
  const sslmode = readWithFallback(db.sslModeEnv, []) ?? "prefer";

  if (!host || !database || !password) {
    return null;
  }

  const encodedUser = encodeURIComponent(user);
  const encodedPassword = encodeURIComponent(password);
  return {
    connString: `postgresql://${encodedUser}:${encodedPassword}@${host}:${port}/${database}?sslmode=${sslmode}`,
  };
}

export function isAnyProductBridgeConfigured(): boolean {
  const registry = getPlatformProductRegistry();
  for (const product of registry.products) {
    if (resolvePortalBridgeConfigForProduct(product) !== null) {
      return true;
    }
  }
  return false;
}
