import { portalSessionCall } from "@/server/portal/bridge";

/** One node of a Meta tree (sp_session_meta_tree_list). */
export type MetaTreeRow = {
  objId: number;
  parentObjId: number | null;
  className: string;
  displayLabel: string;
  seq: number | null;
  depth: number;
  childCount: number;
};

export type MetaTreeClassRow = { className: string; linkId: number; linkName: string; declaredOn: string };

export async function listMetaTreeClasses(token: string): Promise<MetaTreeClassRow[]> {
  const rows = await portalSessionCall(token, "SELECT * FROM portal.sp_session_meta_tree_classes($1)");
  return rows.map((r) => ({
    className: String(r.class_name),
    linkId: Number(r.link_id),
    linkName: String(r.link_name),
    declaredOn: String(r.declared_on),
  }));
}

export async function listMetaTree(token: string, className: string): Promise<MetaTreeRow[]> {
  const rows = await portalSessionCall(token, "SELECT * FROM portal.sp_session_meta_tree_list($1, $2)", [className]);
  return rows.map((r) => ({
    objId: Number(r.obj_id),
    parentObjId: r.parent_obj_id == null ? null : Number(r.parent_obj_id),
    className: String(r.class_name),
    displayLabel: String(r.display_label ?? ""),
    seq: r.seq == null ? null : Number(r.seq),
    depth: Number(r.depth ?? 0),
    childCount: Number(r.child_count ?? 0),
  }));
}

export async function moveMetaTreeNode(
  token: string,
  className: string,
  objId: number,
  parentObjId: number | null,
  position: number | null,
): Promise<number> {
  const rows = await portalSessionCall(
    token,
    "SELECT portal.sp_session_meta_tree_move($1, $2, $3::int, $4::int, $5::int) AS pos",
    [className, objId, parentObjId, position],
  );
  return Number(rows[0]?.pos ?? 0);
}

export async function deleteMetaTreeNode(token: string, className: string, objId: number): Promise<void> {
  await portalSessionCall(token, "SELECT portal.sp_session_meta_tree_delete($1, $2, $3::int) AS r", [
    className,
    objId,
  ]);
}

/** Whether a class is tree-shaped; false when the caller cannot see the tree catalog. */
export async function isMetaTreeClass(token: string, className: string): Promise<boolean> {
  try {
    return (await listMetaTreeClasses(token)).some((c) => c.className === className);
  } catch {
    return false;
  }
}
