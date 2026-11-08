import Link from "next/link";
import { ObjectBadge } from "@goliath/ui";
import { listPublicAuthProviders } from "@/server/auth/registry";
import { headers } from "next/headers";
import { requestOriginFromHeaderStore } from "@/server/http/request-origin";

export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const params = await searchParams;
  const hdrs = await headers();
  const origin = requestOriginFromHeaderStore((name) => hdrs.get(name), "http://localhost:3400");
  const providers = listPublicAuthProviders(origin);

  return (
    <div className="g-host-home">
      <p className="kicker">[Operator sign-in]</p>
      <h2>Authentication methods</h2>
      <p className="g-host-home__lead">
        Human sign-in uses platform-registered identity providers. Accounts are bound by{" "}
        <strong>issuer + subject</strong> per scope — email alone does not grant access. Machine credentials use
        the workflow gateway, not this page.
      </p>
      {params.error === "not_linked" ? (
        <p role="alert">This identity is not linked to an operator account for the selected organization scope.</p>
      ) : null}
      {params.error === "oauth" ? (
        <p role="alert">Sign-in could not be completed. Check provider configuration and try again.</p>
      ) : null}
      {params.error === "transaction" ? (
        <p role="alert">Your sign-in session expired or was invalid. Start again from this page.</p>
      ) : null}
      {params.error === "state" ? (
        <p role="alert">Sign-in state did not match. This can happen if you used an old link or multiple tabs.</p>
      ) : null}
      {params.error === "provider" ? (
        <p role="alert">That sign-in provider is not registered on this host.</p>
      ) : null}
      {params.error === "bridge" ? (
        <p role="alert">Portal session bridge is not configured on this host.</p>
      ) : null}
      {providers.length === 0 ? (
        <p role="status">No OIDC providers are configured on this host (`GOLIATH_AUTH_OIDC_PROVIDERS_JSON`).</p>
      ) : (
        <ul className="g-operator-nav" aria-label="Configured sign-in providers">
          {providers.map((p) => (
            <li key={p.providerId}>
              <a href={p.signInUrl}>
                <ObjectBadge kind={p.presentationKind} label={`Sign in with ${p.displayName}`} />
              </a>
            </li>
          ))}
        </ul>
      )}
      <p>
        <Link href="/">Back to host overview</Link> · <Link href="/fixture">Fixture demo (public)</Link>
      </p>
    </div>
  );
}
