"""PostgreSQL portal client: session helpers and semantic runner (procs only)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional, Sequence

import psycopg
from psycopg.rows import tuple_row
from pydantic import BaseModel

from goliath_app.portal.connection import PortalConnectionConfig, resolve_portal_connection_config
from goliath_app.portal.errors import PortalSemanticError
from goliath_app.portal.models import SemanticCatalogEntry, SessionOpenResult
from goliath_app.portal.registry import result_model_for
from goliath_app.semantic.filters import FilterTemplate
from goliath_app.semantic.models import FilterOrganizationsParams, ListOrganizationsParams, OrganizationRow


def _semantic_error_from(exc: BaseException) -> PortalSemanticError:
    sqlstate = getattr(exc, "sqlstate", None) or ""
    diag = getattr(exc, "diag", None)
    message = getattr(diag, "message_primary", None) if diag is not None else None
    if not message:
        message = str(exc)
    code = sqlstate if sqlstate.startswith("GS") else "GS500"
    return PortalSemanticError(code, message)


def _jsonb_cell(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise TypeError(f"expected json object row, got {type(value)!r}")


class PortalClient:
    """Call ``portal.sp_*`` as the ``goliath_portal`` database role (no table access)."""

    def __init__(
        self,
        conninfo: Optional[str] = None,
        *,
        config: Optional[PortalConnectionConfig] = None,
    ) -> None:
        if config is not None:
            self._config = config
        else:
            self._config = resolve_portal_connection_config(conninfo=conninfo)

    @property
    def conninfo(self) -> str:
        return self._config.conninfo

    @contextmanager
    def _connect(self) -> Generator[psycopg.Connection[tuple[object, ...]], None, None]:
        with psycopg.connect(self._config.conninfo, row_factory=tuple_row) as conn:
            yield conn

    def session_open(
        self,
        user_id: int,
        *,
        active_scope_id: Optional[int] = None,
        auth_provider_id: Optional[int] = None,
        auth_subject_snapshot: Optional[str] = None,
    ) -> SessionOpenResult:
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    """
                    SELECT session_token, session_id, expires_at_utc
                    FROM portal.sp_session_open(%s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        active_scope_id,
                        auth_provider_id,
                        auth_subject_snapshot,
                    ),
                )
            except psycopg.Error as exc:
                raise _semantic_error_from(exc) from exc
            row = cur.fetchone()
            if row is None:
                raise PortalSemanticError("GS500", "sp_session_open returned no row")
            token, session_id, expires = row
            return SessionOpenResult(
                session_token=str(token),
                session_id=int(str(session_id)),
                expires_at_utc=expires if isinstance(expires, datetime) else datetime.fromisoformat(str(expires)),
            )

    def session_revoke(self, session_token: str) -> bool:
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    "SELECT revoked FROM portal.sp_session_revoke(%s)",
                    (session_token,),
                )
            except psycopg.Error as exc:
                raise _semantic_error_from(exc) from exc
            row = cur.fetchone()
            return bool(row[0]) if row else False

    def session_touch(self, session_token: str) -> bool:
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    "SELECT portal.sp_session_touch(%s)",
                    (session_token,),
                )
            except psycopg.Error as exc:
                raise _semantic_error_from(exc) from exc
            row = cur.fetchone()
            return bool(row[0]) if row else False

    def list_semantic_catalog(self, session_token: str) -> list[SemanticCatalogEntry]:
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    """
                    SELECT request_code, version, namespace, entity_code, display_name,
                           params_schema, result_schema, required_permission
                    FROM portal.sp_list_semantic_catalog(%s)
                    """,
                    (session_token,),
                )
            except psycopg.Error as exc:
                raise _semantic_error_from(exc) from exc
            entries: list[SemanticCatalogEntry] = []
            for row in cur.fetchall():
                params_schema = row[5]
                result_schema = row[6]
                entries.append(
                    SemanticCatalogEntry(
                        request_code=str(row[0]),
                        version=str(row[1]),
                        namespace=str(row[2]),
                        entity_code=str(row[3]),
                        display_name=str(row[4]),
                        params_schema=_jsonb_cell(params_schema) if params_schema is not None else {},
                        result_schema=_jsonb_cell(result_schema) if result_schema is not None else {},
                        required_permission=str(row[7]) if row[7] is not None else None,
                    )
                )
            return entries

    def run_semantic_request(
        self,
        session_token: str,
        request_code: str,
        params: Optional[BaseModel] = None,
        *,
        version: str = "1",
        filter_override: Optional[FilterTemplate] = None,
    ) -> Sequence[BaseModel]:
        row_model = result_model_for(request_code)
        params_json = (
            json.dumps(params.model_dump(mode="json", exclude_none=True))
            if params is not None
            else "{}"
        )
        filter_json: Optional[str] = None
        if filter_override is not None:
            filter_json = json.dumps(filter_override.model_dump(mode="json"))

        with self._connect() as conn:
            try:
                cur = conn.execute(
                    """
                    SELECT * FROM portal.sp_run_semantic_request(
                      %s, %s, %s, %s::jsonb, %s::jsonb
                    )
                    """,
                    (
                        session_token,
                        request_code,
                        version,
                        params_json,
                        filter_json,
                    ),
                )
            except psycopg.Error as exc:
                raise _semantic_error_from(exc) from exc
            rows: list[BaseModel] = []
            for row in cur.fetchall():
                payload = _jsonb_cell(row[0])
                rows.append(row_model.model_validate(payload))
            return rows

    def list_organizations(
        self,
        session_token: str,
        params: Optional[ListOrganizationsParams] = None,
    ) -> list[OrganizationRow]:
        result = self.run_semantic_request(
            session_token,
            "core.list_organizations",
            params or ListOrganizationsParams(),
        )
        return [OrganizationRow.model_validate(r.model_dump()) for r in result]

    def filter_organizations(
        self,
        session_token: str,
        params: FilterOrganizationsParams,
        *,
        filter_override: Optional[FilterTemplate] = None,
    ) -> list[OrganizationRow]:
        result = self.run_semantic_request(
            session_token,
            "core.filter_organizations",
            params,
            filter_override=filter_override,
        )
        return [OrganizationRow.model_validate(r.model_dump()) for r in result]
