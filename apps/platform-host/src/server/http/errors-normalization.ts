/** Uniform 404 body for instance APIs (no cross-tenant existence oracle). */
export function resolvePortalNotFoundBody(message: string): string {
  return message.includes("meta class") ? message : "meta object not found";
}
