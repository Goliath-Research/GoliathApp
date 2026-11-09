/** Uniform 404 body for instance APIs (no cross-tenant existence oracle). */
export function resolvePortalNotFoundBody(message: string): string {
  return message.includes("meta class") ? message : "meta object not found";
}

/** Uniform 403 body for identity-independent Meta permission failures (no ObjID oracle). */
export function resolvePortalForbiddenBody(message: string): string {
  if (
    message.includes("meta permission denied") ||
    message.includes("active scope required for meta instance")
  ) {
    return "meta permission denied";
  }
  return message;
}
