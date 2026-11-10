"use client";

import { PlatformRecordTable } from "@goliath/platform-ui";
import { useState } from "react";

type UserRow = { user_id: number; full_name: string; email?: string; active?: number };
type RoleRow = { role_id: number; role_name: string };

type Props = {
  users: UserRow[];
  roles: RoleRow[];
};

export function AdminUsersWorkspace({ users, roles }: Props) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [targetUserId, setTargetUserId] = useState(users[0]?.user_id ?? 0);
  const [roleId, setRoleId] = useState(roles[0]?.role_id ?? 0);
  const [inviteEmail, setInviteEmail] = useState("");
  const [status, setStatus] = useState<string | null>(null);

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

  return (
    <div className="g-admin-users">
      <PlatformRecordTable
        caption="Users"
        columns={[
          { key: "user_id", label: "ID" },
          { key: "full_name", label: "Name" },
          { key: "email", label: "Email" },
          { key: "active", label: "Active" },
        ]}
        rows={users}
      />
      <form
        className="g-portal-form"
        onSubmit={(e) => {
          e.preventDefault();
          void post({ action: "upsert_user", email, fullName, active: 1 })
            .then(() => {
              setStatus("User saved. Reload to refresh list.");
            })
            .catch((err) => setStatus(err instanceof Error ? err.message : "Failed"));
        }}
      >
        <h3>Create / update user</h3>
        <label>
          Email
          <input value={email} onChange={(ev) => setEmail(ev.target.value)} required />
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
          void post({ action: "grant_user_role", targetUserId, roleId })
            .then(() => setStatus("Role granted in active scope."))
            .catch((err) => setStatus(err instanceof Error ? err.message : "Failed"));
        }}
      >
        <h3>Assign role (scoped)</h3>
        <label>
          User
          <select value={targetUserId} onChange={(ev) => setTargetUserId(Number(ev.target.value))}>
            {users.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.full_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Role
          <select value={roleId} onChange={(ev) => setRoleId(Number(ev.target.value))}>
            {roles.map((r) => (
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
          void post({ action: "invite_user", email: inviteEmail, defaultRoleId: roleId })
            .then(() => setStatus("Invitation created."))
            .catch((err) => setStatus(err instanceof Error ? err.message : "Failed"));
        }}
      >
        <h3>Invite user</h3>
        <label>
          Email
          <input value={inviteEmail} onChange={(ev) => setInviteEmail(ev.target.value)} required />
        </label>
        <button type="submit">Send invitation</button>
      </form>
      {status ? <p role="status">{status}</p> : null}
    </div>
  );
}
