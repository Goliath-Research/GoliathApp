import { getPlatformProductRegistry } from "./registry";

function hostnameMatches(pattern: string, hostname: string): boolean {
  const pat = pattern.trim().toLowerCase();
  const host = hostname.trim().toLowerCase();
  if (!pat || !host) return false;
  if (pat === host) return true;
  if (pat.startsWith("*.")) {
    const suffix = pat.slice(1);
    return host.endsWith(suffix) && host.length > suffix.length;
  }
  return false;
}

export function resolveProductIdFromHost(hostname: string): string {
  const registry = getPlatformProductRegistry();
  const host = hostname.trim().toLowerCase();
  if (!host) {
    return registry.defaultProductId;
  }
  for (const product of registry.products) {
    if (product.hostnames.some((pattern) => hostnameMatches(pattern, host))) {
      return product.id;
    }
  }
  return registry.defaultProductId;
}
