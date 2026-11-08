/** Injected at image/build time; falls back for local dev. */
export function platformHostRevision(): string {
  return (
    process.env.PLATFORM_HOST_REVISION?.trim() ||
    process.env.GITHUB_SHA?.trim()?.slice(0, 12) ||
    process.env.VERCEL_GIT_COMMIT_SHA?.trim()?.slice(0, 12) ||
    "dev-local"
  );
}

export function platformHostVersion(): string {
  return process.env.PLATFORM_HOST_VERSION?.trim() || "0.1.0-p0";
}
