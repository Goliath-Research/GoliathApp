"use client";

import { PlatformRecordTable } from "@goliath/platform-ui";
import { formatRoleGrantLabel } from "@/lib/admin-user-roles";
import { useCallback, useEffect, useMemo, useState } from "react";

type UserRow = {
  user_id: number;
  full_name: string;
  email?: string;
  active?: number;
  scoped_role_count?: number;
  active_roles_summary?: string | null;
  sign_in_status?: string;
  identity_provider_name?: string | null;
};
type RoleRow = { role_id: number; role_name: string };
type ProviderRow = { provider_id: number; provider_name: string; issuer: string };
type GrantRow = {
  grant_id: number;
  user_id: number;
  role_id: number;
  role_name: string;
  scope_name?: string | null;
};

type Props = {
  users: UserRow[];
  roles: RoleRow[];
  signInUrl: string;
};

function signInStatusLabel(status: string | undefined, providerName: string | null | undefined): string {
  switch (status) {
    case "linked":
      return "Linked";
    case "awaiting_first_sign_in":
      return providerName ? `Awaiting first ${providerName} sign-in` : "Awaiting first sign-in";
    case "no_provider":
      return "No identity provider on scope";
    default:
      return status ?? "—";
  }
}

export function AdminUsersWorkspace({ users: initialUsers, roles, signInUrl }: Props) {
  const [users, setUsers] = useState(initialUsers);
  const [providers, setProviders] = useState<ProviderRow[]>([]);
  const [grants, setGrants] = useState<GrantRow[]>([]);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [targetUserId, setTargetUserId] = useState(initialUsers[0]?.user_id ?? 0);
  const [roleId, setRoleId] = useState<number | "">(roles[0]?.role_id ?? "");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRoleId, setInviteRoleId] = useState<number | "">(roles[0]?.role_id ?? "");
  const [inviteProviderId, setInviteProviderId] = useState<number | "">("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const validRoles = useMemo(() => roles.filter((r) => Number.isFinite(r.role_id) && r.role_id > 0), [roles]);

  const refreshUsers = useCallback(async () => {
    const res = await fetch("/api/portal/security", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "list_users_admin" }),
    });
    const payload = (await res.json().catch(() => ({}))) as {
      users?: UserRow[];
      error?: string;
    };
    if (res.ok && payload.users) {
      setUsers(payload.users);
    }
  }, []);

  const refreshGrants = useCallback(async (userId: number) => {
    if (!userId) {
      setGrants([]);
      return;
    }
    const res = await fetch("/api/portal/security", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "list_user_role_grants", targetUserId: userId }),
    });
    const payload = (await res.json().catch(() => ({}))) as { grants?: GrantRow[]; error?: string };
    if (res.ok && payload.grants) {
      setGrants(payload.grants);
    }
  }, []);

  useEffect(() => {
    void refreshGrants(targetUserId);
  }, [targetUserId, refreshGrants]);

  useEffect(() => {
    void fetch("/api/portal/security", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "list_scope_identity_providers" }),
    })
      .then((res) => res.json())
      .then((payload: { providers?: ProviderRow[] }) => {
        const rows = payload.providers ?? [];
        setProviders(rows);
        if (rows.length === 1) {
          setInviteProviderId(rows[0].provider_id);
        }
      })
      .catch(() => undefined);
  }, []);

  async function post(body: Record<string, unknown>) {
    const res = await fetch("/api/portal/security", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = (await res.json().catch(() => ({}))) as { error?: string };
    if (!res.ok) throw new Error(payload.error ?? `Failed (${res.status})`);
    return payload;
  }

  async function copySignInLink() {
    try {
      await navigator.clipboard.writeText(signInUrl);
      setStatus("Sign-in link copied.");
    } catch {
      setStatus(`Share this sign-in URL: ${signInUrl}`);
    }
  }

  const userColumns = [
    { key: "user_id", label: "ID" },
    { key: "full_name", label: "Name" },
    { key: "email", label: "Email" },
    { key: "active", label: "Active" },
    { key: "sign_in_label", label: "Sign-in" },
    { key: "roles_label", label: "Roles" },
  ];

  const userRows = users.map((u) => {
    const summary = u.active_roles_summary?.trim();
    const rolesLabel =
      summary && summary.length > 0
        ? summary
        : (u.scoped_role_count ?? 0) === 0
          ? "None — grant role"
          : "—";
    return {
      ...u,
      sign_in_label: signInStatusLabel(u.sign_in_status, u.identity_provider_name),
      roles_label: rolesLabel,
    };
  });

  return (
    <div className="g-admin-users">
      <PlatformRecordTable caption="Users" columns={userColumns} rows={userRows} />
      <section className="g-portal-form" aria-labelledby="user-grants-heading">
        <h3 id="user-grants-heading">Active role grants (active scope)</h3>
        <label>
          User
          <select
            value={targetUserId}
            onChange={(ev) => {
              const id = Number(ev.target.value);
              setTargetUserId(id);
            }}
          >
            {users.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.full_name} ({u.email})
              </option>
            ))}
          </select>
        </label>
        {grants.length === 0 ? (
          <p role="status">No active scoped role grants for this user.</p>
        ) : (
          <ul className="g-admin-grant-list">
            {grants.map((g) => (
              <li key={g.grant_id}>
                <span>{formatRoleGrantLabel(g)}</span>
                <button
                  type="button"
                  className="g-button-secondary"
                  onClick={() => {
                    setError(null);
                    void post({ action: "revoke_user_role_grant", grantId: g.grant_id })
                      .then(() => {
                        setStatus(`Revoked ${formatRoleGrantLabel(g)}.`);
                        void refreshGrants(targetUserId);
                        void refreshUsers();
                      })
                      .catch((err) => setError(err instanceof Error ? err.message : "Failed"));
                  }}
                >
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <form
        className="g-portal-form"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          void post({ action: "upsert_user", email, fullName, active: 1 })
            .then(() => {
              setStatus(
                "User saved. They can sign in with the organization identity provider once a role is granted (no password; no email is sent from this host).",
              );
              void refreshUsers();
            })
            .catch((err) => setError(err instanceof Error ? err.message : "Failed"));
        }}
      >
        <h3>Create / update user</h3>
        <label>
          Email
          <input value={email} onChange={(ev) => setEmail(ev.target.value)} required type="email" />
        </label>
        <label>
          Full name
          <input value={fullName} onChange={(ev) => setFullName(ev.target.value)} required />
        </label>
        <button type="submit">Save user</button>
      </form>
      <form
        className="g-portal-form"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          if (roleId === "" || !Number.isFinite(Number(roleId))) {
            setError("Choose a role.");
            return;
          }
          void post({ action: "grant_user_role", targetUserId, roleId: Number(roleId) })
            .then(() => {
              setStatus("Role granted in active scope.");
              void refreshUsers();
              void refreshGrants(targetUserId);
            })
            .catch((err) => setError(err instanceof Error ? err.message : "Failed"));
        }}
      >
        <h3>Assign role (scoped)</h3>
        <label>
          User
          <select value={targetUserId} onChange={(ev) => setTargetUserId(Number(ev.target.value))}>
            {users.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.full_name} ({u.email})
              </option>
            ))}
          </select>
        </label>
        <label>
          Role
          <select value={roleId} onChange={(ev) => setRoleId(ev.target.value === "" ? "" : Number(ev.target.value))}>
            <option value="">Select role…</option>
            {validRoles.map((r) => (
              <option key={r.role_id} value={r.role_id}>
                {r.role_name}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Grant role</button>
      </form>
      <form
        className="g-portal-form"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          if (inviteRoleId === "" || !Number.isFinite(Number(inviteRoleId))) {
            setError("Choose a default role for the invitation.");
            return;
          }
          if (providers.length > 1 && (inviteProviderId === "" || !Number.isFinite(Number(inviteProviderId)))) {
            setError("Choose an identity provider for this scope.");
            return;
          }
          void post({
            action: "invite_user",
            email: inviteEmail,
            defaultRoleId: Number(inviteRoleId),
            expectedProviderId:
              inviteProviderId === "" ? undefined : Number(inviteProviderId),
          })
            .then(() => {
              setStatus(
                "Invitation recorded. The person can sign in with the matching identity provider — no email is sent unless outbound email is configured.",
              );
              setInviteEmail("");
            })
            .catch((err) => setError(err instanceof Error ? err.message : "Failed"));
        }}
      >
        <h3>Invite user</h3>
        <p className="g-host-home__lead">
          Invitations are fulfilled on first successful sign-in (verified email + provider). No invitation email is sent from this host.
        </p>
        <label>
          Email
          <input value={inviteEmail} onChange={(ev) => setInviteEmail(ev.target.value)} required type="email" />
        </label>
        <label>
          Default role
          <select
            value={inviteRoleId}
            onChange={(ev) => setInviteRoleId(ev.target.value === "" ? "" : Number(ev.target.value))}
            required
          >
            <option value="">Select role…</option>
            {validRoles.map((r) => (
              <option key={r.role_id} value={r.role_id}>
                {r.role_name}
              </option>
            ))}
          </select>
        </label>
        {providers.length > 1 ? (
          <label>
            Identity provider
            <select
              value={inviteProviderId}
              onChange={(ev) => setInviteProviderId(ev.target.value === "" ? "" : Number(ev.target.value))}
              required
            >
              <option value="">Select provider…</option>
              {providers.map((p) => (
                <option key={p.provider_id} value={p.provider_id}>
                  {p.provider_name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="g-portal-form__actions">
          <button type="submit">Record invitation</button>
          <button type="button" className="g-button-secondary" onClick={() => void copySignInLink()}>
            Copy sign-in link
          </button>
        </div>
      </form>
      {error ? (
        <p role="alert" className="g-admin-error">
          {error}
        </p>
      ) : null}
      {status ? <p role="status">{status}</p> : null}
    </div>
  );
}
