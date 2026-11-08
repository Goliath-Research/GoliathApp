import "server-only";

export type PortalBridgeConfig = {
  connString: string;
};

export function resolvePortalBridgeConfig(): PortalBridgeConfig | null {
  const override = process.env.GOLIATH_PORTAL_DB?.trim();
  if (override) {
    return { connString: override };
  }

  const host = process.env.PGHOST?.trim() || process.env.POSTGRES_HOST?.trim();
  const port = process.env.PGPORT?.trim() || process.env.POSTGRES_PORT?.trim() || "5432";
  const database = process.env.PGDATABASE?.trim() || process.env.POSTGRES_DB?.trim();
  const user = process.env.GOLIATH_PORTAL_USER?.trim() || "goliath_portal";
  const password =
    process.env.GOLIATH_PORTAL_PASSWORD?.trim() ||
    process.env.PGPASSWORD?.trim() ||
    process.env.POSTGRES_PASSWORD?.trim();

  if (!host || !database || !password) {
    return null;
  }

  const sslmode = process.env.PGSSLMODE?.trim() || "prefer";
  const encodedUser = encodeURIComponent(user);
  const encodedPassword = encodeURIComponent(password);
  return {
    connString: `postgresql://${encodedUser}:${encodedPassword}@${host}:${port}/${database}?sslmode=${sslmode}`,
  };
}

export function devLoginAllowed(): boolean {
  return process.env.GOLIATH_PLATFORM_HOST_DEV_LOGIN === "1";
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
