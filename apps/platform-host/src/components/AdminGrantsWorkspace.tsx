"use client";

import { RecordDialog, RecordGrid } from "@goliath/platform-ui";
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

  const [dialog, setDialog] = useState<"node" | "nav-grant" | "user-grant" | null>(null);
  const roleSelect = (
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
  );
  const node = navNodes.find((n) => n.node_id === nodeId);
  const user = users.find((u) => u.user_id === userId);

  return (
    <div className="g-admin-grants">
      {status ? <p role="status">{status}</p> : null}
      <RecordGrid
        title="NavTree"
        noun="node"
        columns={[
          { key: "node_id", label: "ID" },
          { key: "caption", label: "Caption" },
          { key: "node_path", label: "Path" },
        ]}
        rows={navNodes}
        rowKey={(n) => String(n.node_id)}
        rowLabel={(n) => n.caption}
        onAdd={() => setDialog("node")}
        rowActions={[
          {
            id: "grant",
            label: "Grant to role",
            onRun: (n) => {
              setNodeId(n.node_id);
              setDialog("nav-grant");
            },
          },
        ]}
        testId="record-grid-nav_node"
      />
      <RecordGrid
        title="Users"
        noun="user"
        columns={[
          { key: "user_id", label: "ID" },
          { key: "full_name", label: "Name" },
        ]}
        rows={users}
        rowKey={(u) => String(u.user_id)}
        rowLabel={(u) => u.full_name}
        rowActions={[
          {
            id: "grant",
            label: "Grant role",
            onRun: (u) => {
              setUserId(u.user_id);
              setDialog("user-grant");
            },
          },
        ]}
        testId="record-grid-grant_user"
      />
      <RecordDialog open={dialog === "node"} title="New navigation node" onClose={() => setDialog(null)}>
        <form className="g-portal-form" onSubmit={registerNode}>
          <label>
            Parent node
            <select
              value={parentId ?? ""}
              onChange={(e) => setParentId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">(top level)</option>
              {navNodes.map((n) => (
                <option key={n.node_id} value={n.node_id}>
                  {n.caption} {n.node_path ?? ""}
                </option>
              ))}
            </select>
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
      </RecordDialog>
      <RecordDialog
        open={dialog === "nav-grant"}
        title={`Grant ${node?.caption ?? "node"} to a role (active scope)`}
        onClose={() => setDialog(null)}
      >
        <form className="g-portal-form" onSubmit={(e) => void grantNav(e).then(() => setDialog(null))}>
          {roleSelect}
          <button type="submit">Grant nav</button>
        </form>
      </RecordDialog>
      <RecordDialog
        open={dialog === "user-grant"}
        title={`Grant a role to ${user?.full_name ?? "user"} (active scope)`}
        onClose={() => setDialog(null)}
      >
        <form className="g-portal-form" onSubmit={(e) => void grantUserRole(e).then(() => setDialog(null))}>
          {roleSelect}
          <button type="submit">Grant role</button>
        </form>
      </RecordDialog>
    </div>
  );
}
