import { defaultGoliathAppProduct } from "../product/database-env";
import { resolvePortalBridgeConfigForProduct } from "../product/portal-db";
import type { PlatformProductDefinition } from "../product/types";

export type PortalBridgeConfig = {
  connString: string;
  productId: string;
};

export function resolvePortalBridgeConfig(
  product: PlatformProductDefinition = defaultGoliathAppProduct(),
): PortalBridgeConfig | null {
  const cfg = resolvePortalBridgeConfigForProduct(product);
  if (!cfg) {
    return null;
  }
  return { connString: cfg.connString, productId: product.id };
}

/**
 * Integration-only login path. Never enabled in NODE_ENV=production unless
 * GOLIATH_PLATFORM_HOST_E2E_INTEGRATION=1 (Playwright against standalone build).
 */
export function devLoginAllowed(): boolean {
  if (process.env.GOLIATH_PLATFORM_HOST_DEV_LOGIN !== "1") {
    return false;
  }
  if (process.env.NODE_ENV === "production") {
    return process.env.GOLIATH_PLATFORM_HOST_E2E_INTEGRATION === "1";
  }
  return true;
}

export function devLoginUserId(): number | null {
  const raw = process.env.GOLIATH_P1_DEV_LOGIN_USER_ID?.trim();
  if (!raw) return null;
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function devLoginSecret(): string | null {
  const secret = process.env.GOLIATH_PLATFORM_HOST_DEV_LOGIN_SECRET?.trim();
  return secret || null;
}

export function devLoginE2eIntegration(): boolean {
  return process.env.GOLIATH_PLATFORM_HOST_E2E_INTEGRATION === "1";
}

/** User IDs permitted via `x-goliath-dev-login-user-id` when E2E integration is enabled. */
export function devLoginAllowlistedUserIds(): number[] {
  const ids = new Set<number>();
  const primary = devLoginUserId();
  if (primary != null) {
    ids.add(primary);
  }
  const deniedRaw = process.env.GOLIATH_E2E_DENIED_USER_ID?.trim();
  if (deniedRaw) {
    const denied = Number(deniedRaw);
    if (Number.isInteger(denied) && denied > 0) {
      ids.add(denied);
    }
  }
  return [...ids];
}

export type DevEstablishUserResolution =
  | { ok: true; userId: number }
  | { ok: false; status: 403 | 503; message: string };

/**
 * Resolves the RBAC user for dev-establish. Callers cannot pick arbitrary principals:
 * default env user when header omitted; header ignored outside E2E integration; in E2E
 * integration only env-pinned IDs are accepted.
 */
export function resolveDevEstablishUserId(headerValue: string | null): DevEstablishUserResolution {
  const defaultUser = devLoginUserId();
  if (defaultUser == null) {
    return { ok: false, status: 503, message: "dev login is misconfigured" };
  }

  if (headerValue == null || headerValue.trim() === "") {
    return { ok: true, userId: defaultUser };
  }

  const parsed = Number(headerValue.trim());
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return { ok: false, status: 403, message: "dev login denied" };
  }

  if (!devLoginE2eIntegration()) {
    return { ok: true, userId: defaultUser };
  }

  const allowlist = devLoginAllowlistedUserIds();
  if (!allowlist.includes(parsed)) {
    return { ok: false, status: 403, message: "dev login denied" };
  }
  return { ok: true, userId: parsed };
}
