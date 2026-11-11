"use client";

import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

type SelectableRole = { roleId: number; roleName: string };

export function SelectActiveRoleWorkspace({
  initialRoles,
  switchMode,
}: {
  initialRoles: SelectableRole[];
  switchMode?: boolean;
}) {
  const router = useRouter();
  const [roles, setRoles] = useState(initialRoles);
  const [pendingRoleId, setPendingRoleId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (initialRoles.length > 0) return;
    void (async () => {
      const res = await fetch("/api/session/roles", { credentials: "same-origin" });
      if (!res.ok) return;
      const body = (await res.json()) as { roles: SelectableRole[] };
      setRoles(body.roles ?? []);
    })();
  }, [initialRoles.length]);

  const submit = useCallback(
    async (roleId: number) => {
      setLoading(true);
      setError(null);
      setPendingRoleId(roleId);
      try {
        const res = await fetch("/api/session/active-role", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ roleId }),
        });
        const body = (await res.json().catch(() => ({}))) as { error?: string };
        if (!res.ok) {
          setError(body.error ?? "Could not set active role");
          return;
        }
        router.push("/app");
        router.refresh();
      } finally {
        setLoading(false);
        setPendingRoleId(null);
      }
    },
    [router],
  );

  return (
    <RolePickerSection switchMode={switchMode} roles={roles} error={error}>
      <ul className="g-role-picker__list">
        {roles.map((role) => (
          <li key={role.roleId}>
            <button
              type="button"
              className="g-host-button g-role-picker__option"
              disabled={loading}
              onClick={() => void submit(role.roleId)}
            >
              {pendingRoleId === role.roleId ? "Selecting…" : role.roleName}
            </button>
          </li>
        ))}
      </ul>
    </RolePickerSection>
  );
}

function RolePickerSection({
  switchMode,
  roles,
  error,
  children,
}: {
  switchMode?: boolean;
  roles: SelectableRole[];
  error: string | null;
  children: ReactNode;
}) {
  return (
    <>
      <h1 className="g-onboarding__title">{switchMode ? "Switch active role" : "Choose your role"}</h1>
      <p className="g-onboarding__lead">
        {switchMode
          ? "The portal uses one role per session. Permissions and navigation follow the role you select."
          : "You have more than one role in this scope. Select which role this session should use."}
      </p>
      {roles.length === 0 ? (
        <p className="g-onboarding__muted">No selectable roles were returned for this scope.</p>
      ) : (
        children
      )}
      {error ? <p className="g-onboarding__error">{error}</p> : null}
    </>
  );
}
