"""cfg import-fs on release runtime-bundle layout + credential upsert naming."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cfg.cli import _cmd_upsert  # noqa: E402
from cfg.import_fs import import_filesystem  # noqa: E402
from cfg.store import FileConfigStore  # noqa: E402


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_import_fs_reads_runtime_bundle_domain(tmp_path: Path) -> None:
    bundle = tmp_path / "runtime-bundle"
    _write(
        bundle / "domain" / "fixtures" / "reference_assets" / "linear.json",
        {"name": "linear-x", "version": "1", "inventoryPrefix": "linear/x", "recipe": {"steps": []}},
    )
    store = FileConfigStore(tmp_path / "store")
    result = import_filesystem(
        store,
        repo_root=bundle,
        include_programs=False,
        include_profiles=False,
        include_site=False,
        include_studies=False,
    )
    assert any("linear-x" in item for item in result["imported"])
    assert store.get("reference_asset", "linear-x") is not None


def test_upsert_credential_keeps_document_name(tmp_path: Path) -> None:
    cred = tmp_path / "keys.json"
    _write(cred, {"name": "archive-keys", "version": "1", "provider": "s3", "accessKeyId": "a", "secretAccessKey": "b"})
    store_dir = tmp_path / "store"
    args = argparse.Namespace(
        store_dir=str(store_dir), file=str(cred), kind="credential", provider="s3",
        name=None, version="1", draft=False, publish=False, credential_name=None, study_id=None,
    )
    _cmd_upsert(args)
    store = FileConfigStore(store_dir)
    assert store.get("credential", "archive-keys", include_secret=True) is not None
    assert store.get("credential", "keys") is None
