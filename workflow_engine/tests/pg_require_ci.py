"""Shared PostgreSQL test helpers — fail in CI instead of skipping silently."""

from __future__ import annotations

import os
from collections.abc import Callable

import pytest


def require_psql() -> None:
    from shutil import which

    if which("psql"):
        return
    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.fail("psql is required in CI")
    pytest.skip("psql not installed")


def require_postgres_reachable(probe: Callable[[], None]) -> None:
    try:
        probe()
    except RuntimeError as exc:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail(f"PostgreSQL required in CI but not reachable: {exc}")
        pytest.skip("PostgreSQL not reachable")
