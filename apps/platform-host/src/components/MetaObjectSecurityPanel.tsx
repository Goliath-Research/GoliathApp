"use client";

import { useEffect, useState } from "react";

type Props = {
  objId: number;
  roles: Array<{ role_id: number; role_name: string }>;
};

export function MetaObjectSecurityPanel({ objId, roles }: Props) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [roleId, setRoleId] = useState(roles[0]?.role_id ?? 0);
  const [status, setStatus] = useState<string | null>(null);

  async function post(body: Record<string, unknown>) {
    const res = await fetch("/api/portal/security", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = (await res.json().catch(() => ({}))) as { error?: string; rows?: Record<string, unknown>[] };
    if (!res.ok) throw new Error(payload.error ?? `Failed (${res.status})`);
    return payload;
  }

  async function reload() {
    const payload = await post({ action: "list_object_access", objId });
    setRows(payload.rows ?? []);
  }

  useEffect(() => {
    void reload();
  }, [objId]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      await post({ action: "upsert_object_access", objId, roleId, metaAction: "read", effect: "deny" });
      setStatus("Object ACL saved.");
      await reload();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div className="g-meta-object-security">
      <h4>Object ACL</h4>
      {status ? <p role="status">{status}</p> : null}
      <form className="g-portal-form" onSubmit={save}>
        <label>
          Deny read for role
          <select value={roleId} onChange={(ev) => setRoleId(Number(ev.target.value))}>
            {roles.map((r) => (
              <option key={r.role_id} value={r.role_id}>
                {r.role_name}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Apply object deny (read)</button>
      </form>
      <table className="g-host-table">
        <thead>
          <tr>
            <th scope="col">Principal</th>
            <th scope="col">Action</th>
            <th scope="col">Effect</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{String(r.role_name ?? r.user_name ?? "—")}</td>
              <td>{String(r.action)}</td>
              <td>{String(r.effect)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
