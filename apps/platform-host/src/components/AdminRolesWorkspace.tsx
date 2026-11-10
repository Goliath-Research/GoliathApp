"use client";

import { PlatformRecordTable } from "@goliath/platform-ui";
import { useState } from "react";

type RoleRow = { role_id: number; role_name?: string; name?: string };
type PermRow = { permission_id: number; name: string; role_id?: number };

type Props = {
  roles: RoleRow[];
  permissions: PermRow[];
};

export function AdminRolesWorkspace({ roles, permissions }: Props) {
  const [roleName, setRoleName] = useState("");
  const [roleId, setRoleId] = useState(roles[0]?.role_id ?? 0);
  const [permName, setPermName] = useState(permissions[0]?.name ?? "meta.object.read");
  const [granted, setGranted] = useState(true);
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

  const roleRows = roles.map((r) => ({
    role_id: r.role_id,
    name: r.role_name ?? r.name ?? "",
  }));

  return (
    <div className="g-admin-roles">
      <PlatformRecordTable
        caption="Roles"
        columns={[
          { key: "role_id", label: "ID" },
          { key: "name", label: "Name" },
        ]}
        rows={roleRows}
      />
      <form
        className="g-portal-form"
        onSubmit={(e) => {
          e.preventDefault();
          void post({ action: "create_role", name: roleName })
            .then(() => setStatus(`Role ${roleName} created. Reload to refresh.`))
            .catch((err) => setStatus(err instanceof Error ? err.message : "Failed"));
        }}
      >
        <h3>Create role</h3>
        <label>
          Name
          <input value={roleName} onChange={(ev) => setRoleName(ev.target.value)} required />
        </label>
        <button type="submit">Create</button>
      </form>
      <form
        className="g-portal-form"
        onSubmit={(e) => {
          e.preventDefault();
          void post({ action: "set_role_permission", roleId, permissionName: permName, granted })
            .then(() => setStatus("Role permission updated."))
            .catch((err) => setStatus(err instanceof Error ? err.message : "Failed"));
        }}
      >
        <h3>Role → permission</h3>
        <label>
          Role
          <select value={roleId} onChange={(ev) => setRoleId(Number(ev.target.value))}>
            {roleRows.map((r) => (
              <option key={r.role_id} value={r.role_id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Permission
          <select value={permName} onChange={(ev) => setPermName(ev.target.value)}>
            {permissions.map((p) => (
              <option key={p.permission_id} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={granted} onChange={(ev) => setGranted(ev.target.checked)} />
          Granted
        </label>
        <button type="submit">Save</button>
      </form>
      <PlatformRecordTable
        caption="Permission catalog"
        columns={[
          { key: "permission_id", label: "ID" },
          { key: "name", label: "Name" },
        ]}
        rows={permissions}
      />
      {status ? <p role="status">{status}</p> : null}
    </div>
  );
}
