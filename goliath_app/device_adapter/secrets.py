"""Secret references: resolve from environment or file paths; never log material."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator


class SecretRef(BaseModel):
    """Opaque reference (path or env name) resolved at runtime on the adapter host."""

    model_config = ConfigDict(extra="forbid")

    env_name: str | None = None
    file_path: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> SecretRef:
        if not (self.env_name or "").strip() and not (self.file_path or "").strip():
            raise ValueError("SecretRef requires env_name or file_path")
        return self

    def resolve(self) -> str:
        if self.env_name and self.env_name.strip():
            raw = os.environ.get(self.env_name.strip(), "")
            if not raw.strip():
                raise RuntimeError(f"secret env {self.env_name!r} is unset")
            return raw.strip()
        assert self.file_path is not None
        path = Path(self.file_path).expanduser()
        if not path.is_file():
            raise RuntimeError(f"secret file missing: {path}")
        return path.read_text(encoding="utf-8").strip()


def read_secret_ref(ref: SecretRef | None) -> str | None:
    if ref is None:
        return None
    return ref.resolve()
