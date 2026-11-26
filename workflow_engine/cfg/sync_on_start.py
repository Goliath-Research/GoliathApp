"""Mandatory cfg → /work sync before a study run starts."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from goliath_worker import platform_env  # noqa: E402

from .safe_paths import open_dir, safe_segment, write_file_at
from .store import FileConfigStore
from .study_membership import materialize_study_membership

logger = logging.getLogger(__name__)


def resolve_work_root(context: Mapping[str, Any] | None = None) -> Path:
    ctx = context or {}
    raw = (
        ctx.get("workRoot")
        or ctx.get("work_root")
        or str(platform_env.resolve_work_root())
    )
    return Path(str(raw))


def resolve_cfg_store_dir() -> Optional[Path]:
    return platform_env.resolve_cfg_store_dir()


def resolve_study_name(context: Mapping[str, Any]) -> Optional[str]:
    for key in ("cfgStudyName", "studyName", "study"):
        val = context.get(key)
        if val not in (None, ""):
            return str(val)
    project = context.get("project")
    if isinstance(project, dict):
        for key in ("project_name", "projectName", "name"):
            val = project.get(key)
            if val not in (None, ""):
                return str(val)
    project_path = context.get("projectPath") or context.get("project_path")
    if project_path:
        stem = Path(str(project_path)).stem
        if stem.startswith("project_"):
            return stem[len("project_") :]
        return stem
    return None


def resolve_study_row_id(context: Mapping[str, Any]) -> Optional[int]:
    for key in ("cfgStudyRowId", "studyRowId", "study_row_id"):
        val = context.get(key)
        if val is not None and str(val).strip() != "":
            return int(val)
    return None


def _csv_bytes_from_keys(sample_keys: str | None) -> bytes:
    keys = []
    if sample_keys:
        keys = [k.strip() for k in str(sample_keys).splitlines() if k.strip()]
    lines = ["sample"] + sorted(keys)
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _split_db_csv_path(
    csv_path: str, work_root: Path, list_filename: Any
) -> tuple[str, str]:
    """Return (studyId, filename) for ``<work_root>/projects/<studyId>/data/<filename>``."""
    prefix = str(work_root).rstrip("/") + "/projects/"
    if not csv_path.startswith(prefix):
        raise ValueError(f"db csv_path is not under {prefix}: {csv_path!r}")
    parts = csv_path[len(prefix) :].split("/")
    if len(parts) != 3 or parts[1] != "data":
        raise ValueError(f"db csv_path is not <studyId>/data/<file>: {csv_path!r}")
    study_id = safe_segment(parts[0], what="studyId")
    filename = safe_segment(parts[2], what="listFilename")
    if list_filename is not None and str(list_filename) != filename:
        raise ValueError(
            f"db csv_path {csv_path!r} does not end in list_filename {list_filename!r}"
        )
    return study_id, filename


def _sync_from_db(
    db: Any,
    *,
    study_row_id: int,
    work_root: Path,
) -> Dict[str, Any]:
    """Call cfg_repo_materialize_study_lists and write returned CSV paths."""
    written: list[str] = []
    rows: list[Any] = []
    # Backend-agnostic: prefer a helper if present, else raw SQL shapes.
    if hasattr(db, "cfg_materialize_study_lists"):
        rows = list(db.cfg_materialize_study_lists(study_row_id, str(work_root)))
    elif hasattr(db, "execute"):
        # Best-effort dialect-agnostic call sites use named helpers elsewhere.
        raise RuntimeError(
            "db adapter missing cfg_materialize_study_lists; "
            "use FileConfigStore sync or extend the gateway DB client"
        )
    else:
        raise RuntimeError("unsupported db object for study work sync")

    planned: list[tuple[str, bytes]] = []
    bound_study_id: Optional[str] = None
    for row in rows:
        if isinstance(row, Mapping):
            csv_path = row.get("csv_path") or row.get("csvPath")
            sample_keys = row.get("sample_keys") or row.get("sampleKeys")
            list_filename = row.get("list_filename") or row.get("listFilename")
        else:
            # tuple-like: study_group_id, role, label, list_filename, csv_path, sample_keys
            list_filename = row[3] if len(row) > 3 else None
            csv_path = row[4] if len(row) > 4 else None
            sample_keys = row[5] if len(row) > 5 else None
        if not csv_path:
            continue
        study_id, filename = _split_db_csv_path(str(csv_path), work_root, list_filename)
        if bound_study_id is None:
            bound_study_id = study_id
        elif study_id != bound_study_id:
            raise ValueError(
                f"db rows for study row {study_row_id} name more than one studyId: "
                f"{bound_study_id!r}, {study_id!r}"
            )
        planned.append((filename, _csv_bytes_from_keys(sample_keys)))

    if bound_study_id is not None:
        data_dir = work_root / "projects" / bound_study_id / "data"
        data_fd = open_dir(work_root, ["projects", bound_study_id, "data"])
        try:
            for filename, data in planned:
                write_file_at(data_fd, filename, data)
                written.append(str(data_dir / filename))
        finally:
            os.close(data_fd)
    return {"source": "db", "studyRowId": study_row_id, "written": written}


def ensure_study_work_synced(
    context: Mapping[str, Any] | Dict[str, Any],
    *,
    work_root: Path | str | None = None,
    store: Optional[FileConfigStore] = None,
    db: Any = None,
    study_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Synchronize published cfg study membership onto ``/work`` before a run.

    - No-op when there is no cfg store and no ``study_row_id`` (legacy file-only studies).
    - When the study is in the cfg store (with or without ``studyGroups``), rewrite
      project JSON and membership CSVs under the work root.
    - When ``db`` + ``cfgStudyRowId`` are provided, also run DB materialize and write CSVs.
    - Raises on failure when cfg membership exists so runs never start against stale lists.
    """
    out = dict(context)
    if out.get("cfgWorkSynced") and out.get("skipCfgWorkSync"):
        return out
    if out.get("skipCfgWorkSync"):
        out["cfgWorkSynced"] = False
        return out

    root = Path(work_root) if work_root else resolve_work_root(out)
    name = study_name or resolve_study_name(out)
    row_id = resolve_study_row_id(out)
    sync_meta: Dict[str, Any] = {"workRoot": str(root), "studyName": name, "written": []}

    store_obj = store
    if store_obj is None:
        store_dir = resolve_cfg_store_dir()
        if store_dir is not None:
            store_obj = FileConfigStore(store_dir)

    try:
        if store_obj is not None and name:
            # Always refresh published study document + membership CSVs when present.
            rec = store_obj.get("study", name, published_only=True)
            if rec is not None:
                result = materialize_study_membership(
                    store_obj, root, study_name=name
                )
                sync_meta["source"] = "file_store"
                sync_meta["written"].extend(result.get("written") or [])
                # Use the project JSON this sync wrote, not a path re-derived from the store.
                synced_project = next(
                    (
                        p["projectPath"]
                        for p in result.get("projects") or []
                        if p.get("name") == rec.name and p.get("version") == rec.version
                    ),
                    None,
                )
                if synced_project:
                    out["projectPath"] = synced_project
                    # Reload document after membership sync
                    refreshed = store_obj.get("study", name, published_only=True)
                    if refreshed is not None:
                        out.setdefault("project", refreshed.document)

        if db is not None and row_id is not None:
            db_result = _sync_from_db(db, study_row_id=row_id, work_root=root)
            sync_meta["db"] = db_result
            sync_meta["written"].extend(db_result.get("written") or [])

    except Exception as exc:
        logger.error("cfg → /work study sync failed: %s", exc)
        raise RuntimeError(
            f"study work area sync failed before run start ({name or row_id}): {exc}"
        ) from exc

    out["cfgWorkSynced"] = True
    out["cfgWorkSync"] = sync_meta
    logger.info(
        "cfg → /work study sync ok study=%s written=%d",
        name or row_id,
        len(sync_meta["written"]),
    )
    return out
