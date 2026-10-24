#!/usr/bin/env python3
"""Fetch and verify third-party release artifacts described by third_party/*.lock files."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
THIRD_PARTY = REPO_ROOT / "third_party"


def _load_lock(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_exograph(lock_path: Path, dest: Path, *, allow_platform_skip: bool) -> None:
    lock = _load_lock(lock_path)
    if lock.get("artifact") != "exograph":
        raise ValueError(f"unsupported lock artifact in {lock_path}")

    platform = lock.get("platform", "")
    if platform != "linux-x86_64":
        if allow_platform_skip:
            print(f"[skip] {lock_path.name}: platform {platform!r} (this host is linux-x86_64 only)")
            return
        raise ValueError(f"{lock_path.name}: only linux-x86_64 is supported, got {platform!r}")

    asset = lock["asset"]
    expected = asset["sha256"].lower()
    url = asset["url"]
    version = lock["version"]
    install_root = dest / "exograph" / version / platform

    if install_root.is_dir():
        binaries = lock.get("install", {}).get("binaries", ["exo"])
        if all((install_root / name).is_file() for name in binaries):
            print(f"[ok] exograph {version} already present at {install_root}")
            return

    install_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="goliath-exograph-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / asset["name"]
        print(f"[fetch] {url}")
        urllib.request.urlretrieve(url, archive)
        actual = _sha256_file(archive)
        if actual != expected:
            raise SystemExit(
                f"checksum mismatch for {asset['name']}: expected {expected}, got {actual}"
            )

        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_dir)

        if install_root.exists():
            shutil.rmtree(install_root)
        shutil.copytree(extract_dir, install_root)
        for name in lock.get("install", {}).get("binaries", []):
            path = install_root / name
            if path.is_file():
                path.chmod(path.stat().st_mode | 0o111)

    print(f"[ok] installed exograph {version} -> {install_root}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=THIRD_PARTY / "vendor",
        help="Output root for extracted artifacts (default: third_party/vendor)",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        action="append",
        dest="locks",
        help="Specific lock file (default: all third_party/*.lock)",
    )
    parser.add_argument(
        "--allow-platform-skip",
        action="store_true",
        help="Skip locks for unsupported platforms instead of failing",
    )
    args = parser.parse_args(argv)

    locks = args.locks or sorted(THIRD_PARTY.glob("*.lock"))
    if not locks:
        print("no third_party/*.lock files found", file=sys.stderr)
        return 1

    args.dest.mkdir(parents=True, exist_ok=True)
    for lock_path in locks:
        if lock_path.name == "exograph.lock":
            fetch_exograph(lock_path, args.dest, allow_platform_skip=args.allow_platform_skip)
        else:
            raise SystemExit(f"unknown lock file: {lock_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
