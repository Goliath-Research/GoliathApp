"""Optional science extensions via ``goliath.application_profiles`` entry points."""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

_GROUP = "goliath.application_profiles"


class _MissingApplicationProfiles:
    """Platform-only wheel: neutral pipeline scope without product presets."""

    PROFILE_PRESETS: dict[str, Any] = {}

    def load_profile(self, name_or_path: str | Path) -> dict[str, Any]:
        from .pipeline_profiles import load_profile_file

        path = Path(name_or_path)
        if path.is_file():
            return load_profile_file(path)
        raise FileNotFoundError(
            f"Unknown pipeline profile {name_or_path!r} "
            "(install a goliath.application_profiles entry point)"
        )

    def load_procedure(self, name_or_path: str | Path) -> dict[str, Any]:
        path = Path(name_or_path)
        if path.is_file():
            from .pipeline_profiles import load_profile_file

            return load_profile_file(path)
        raise FileNotFoundError(
            f"Unknown pipeline procedure {name_or_path!r} "
            "(install a goliath.application_profiles entry point)"
        )

    def profile_action_config(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        ac = profile.get("actionConfig") or profile.get("step_config_overrides") or {}
        return dict(ac) if isinstance(ac, dict) else {}

    def load_samd_research_with_mode(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise FileNotFoundError(
            "samd_research profiles require a goliath.application_profiles entry point"
        )


def get_application_profiles_module() -> ModuleType | _MissingApplicationProfiles:
    eps = entry_points().select(group=_GROUP)
    for ep in sorted(eps, key=lambda e: e.name):
        loaded = ep.load()
        if isinstance(loaded, str):
            return importlib.import_module(loaded)
        return loaded
    return _MissingApplicationProfiles()
