"""Write cfg-derived files under the work root without leaving the intended directory.

Names that come from published cfg objects (study id, record name, list filename)
are untrusted: they must be one plain path segment. Directories below the trusted
root are opened one segment at a time with ``O_NOFOLLOW``, and files are written to
a temporary name in that directory and renamed into place, so neither a ``..``
segment nor a planted symlink or hard link moves the write somewhere else.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, Sequence

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def safe_segment(value: Any, *, what: str) -> str:
    """Return ``value`` as a single relative path segment, or raise ``ValueError``."""
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{what} must be a non-empty string, got {value!r}")
    text = str(value)
    if (
        not text
        or text in (".", "..")
        or "/" in text
        or "\\" in text
        or "\x00" in text
        or os.path.isabs(text)
    ):
        raise ValueError(f"{what} must be a single path segment, got {text!r}")
    return text


def open_dir(root: Path | str, parts: Sequence[str] = ()) -> int:
    """Open ``root`` (created if missing), then each of ``parts`` without following symlinks.

    ``root`` is operator configuration and is opened as given. Every segment in
    ``parts`` is validated, created if missing, and must be a real directory.
    Returns a directory file descriptor the caller must close.
    """
    for part in parts:
        safe_segment(part, what="path segment")
    Path(root).mkdir(parents=True, exist_ok=True)
    fd = os.open(str(root), _DIR_FLAGS)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o777, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, _DIR_FLAGS | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def write_file_at(dir_fd: int, name: str, data: bytes) -> None:
    """Atomically replace the entry ``name`` in the open directory ``dir_fd``."""
    safe_segment(name, what="file name")
    tmp = f".{name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(tmp, _FILE_FLAGS, 0o666, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.rename(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=dir_fd)
        except FileNotFoundError:
            pass
        raise


def write_under(root: Path | str, parts: Sequence[str], name: str, data: bytes) -> Path:
    """Write ``root/<parts...>/name`` and return that path."""
    safe_segment(name, what="file name")
    fd = open_dir(root, parts)
    try:
        write_file_at(fd, name, data)
    finally:
        os.close(fd)
    return Path(root).joinpath(*parts, name)


def ensure_dir_under(root: Path | str, parts: Sequence[str]) -> Path:
    """Create ``root/<parts...>`` without following symlinks below ``root``."""
    os.close(open_dir(root, parts))
    return Path(root).joinpath(*parts)
