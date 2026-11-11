"use client";

import { usePathname, useRouter } from "next/navigation";
import { OperatorNavTree } from "@goliath/platform-ui";
import type { OperatorNavNode } from "@goliath/client";
import type { ResolvedPortalSession } from "@/server/portal/bridge";

export function OperatorPortalShell({
  session,
  nodes,
  children,
  brandName = "Goliath",
  brandSubtitle = "Platform portal",
}: {
  session: ResolvedPortalSession;
  nodes: OperatorNavNode[];
  children: React.ReactNode;
  brandName?: string;
  brandSubtitle?: string;
}) {
  const pathname = usePathname();
  const router = useRouter();

  async function signOut() {
    await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="g-portal">
      <header className="g-portal__bar">
        <div className="g-portal__brand">
          <p className="g-portal__brand-name">{brandName}</p>
          <p className="g-portal__brand-sub">{brandSubtitle}</p>
        </div>
        <p className="g-portal__operator">
          {session.fullName} · <code>{session.email}</code>
          {session.activeRoleName ? (
            <>
              {" "}
              · Role <strong>{session.activeRoleName}</strong>
            </>
          ) : null}
        </p>
        <div className="g-portal__header-actions">
          <button
            type="button"
            className="g-host-button g-host-button--ghost"
            onClick={() => router.push("/app/onboarding/select-role?switch=1")}
          >
            Switch role
          </button>
          <button type="button" className="g-host-button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>
      <div className="g-portal__body">
        <aside className="g-portal__navigate" aria-label="Navigate">
          <p className="g-portal__navigate-title">Navigate</p>
          <OperatorNavTree nodes={nodes} currentPath={pathname} />
        </aside>
        <section className="g-portal__workspace">{children}</section>
      </div>
      <footer className="g-portal__status">
        <span className="g-portal__live" aria-hidden />
        Session scope {session.activeScopeId ?? "—"}
      </footer>
    </div>
  );
}
