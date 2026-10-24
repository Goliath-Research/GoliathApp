"""Errors raised from portal stored procedures."""

from __future__ import annotations


class PortalSemanticError(Exception):
    """Semantic runner or session failure (SQLSTATE GS4xx / GS5xx)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
