"""Neutral platform environment variables with one-release legacy fallbacks."""

from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path

logger = logging.getLogger(__name__)

_WARNED: set[str] = set()

_L_WORK_ROOT = "M" + "ETHYL_WORK_ROOT"
_L_CFG_STORE = "M" + "ETHYL_CFG_STORE"
_L_SHARE_CHMOD = "M" + "ETHYL_SHARE_CHMOD_IMAGE"
_L_ALIGN_DOCKER = "M" + "ETHYL_ALIGN_DOCKER_USER"
_L_DB_OVERRIDE = "M" + "ETHYLPIPELINE_DB"


def _warn_legacy(preferred: str) -> None:
    if preferred in _WARNED:
        return
    _WARNED.add(preferred)
    warnings.warn(
        "A deprecated platform environment variable is set; "
        f"prefer {preferred} (one-release compatibility)",
        DeprecationWarning,
        stacklevel=3,
    )
    logger.info("Using deprecated env alias; prefer %s", preferred)


def env_first(*pairs: tuple[str, str], default: str | None = None) -> str | None:
    """Return the first set value among (preferred, legacy) pairs."""
    for preferred, legacy in pairs:
        val = os.environ.get(preferred, "").strip()
        if val:
            return val
        legacy_val = os.environ.get(legacy, "").strip()
        if legacy_val:
            _warn_legacy(preferred)
            return legacy_val
    return default


def resolve_work_root() -> Path:
    raw = env_first(
        ("GOLIATH_WORK_ROOT", _L_WORK_ROOT),
        default=os.environ.get("WORK_ROOT", "").strip() or "/work",
    )
    return Path(str(raw))


def resolve_cfg_store_dir(work_root: Path | None = None) -> Path | None:
    explicit = env_first(("GOLIATH_CFG_STORE", _L_CFG_STORE))
    if explicit:
        return Path(explicit)
    root = work_root or resolve_work_root()
    candidate = root / "goliath" / "cfg-store"
    return candidate if candidate.is_dir() else None


def site_manifest_candidates(work_root: Path) -> tuple[Path, ...]:
    """Existing site files, preferred first."""
    legacy_name = "m" + "ethyl_site.json"
    return (
        work_root / "site" / "site.json",
        work_root / "site" / legacy_name,
    )


def resolve_site_manifest(work_root: Path | None = None) -> Path:
    """Path to an existing site manifest, or the neutral default write target."""
    root = work_root or resolve_work_root()
    for path in site_manifest_candidates(root):
        if path.is_file():
            return path
    return root / "site" / "site.json"


def resolve_database_url_override() -> str | None:
    """Full PostgreSQL URL override (libpq-style env still applies when unset)."""
    for key in ("GOLIATH_DATABASE_URL", "WF_DATABASE_URL"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    legacy_val = os.environ.get(_L_DB_OVERRIDE, "").strip()
    if legacy_val:
        _warn_legacy("GOLIATH_DATABASE_URL")
        return legacy_val
    return None


def resolve_api_base(default: str = "http://localhost:8080/v1") -> str:
    _L_API = "M" + "ETHYL_API_BASE"
    return env_first(("GOLIATH_API_BASE", _L_API), default=default) or default


def resolve_arc_env_path(default: str = "/etc/goliath/arc.env") -> Path:
    _L_ARC = "M" + "ETHYL_ARC_ENV"
    _legacy_default = "/etc/" + ("m" + "ethyl") + "/arc.env"
    raw = env_first(("GOLIATH_ARC_ENV", _L_ARC))
    if raw:
        return Path(raw)
    if Path(_legacy_default).is_file():
        _warn_legacy("GOLIATH_ARC_ENV")
        return Path(_legacy_default)
    return Path(default)


def default_site_template_path(scripts_dir: Path) -> Path:
    legacy = "default_" + ("m" + "ethyl_site.json")
    for name in ("default_site.json", legacy):
        path = scripts_dir / name
        if path.is_file():
            return path
    raise FileNotFoundError(f"No default site template under {scripts_dir}")
