"use client";

import { useCallback, useEffect, useState } from "react";

type AccessRow = {
  access_id: number;
  role_id: number;
  role_name: string;
  class_name: string;
  action: string;
  effect: string;
  declared_depth: number;
};

type Props = {
  className: string;
  roles: Array<{ role_id: number; role_name: string }>;
};

async function securityPost(body: Record<string, unknown>) {
  const res = await fetch("/api/portal/security", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = (await res.json().catch(() => ({}))) as {
    error?: string;
    rows?: AccessRow[];
    allowed?: boolean;
  };
  if (!res.ok) throw new Error(payload.error ?? `Failed (${res.status})`);
  return payload;
}

export function MetaClassSecurityPanel({ className, roles }: Props) {
  const [rows, setRows] = useState<AccessRow[]>([]);
  const [roleId, setRoleId] = useState(roles[0]?.role_id ?? 0);
  const [action, setAction] = useState("read");
  const [effect, setEffect] = useState("allow");
  const [status, setStatus] = useState<string | null>(null);
  const [checkUserId, setCheckUserId] = useState("");
  const [checkResult, setCheckResult] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const payload = await securityPost({ action: "list_class_access", className });
    setRows((payload.rows as AccessRow[]) ?? []);
  }, [className]);

  useEffect(() => {
    void reload().catch(() => setRows([]));
  }, [reload]);

  async function saveGrant(e: React.FormEvent) {
    e.preventDefault();
    setStatus(null);
    try {
      await securityPost({
        action: "upsert_class_access",
        className,
        roleId,
        metaAction: action,
        effect,
      });
      setStatus("Class permission saved.");
      await reload();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function runCheck(e: React.FormEvent) {
    e.preventDefault();
    setCheckResult(null);
    try {
      const payload = await securityPost({
        action: "effective_check",
        targetUserId: Number(checkUserId),
        className,
        metaAction: action,
      });
      setCheckResult(payload.allowed ? "Allowed" : "Denied");
    } catch (err) {
      setCheckResult(err instanceof Error ? err.message : "Check failed");
    }
  }

  return (
    <div className="g-meta-security">
      <p className="g-host-home__lead">
        Class-level grants inherit down the hierarchy; subclass rules override parent rules. Deny wins for a role.
      </p>
      {status ? <p role="status">{status}</p> : null}
      <form className="g-portal-form" onSubmit={saveGrant}>
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
        <label>
          Action
          <select value={action} onChange={(ev) => setAction(ev.target.value)}>
            {["read", "create", "update", "delete", "author"].map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <label>
          Effect
          <select value={effect} onChange={(ev) => setEffect(ev.target.value)}>
            <option value="allow">allow</option>
            <option value="deny">deny</option>
          </select>
        </label>
        <button type="submit">Save class grant</button>
      </form>
      <table className="g-host-table">
        <thead>
          <tr>
            <th scope="col">Role</th>
            <th scope="col">On class</th>
            <th scope="col">Depth</th>
            <th scope="col">Action</th>
            <th scope="col">Effect</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.access_id}>
              <td>{r.role_name}</td>
              <td>{r.class_name}</td>
              <td>{r.declared_depth}</td>
              <td>{r.action}</td>
              <td>{r.effect}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="g-portal-form" onSubmit={runCheck}>
        <h4>Effective permissions checker</h4>
        <label>
          User ID
          <input value={checkUserId} onChange={(ev) => setCheckUserId(ev.target.value)} required />
        </label>
        <button type="submit">Check read on this class</button>
        {checkResult ? <p role="status">{checkResult}</p> : null}
      </form>
    </div>
  );
}
