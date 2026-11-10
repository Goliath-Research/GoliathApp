"use client";

import { useState } from "react";

type Props = {
  roles: Array<{ role_id: number; role_name: string }>;
  users: Array<{ user_id: number; full_name: string }>;
  navNodes: Array<{ node_id: number; caption: string; node_path: string | null }>;
};

export function AdminGrantsWorkspace({ roles, users, navNodes }: Props) {
  const [roleId, setRoleId] = useState(roles[0]?.role_id ?? 0);
  const [nodeId, setNodeId] = useState(navNodes[0]?.node_id ?? 0);
  const [userId, setUserId] = useState(users[0]?.user_id ?? 0);
  const [caption, setCaption] = useState("New module");
  const [nodePath, setNodePath] = useState("/app/your-module");
  const [parentId, setParentId] = useState<number | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  async function post(body: Record<string, unknown>) {
    const res = await fetch("/api/portal/model", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = (await res.json().catch(() => ({}))) as { error?: string };
    if (!res.ok) throw new Error(payload.error ?? `Failed (${res.status})`);
  }

  async function grantNav(e: React.FormEvent) {
    e.preventDefault();
    try {
      await post({ action: "grant_role_nav_node", roleId, nodeId });
      setStatus("Nav grant saved.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Grant failed");
    }
  }

  async function grantUserRole(e: React.FormEvent) {
    e.preventDefault();
    try {
      await post({ action: "grant_user_role", targetUserId: userId, roleId });
      setStatus("User role grant saved.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Grant failed");
    }
  }

  async function registerNode(e: React.FormEvent) {
    e.preventDefault();
    try {
      await post({
        action: "nav_register_node",
        parentNavId: parentId,
        caption,
        seq: 50,
        nodePath,
      });
      setStatus("Nav node registered. Reload to see it in the tree.");
      window.location.reload();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Register failed");
    }
  }

  return (
    <div className="g-admin-grants">
      {status ? <p role="status">{status}</p> : null}
      <form className="g-portal-form" onSubmit={registerNode}>
        <h3>NavTree</h3>
        <label>
          Parent nav ID (optional)
          <input
            type="number"
            value={parentId ?? ""}
            onChange={(e) => setParentId(e.target.value ? Number(e.target.value) : null)}
          />
        </label>
        <label>
          Caption
          <input value={caption} onChange={(e) => setCaption(e.target.value)} />
        </label>
        <label>
          Node path
          <input value={nodePath} onChange={(e) => setNodePath(e.target.value)} />
        </label>
        <button type="submit">Register node</button>
      </form>
      <form className="g-portal-form" onSubmit={grantNav}>
        <h3>Grant role → nav node (active scope)</h3>
        <label>
          Role
          <select value={roleId} onChange={(e) => setRoleId(Number(e.target.value))}>
            {roles.map((r) => (
              <option key={r.role_id} value={r.role_id}>
                {r.role_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Nav node
          <select value={nodeId} onChange={(e) => setNodeId(Number(e.target.value))}>
            {navNodes.map((n) => (
              <option key={n.node_id} value={n.node_id}>
                {n.caption} {n.node_path ?? ""}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Grant nav</button>
      </form>
      <form className="g-portal-form" onSubmit={grantUserRole}>
        <h3>Grant role → user (active scope)</h3>
        <label>
          User
          <select value={userId} onChange={(e) => setUserId(Number(e.target.value))}>
            {users.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.full_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Role
          <select value={roleId} onChange={(e) => setRoleId(Number(e.target.value))}>
            {roles.map((r) => (
              <option key={r.role_id} value={r.role_id}>
                {r.role_name}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Grant role</button>
      </form>
    </div>
  );
}
