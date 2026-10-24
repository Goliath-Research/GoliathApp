"""Third-party Exograph lock and fetch verification."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK = REPO_ROOT / "third_party" / "exograph.lock"
FETCH = REPO_ROOT / "scripts" / "fetch_third_party.py"


def test_exograph_lock_matches_upstream_sha256_file() -> None:
    with LOCK.open("rb") as fh:
        lock = tomllib.load(fh)
    expected = lock["asset"]["sha256"].lower()
    assert lock["platform"] == "linux-x86_64"
    sha_url = f"{lock['asset']['url']}.sha256"
    with urllib.request.urlopen(sha_url, timeout=60) as resp:
        published = resp.read().decode().strip().split()[0].lower()
    assert published == expected


def test_fetch_third_party_checksum_mismatch_fails(tmp_path: Path) -> None:
    bad_lock = tmp_path / "exograph.lock"
    text = LOCK.read_text()
    bad_lock.write_text(text.replace("537c9ed4955871ecd5b408f975c7425197898b60d7d32d90cd65bcde3d431cf6", "0" * 64))

    proc = subprocess.run(
        [sys.executable, str(FETCH), "--lock", str(bad_lock), "--dest", str(tmp_path / "out")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "checksum mismatch" in (proc.stderr + proc.stdout).lower()


@pytest.mark.skipif(not (REPO_ROOT / "third_party" / "vendor" / "exograph").is_dir(), reason="vendor not fetched")
def test_exograph_vendor_binaries_executable() -> None:
    root = REPO_ROOT / "third_party" / "vendor" / "exograph" / "0.29.1" / "linux-x86_64"
    exo = root / "exo"
    assert exo.is_file()
    assert exo.stat().st_mode & 0o111
