import {
  databaseEnvForProduct,
  defaultGoliathAppProduct,
} from "./database-env";
import type { PlatformProductDefinition, PlatformProductRegistry } from "./types";

function parseHostnameList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((h) => String(h).trim().toLowerCase()).filter(Boolean);
}

function parseProduct(row: unknown): PlatformProductDefinition | null {
  if (!row || typeof row !== "object") return null;
  const r = row as Record<string, unknown>;
  const id = String(r.id ?? "").trim().toLowerCase();
  if (!id) return null;
  const hostnames = parseHostnameList(r.hostnames);
  return {
    id,
    displayName: String(r.displayName ?? id),
    portalSubtitle: String(r.portalSubtitle ?? "Operator portal"),
    hostnames: hostnames.length > 0 ? hostnames : [],
    database: databaseEnvForProduct(id),
  };
}

export function parsePlatformProductRegistry(raw: unknown): PlatformProductRegistry | null {
  if (!raw || typeof raw !== "object") return null;
  const doc = raw as Record<string, unknown>;
  const defaultProductId = String(doc.defaultProductId ?? "goliathapp").trim().toLowerCase();
  const productsRaw = doc.products;
  const products: PlatformProductDefinition[] = [];
  if (Array.isArray(productsRaw)) {
    for (const row of productsRaw) {
      const p = parseProduct(row);
      if (p) products.push(p);
    }
  }
  if (products.length === 0) return null;
  return { defaultProductId, products };
}

let cachedRegistry: PlatformProductRegistry | null | undefined;

/** @internal test hook */
export function resetPlatformProductRegistryForTests(): void {
  cachedRegistry = undefined;
}

export function getPlatformProductRegistry(): PlatformProductRegistry {
  if (cachedRegistry !== undefined) {
    return cachedRegistry ?? fallbackRegistry();
  }
  const raw = process.env.GOLIATH_PLATFORM_PRODUCTS_JSON?.trim();
  if (!raw) {
    cachedRegistry = null;
    return fallbackRegistry();
  }
  try {
    const parsed = parsePlatformProductRegistry(JSON.parse(raw) as unknown);
    if (!parsed) {
      cachedRegistry = null;
      return fallbackRegistry();
    }
    cachedRegistry = parsed;
    return parsed;
  } catch {
    cachedRegistry = null;
    return fallbackRegistry();
  }
}

function fallbackRegistry(): PlatformProductRegistry {
  return {
    defaultProductId: "goliathapp",
    products: [defaultGoliathAppProduct()],
  };
}

export function getProductDefinition(productId: string): PlatformProductDefinition | null {
  const registry = getPlatformProductRegistry();
  return registry.products.find((p) => p.id === productId) ?? null;
}
