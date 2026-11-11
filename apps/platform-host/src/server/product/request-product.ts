import { headers } from "next/headers";
import { getProductDefinition, getPlatformProductRegistry } from "./registry";
import { resolveProductIdFromHost } from "./resolve";
import type { PlatformProductDefinition } from "./types";

export const PRODUCT_ID_HEADER = "x-goliath-product-id";

export async function getRequestProductId(): Promise<string> {
  const h = await headers();
  const fromHeader = h.get(PRODUCT_ID_HEADER)?.trim().toLowerCase();
  if (fromHeader) {
    return fromHeader;
  }
  const host =
    h.get("x-forwarded-host")?.split(",")[0]?.trim() ??
    h.get("host")?.split(",")[0]?.trim() ??
    "";
  const hostname = host.split(":")[0] ?? "";
  return resolveProductIdFromHost(hostname);
}

export async function getRequestProductDefinition(): Promise<PlatformProductDefinition> {
  const id = await getRequestProductId();
  const product = getProductDefinition(id);
  if (product) {
    return product;
  }
  const registry = getPlatformProductRegistry();
  const fallback = getProductDefinition(registry.defaultProductId);
  if (fallback) {
    return fallback;
  }
  return registry.products[0]!;
}
