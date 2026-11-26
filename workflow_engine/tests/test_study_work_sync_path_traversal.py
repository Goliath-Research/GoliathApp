"""Study work sync must not follow study id, study name, or list filename outside the study tree.

The published study document is the input (file cfg store, or the CSV path built the
same way as cfg.cfg_repo_materialize_study_lists). These tests fail while that input
can create or rewrite files outside the study directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

import pytest

from cfg.materialize import materialize_store
from cfg.store import FileConfigStore
from cfg.study_membership import study_data_dir
from cfg.sync_on_start import ensure_study_work_synced
from domain.workflow_context import finalize_instance_context
from rest.db_client import create_workflow_instance

ATTACK_MARKER = "ATTACKER-CHOSEN-SAMPLE"
VICTIM_BODY = "victim-original-sample-list\n"
OUTSIDE_BODY = "outside-original\n"


def _snapshot(root: Path) -> Dict[str, bytes]:
    """File and directory names under root, plus file bytes. Symlinks are not followed."""
    found: Dict[str, bytes] = {}
    if not root.exists():
        return found
    for path in root.rglob("*"):
        rel = str(path.relative_to(root))
        if path.is_symlink():
            found[rel] = b"symlink:" + str(path.readlink()).encode()
        elif path.is_file():
            found[rel] = path.read_bytes()
        elif path.is_dir():
            found[rel] = b"dir"
    return found


def _under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


def _assert_no_new_side_effects(before: Mapping[str, bytes], after: Mapping[str, bytes], allowed: Sequence[Path], base: Path) -> None:
    """Any created, rewritten, or removed path must stay under an allowed prefix."""
    allowed_resolved = [p.resolve() for p in allowed]

    def is_allowed(rel: str) -> bool:
        full = (base / rel).resolve()
        return any(full == root or _under(full, root) for root in allowed_resolved)

    for rel, content in after.items():
        if before.get(rel) != content and not is_allowed(rel):
            raise AssertionError(f"path changed outside the study directory: {base / rel}")
    for rel in before:
        if rel not in after and not is_allowed(rel):
            raise AssertionError(f"path removed outside the study directory: {base / rel}")


def _publish(
    store: FileConfigStore,
    *,
    name: str = "cohort-a",
    extra_study_id: Optional[str] = None,
    document_study_id: Optional[str] = None,
    document_study_id_camel: Optional[str] = None,
    list_filename: str = "controls.csv",
    with_group: bool = True,
) -> None:
    document: Dict[str, Any] = {"label": "cohort"}
    if document_study_id is not None:
        document["study_id"] = document_study_id
    if document_study_id_camel is not None:
        document["studyId"] = document_study_id_camel
    extra: Dict[str, Any] = {}
    if extra_study_id is not None:
        extra["studyId"] = extra_study_id
    if with_group:
        extra["studyGroups"] = [
            {
                "role": "control",
                "label": "ctrl",
                "listFilename": list_filename,
                "members": [
                    {"portalSampleId": 1, "processingSampleKey": ATTACK_MARKER},
                ],
            }
        ]
    store.upsert("study", name, document, status="published", extra=extra or None)


def _layout(tmp_path: Path) -> Dict[str, Path]:
    base = tmp_path / "base"
    work = base / "work"
    outside = base / "outside"
    victim = work / "projects" / "other-study" / "data" / "samples.csv"
    outside_file = outside / "marker.txt"
    victim.parent.mkdir(parents=True)
    outside.mkdir(parents=True)
    victim.write_text(VICTIM_BODY, encoding="utf-8")
    outside_file.write_text(OUTSIDE_BODY, encoding="utf-8")
    store = FileConfigStore(work / "goliath" / "cfg-store")
    return {
        "base": base,
        "work": work,
        "outside": outside,
        "victim": victim,
        "outside_file": outside_file,
        "store_dir": store.store_dir,
    }


def _assert_victims_intact(paths: Mapping[str, Path]) -> None:
    assert paths["victim"].read_text(encoding="utf-8") == VICTIM_BODY
    assert paths["outside_file"].read_text(encoding="utf-8") == OUTSIDE_BODY
    outside_text = ""
    if paths["outside"].exists():
        for child in paths["outside"].rglob("*"):
            if child.is_file() and not child.is_symlink():
                outside_text += child.read_text(encoding="utf-8", errors="replace")
    assert ATTACK_MARKER not in outside_text
    victim_root = paths["work"] / "projects" / "other-study"
    victim_text = ""
    for child in victim_root.rglob("*"):
        if child.is_file() and not child.is_symlink():
            victim_text += child.read_text(encoding="utf-8", errors="replace")
    assert ATTACK_MARKER not in victim_text


def _confined_project_strings(study_root: Path) -> None:
    """Paths recorded inside the study tree must still resolve under that tree."""
    if not study_root.exists():
        return
    for path in study_root.rglob("*.json"):
        if path.is_symlink():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        for value in _strings(document):
            candidate = Path(value)
            if not (candidate.is_absolute() or ".." in candidate.parts):
                continue
            resolved = candidate.resolve()
            assert _under(resolved, study_root), value


def _strings(value: Any) -> Sequence[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(_strings(item))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_strings(item))
        return out
    return []


def _run_sync(context: Dict[str, Any], store: FileConfigStore) -> Optional[Dict[str, Any]]:
    try:
        return ensure_study_work_synced(context, store=store)
    except Exception:
        return None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"extra_study_id": "../../outside/pwned"},
        {"document_study_id": "../../outside/pwned"},
        {"document_study_id_camel": "../../outside/pwned"},
        {"name": "../../outside/pwned"},
        {"extra_study_id": "cohort-a/../../outside/pwned"},
    ],
)
def test_membership_sync_rejects_study_id_that_leaves_the_work_tree(tmp_path: Path, kwargs: Dict[str, Any]) -> None:
    paths = _layout(tmp_path)
    store = FileConfigStore(paths["store_dir"])
    name = kwargs.get("name", "cohort-a")
    _publish(store, **kwargs)
    before = _snapshot(paths["base"])
    result = _run_sync(
        {"workRoot": str(paths["work"]), "cfgStudyName": name},
        store,
    )
    after = _snapshot(paths["base"])
    _assert_no_new_side_effects(before, after, [paths["store_dir"]], paths["base"])
    _assert_victims_intact(paths)
    assert not (result or {}).get("projectPath")


@pytest.mark.parametrize(
    "list_filename",
    [
        "../../../../outside/hit.csv",
        "../../other-study/data/samples.csv",
        "nested/../../../../outside/hit.csv",
    ],
)
def test_membership_sync_rejects_list_filename_that_leaves_the_study(tmp_path: Path, list_filename: str) -> None:
    paths = _layout(tmp_path)
    store = FileConfigStore(paths["store_dir"])
    _publish(store, extra_study_id="cohort-a", list_filename=list_filename)
    study_root = paths["work"] / "projects" / "cohort-a"
    before = _snapshot(paths["base"])
    result = _run_sync(
        {"workRoot": str(paths["work"]), "cfgStudyName": "cohort-a"},
        store,
    )
    after = _snapshot(paths["base"])
    _assert_no_new_side_effects(before, after, [paths["store_dir"], study_root], paths["base"])
    _assert_victims_intact(paths)
    _confined_project_strings(study_root)
    project_path = (result or {}).get("projectPath")
    if project_path:
        assert _under(Path(project_path), study_root)


def test_membership_sync_rejects_absolute_study_id_and_list_filename(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    store = FileConfigStore(paths["store_dir"])
    absolute_study = str(paths["outside"] / "abs-study")
    absolute_list = str(paths["outside"] / "abs-list.csv")
    _publish(store, name="abs-study-doc", extra_study_id=absolute_study, list_filename=absolute_list)
    before = _snapshot(paths["base"])
    result = _run_sync(
        {"workRoot": str(paths["work"]), "cfgStudyName": "abs-study-doc"},
        store,
    )
    after = _snapshot(paths["base"])
    _assert_no_new_side_effects(before, after, [paths["store_dir"]], paths["base"])
    _assert_victims_intact(paths)
    assert not (result or {}).get("projectPath")
    assert not Path(absolute_study).exists()
    assert not Path(absolute_list).exists()


def test_finalize_instance_context_writes_only_inside_the_study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _layout(tmp_path)
    store = FileConfigStore(paths["store_dir"])
    _publish(
        store,
        extra_study_id="../../outside/pwned",
        list_filename="../../../../outside/hit.csv",
    )
    monkeypatch.setenv("GOLIATH_CFG_STORE", str(paths["store_dir"]))
    before = _snapshot(paths["base"])
    try:
        finalize_instance_context(
            {
                "workRoot": str(paths["work"]),
                "cfgStudyName": "cohort-a",
                "projectPath": str(paths["work"] / "unused-project.json"),
            }
        )
    except Exception:
        pass
    after = _snapshot(paths["base"])
    _assert_no_new_side_effects(before, after, [paths["store_dir"]], paths["base"])
    _assert_victims_intact(paths)


def test_create_workflow_instance_syncs_through_finalize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """rest.db_client.create_workflow_instance calls finalize before it opens the database."""
    paths = _layout(tmp_path)
    store = FileConfigStore(paths["store_dir"])
    _publish(store, extra_study_id="../../outside/pwned", list_filename="../../other-study/data/samples.csv")
    monkeypatch.setenv("GOLIATH_CFG_STORE", str(paths["store_dir"]))

    def _db_is_not_the_write(_dsn: str) -> Any:
        raise RuntimeError("database open is after study sync")

    monkeypatch.setattr("rest.db_client.open_db_from_dsn", _db_is_not_the_write)
    before = _snapshot(paths["base"])
    try:
        create_workflow_instance(
            "postgresql://127.0.0.1:1/none",
            1,
            {"workRoot": str(paths["work"]), "cfgStudyName": "cohort-a"},
        )
    except Exception:
        pass
    after = _snapshot(paths["base"])
    _assert_no_new_side_effects(before, after, [paths["store_dir"]], paths["base"])
    _assert_victims_intact(paths)


def test_materialize_store_second_write_rejects_escaped_study_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """materialize_store writes project JSON itself after membership sync returns."""
    paths = _layout(tmp_path)
    store = FileConfigStore(paths["store_dir"])
    _publish(store, extra_study_id="../../outside/pwned", list_filename="controls.csv")

    def _membership_returns_without_writing(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {"written": []}

    monkeypatch.setattr(
        "cfg.study_membership.materialize_study_membership",
        _membership_returns_without_writing,
    )
    before = _snapshot(paths["base"])
    try:
        materialize_store(store, paths["work"], kinds=["study"])
    except Exception:
        pass
    after = _snapshot(paths["base"])
    _assert_no_new_side_effects(before, after, [paths["store_dir"]], paths["base"])
    _assert_victims_intact(paths)


def test_materialize_store_rejects_escaped_document_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """materialize_store joins ``project_<name>.json`` and creates missing parents.

    Membership sync's own ``write_text`` does not create those parents, so this
    test skips that write and exercises the second writer by itself.
    """
    paths = _layout(tmp_path)
    store = FileConfigStore(paths["store_dir"])
    # "project_" is glued onto the first segment, so the name needs enough ".."
    # to leave base/work/projects/<study>/configs after that glued segment.
    escaped_name = "x/../../../../../outside/pwn"
    _publish(store, name=escaped_name, extra_study_id="cohort-a", list_filename="controls.csv")

    def _membership_returns_without_writing(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {"written": []}

    monkeypatch.setattr(
        "cfg.study_membership.materialize_study_membership",
        _membership_returns_without_writing,
    )
    study_root = paths["work"] / "projects" / "cohort-a"
    before = _snapshot(paths["base"])
    try:
        materialize_store(store, paths["work"], kinds=["study"])
    except Exception:
        pass
    after = _snapshot(paths["base"])
    _assert_no_new_side_effects(before, after, [paths["store_dir"], study_root], paths["base"])
    _assert_victims_intact(paths)
    _confined_project_strings(study_root)


def test_symlink_study_data_dir_is_not_a_write_target(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    store = FileConfigStore(paths["store_dir"])
    study_root = paths["work"] / "projects" / "cohort-a"
    data_dir = study_root / "data"
    data_dir.parent.mkdir(parents=True)
    data_dir.symlink_to(paths["victim"].parent, target_is_directory=True)
    _publish(store, extra_study_id="cohort-a", list_filename="samples.csv")
    before = _snapshot(paths["base"])
    _run_sync({"workRoot": str(paths["work"]), "cfgStudyName": "cohort-a"}, store)
    after = _snapshot(paths["base"])
    _assert_no_new_side_effects(
        before,
        after,
        [paths["store_dir"], study_root],
        paths["base"],
    )
    _assert_victims_intact(paths)


def test_db_materialize_csv_path_is_not_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CSV paths use the concatenation in cfg.cfg_repo_materialize_study_lists.

    v_data_root := work_root || '/projects/' || coalesce(study_id, name) || '/data'
    csv_path := v_data_root || '/' || list_filename
    """
    paths = _layout(tmp_path)
    monkeypatch.setattr("cfg.sync_on_start.resolve_cfg_store_dir", lambda: None)

    class _Db:
        def cfg_materialize_study_lists(self, study_row_id: int, work_root: str) -> list[Any]:
            assert study_row_id == 17
            study_id = "../../outside/pwned"
            list_filenames = [
                "controls.csv",
                "../hit.csv",
                str(paths["outside"] / "from-db.csv"),
            ]
            rows: list[Any] = []
            for filename in list_filenames:
                csv_path = f"{work_root}/projects/{study_id}/data/{filename}"
                rows.append({"csv_path": csv_path, "sample_keys": ATTACK_MARKER})
            rows.append(
                (
                    1,
                    "control",
                    "ctrl",
                    "../../other-study/data/samples.csv",
                    f"{work_root}/projects/cohort-a/data/../../other-study/data/samples.csv",
                    ATTACK_MARKER,
                )
            )
            return rows

    before = _snapshot(paths["base"])
    try:
        ensure_study_work_synced(
            {"workRoot": str(paths["work"]), "cfgStudyRowId": 17},
            db=_Db(),
        )
    except Exception:
        pass
    after = _snapshot(paths["base"])
    _assert_no_new_side_effects(before, after, [paths["work"] / "projects" / "cohort-a"], paths["base"])
    _assert_victims_intact(paths)


def test_legitimate_study_membership_still_materializes(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    store = FileConfigStore(paths["store_dir"])
    _publish(store, extra_study_id="cohort-a", list_filename="controls.csv")
    result = ensure_study_work_synced(
        {"workRoot": str(paths["work"]), "cfgStudyName": "cohort-a"},
        store=store,
    )
    csv_path = paths["work"] / "projects" / "cohort-a" / "data" / "controls.csv"
    project_path = paths["work"] / "projects" / "cohort-a" / "configs" / "project_cohort-a.json"
    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == "sample"
    assert ATTACK_MARKER in csv_path.read_text(encoding="utf-8")
    document = json.loads(project_path.read_text(encoding="utf-8"))
    assert document["cfgStudyGroups"][0]["samplePath"] == str(csv_path)
    assert result["projectPath"] == str(project_path)
    _assert_victims_intact(paths)


def test_study_data_dir_rejects_a_non_segment(tmp_path: Path) -> None:
    work = tmp_path / "work"
    with pytest.raises(ValueError):
        study_data_dir(work, "../../outside/pwned")
    with pytest.raises(ValueError):
        study_data_dir(work, str(tmp_path / "absolute"))
