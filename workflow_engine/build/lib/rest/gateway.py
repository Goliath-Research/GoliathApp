#!/usr/bin/env python3
"""
OpenAPI workflow REST gateway backed by wf contract stored procedures.

Worker-only identity: ``/v1/workers/*`` for task claim/submit. Catalog seed,
workflow deploy, and study lifecycle use direct DB (``workflow_engine/ops``),
portal SQL, or Cursor MCP — not this HTTP surface.

The gateway is domain-agnostic: no pipeline knowledge, no catalog files on disk,
and no config resolution at task claim. Enrolled adapters ingest typed events via
``POST /v1/events`` using the **same worker session headers** as claim
(``wf.sp_worker_ingest_event``).
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any, Optional

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "rest"

from .connection import resolve_connection_config
from .db import open_gateway_db
from goliath_worker.wake import (
    wake_channel_for_capability,
    wake_channel_for_pool,
    wake_channel_for_program,
)

from .db.base import EventIngestForbidden, GatewayDb, WorkerAuthError, WorkerCallAuth
from .db_client import (
    ingest_event_with_api_key,
    ingest_event_worker,
    worker_enroll,
    worker_fail_task,
    worker_heartbeat,
    worker_open_session,
    worker_request_task,
    worker_submit_result,
)
from .postgres_wake import resolve_wake_publisher
from .worker_wake import NullWorkerWakePublisher, WorkerWakePublisher, bind_worker_wake_publisher, publish_wakes_after_event_ingest
from .worker_wake_hub import WorkerWakeHub, WorkerWakeWaitConflict


class RestGateway:
    def __init__(
        self,
        db: GatewayDb,
        *,
        wake_publisher: Optional[WorkerWakePublisher] = None,
        wake_hub: Optional[WorkerWakeHub] = None,
    ) -> None:
        self.db = db
        self._wake_publisher: WorkerWakePublisher = wake_publisher or NullWorkerWakePublisher()
        self._wake_hub: WorkerWakeHub = wake_hub if wake_hub is not None else WorkerWakeHub()
        bind_worker_wake_publisher(self._wake_publisher)

    @property
    def backend(self) -> str:
        return self.db.backend

    def dispatch(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
        query: Optional[dict[str, list[str]]] = None,
        *,
        client_ip: Optional[str] = None,
        worker_auth: Optional[WorkerCallAuth] = None,
        identity_token: Optional[str] = None,
        event_ingest_api_key_hex: Optional[str] = None,
    ) -> tuple[int, Any]:
        _ = query  # worker routes do not use query params today

        if method == "GET" and path in ("/", "/v1", "/v1/health"):
            return 200, {
                "status": "ok",
                "service": "goliath-workflow-gateway",
                "backend": self.backend,
                "api_base": "/v1",
                "identities": ["worker"],
            }

        if method == "POST" and path == "/v1/workers/enroll":
            # Client IP must come from extract_client_ip (ASGI/proxy), never from the body.
            ip = (client_ip or "").strip()
            if not ip:
                return 400, {"error": "client IP unavailable; enroll requires proxy-derived client address"}
            token = secrets.token_hex(32)
            caps = body.get("capabilities")
            if caps is not None and not isinstance(caps, list):
                return 400, {"error": "capabilities must be a JSON array"}
            worker_id = worker_enroll(
                self.db,
                cluster_key=str(body["cluster_key"]),
                external_worker_key=str(body["external_worker_key"]),
                client_ip=ip,
                worker_token=token,
                capabilities=caps,
                arc_resource_id=(
                    str(body["arc_resource_id"]) if body.get("arc_resource_id") else None
                ),
            )
            return 200, {
                "worker_id": worker_id,
                "worker_token": token,
                "external_worker_key": str(body["external_worker_key"]),
                "cluster_key": str(body["cluster_key"]),
            }

        if method == "POST" and path == "/v1/workers/session":
            ip = (client_ip or "").strip()
            if not ip:
                return 400, {"error": "client IP unavailable; session open requires proxy-derived address"}
            token = (identity_token or "").strip()
            if not token:
                return 400, {"error": "X-Goliath-Worker-Token header is required"}
            payload = worker_open_session(self.db, token, ip)
            return 200, payload

        if method == "POST" and path == "/v1/workers/wakes/wait":
            return self._worker_wait_for_wake(body, client_ip=client_ip or "", worker_auth=worker_auth)

        if method == "POST" and path == "/v1/workers/tasks/request":
            if worker_auth is None:
                return 401, {"error": "worker session auth required"}
            result = worker_request_task(
                self.db,
                worker_auth,
                body.get("capability"),
                int(body.get("max_lease_seconds", 300)),
            )
            return 200, result

        m = re.fullmatch(r"/v1/workers/tasks/(\d+)/submit", path)
        if method == "POST" and m:
            if worker_auth is None:
                return 401, {"error": "worker session auth required"}
            payload = worker_submit_result(
                self.db,
                int(m.group(1)),
                worker_auth,
                int(body["result_code"]),
                body.get("output_json"),
            )
            try:
                from rest.execution_scope import sync_execution_scope_action_entry_after_submit

                sync_execution_scope_action_entry_after_submit(
                    self.db,
                    int(m.group(1)),
                    int(body["result_code"]),
                )
            except Exception:
                pass
            return 200, payload

        m = re.fullmatch(r"/v1/workers/tasks/(\d+)/heartbeat", path)
        if method == "POST" and m:
            if worker_auth is None:
                return 401, {"error": "worker session auth required"}
            payload = worker_heartbeat(
                self.db,
                int(m.group(1)),
                worker_auth,
                int(body.get("extend_seconds", 300)),
            )
            return 200, payload

        m = re.fullmatch(r"/v1/workers/tasks/(\d+)/fail", path)
        if method == "POST" and m:
            if worker_auth is None:
                return 401, {"error": "worker session auth required"}
            worker_fail_task(
                self.db,
                int(m.group(1)),
                worker_auth,
                int(body["error_code"]),
                body.get("error_message"),
            )
            return 204, None

        if method == "POST" and path == "/v1/events":
            event_type = str(body.get("event_type") or "").strip()
            source = str(body.get("source") or "").strip()
            idempotency_key = str(body.get("idempotency_key") or "").strip()
            if not event_type:
                raise KeyError("event_type")
            if not source:
                raise KeyError("source")
            if not idempotency_key:
                raise KeyError("idempotency_key")
            payload = body.get("payload")
            if payload is None:
                payload = body.get("payload_json") or {}
            if payload is not None and not isinstance(payload, dict):
                return 400, {"error": "payload must be a JSON object"}
            payload_dict = dict(payload) if isinstance(payload, dict) else {}
            try:
                if event_ingest_api_key_hex:
                    key_hex = event_ingest_api_key_hex.strip().lower()
                    api_payload = dict(payload_dict)
                    top_org = body.get("organization_key")
                    if top_org is not None and str(top_org).strip():
                        api_payload["organization_key"] = str(top_org).strip()
                    result = ingest_event_with_api_key(
                        self.db,
                        key_hex,
                        event_type=event_type,
                        source=source,
                        idempotency_key=idempotency_key,
                        payload_json=api_payload,
                        correlation_key=(
                            str(body["correlation_key"])
                            if body.get("correlation_key") is not None
                            else None
                        ),
                        occurred_at_utc=(
                            str(body["occurred_at_utc"])
                            if body.get("occurred_at_utc")
                            else None
                        ),
                    )
                else:
                    if worker_auth is None:
                        return 401, {"error": "worker session auth required for event ingest"}
                    result = ingest_event_worker(
                        self.db,
                        worker_auth,
                        event_type=event_type,
                        source=source,
                        idempotency_key=idempotency_key,
                        payload_json=payload_dict,
                        correlation_key=(
                            str(body["correlation_key"])
                            if body.get("correlation_key") is not None
                            else None
                        ),
                        occurred_at_utc=(
                            str(body["occurred_at_utc"])
                            if body.get("occurred_at_utc")
                            else None
                        ),
                    )
            except EventIngestForbidden as exc:
                return 403, {"error": exc.message}
            # Dual activation (tier 1): notify idle workers; claim still owns the lease.
            publish_wakes_after_event_ingest(
                self._wake_publisher,
                self.db,
                ingest_result=result,
                event_type=event_type,
                idempotency_key=idempotency_key,
                payload=payload_dict,
            )
            return 200, result

        return 404, {"error": "not found", "path": path}

    def _worker_wait_for_wake(
        self,
        body: dict[str, Any],
        *,
        client_ip: str,
        worker_auth: Optional[WorkerCallAuth],
    ) -> tuple[int, Any]:
        """Long-poll until a matching wake or timeout (HTTP subscribe path for workers)."""
        if worker_auth is None:
            return 401, {"error": "worker session auth required"}

        raw_timeout = body.get("timeout_seconds")
        if raw_timeout is None:
            timeout = 30.0
        else:
            try:
                timeout = float(raw_timeout)
            except (TypeError, ValueError):
                return 400, {"error": "timeout_seconds must be a number"}
        timeout = max(0.0, min(timeout, 120.0))

        program_id = body.get("program_id")
        if program_id is not None and program_id != "":
            if not isinstance(program_id, str):
                return 400, {"error": "program_id must be a string when set"}

        try:
            resolved = self.db.worker_resolve_session_for_wake(
                worker_auth.session_token,
                worker_auth.identity_token,
                client_ip,
            )
        except WorkerAuthError as exc:
            return 401, {"error": str(exc)}

        wid = int(resolved["worker_id"])
        if wid != worker_auth.worker_id:
            return 403, {"error": "worker_id does not match session"}

        cluster_key = str(resolved["cluster_key"])
        caps_raw = resolved.get("capabilities") or []
        caps: list[str] = []
        if isinstance(caps_raw, list):
            for c in caps_raw:
                if c is not None:
                    caps.append(str(c))

        channels: set[str] = {wake_channel_for_pool(cluster_key)}
        for cap in caps:
            name = cap.strip()
            if name and name != "*":
                channels.add(wake_channel_for_capability(name))

        if program_id not in (None, ""):
            prog = str(program_id).strip()
            if prog:
                channels.add(wake_channel_for_program(prog))

        try:
            msg = self._wake_hub.wait_for_wake(
                wid,
                frozenset(channels),
                timeout_seconds=timeout,
            )
        except WorkerWakeWaitConflict:
            return 409, {"error": "concurrent wake wait for this worker"}

        if msg is None:
            return 200, {"wake": None, "timed_out": True}
        return 200, {"wake": msg.to_json(), "timed_out": False}


def main(argv: Optional[list[str]] = None) -> int:
    import uvicorn

    from .asgi import create_app

    parser = argparse.ArgumentParser(description="GoliathApp workflow REST gateway")
    parser.add_argument(
        "--host",
        default=os.environ.get("WF_GATEWAY_HOST", os.environ.get("REST_HOST", "127.0.0.1")),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("WF_GATEWAY_PORT", os.environ.get("REST_PORT", "8080"))),
    )
    args = parser.parse_args(argv)

    config = resolve_connection_config()
    db = open_gateway_db(config)
    wake_hub = WorkerWakeHub()
    wake_publisher = resolve_wake_publisher(config, wake_hub=wake_hub)
    gateway = RestGateway(db, wake_publisher=wake_publisher, wake_hub=wake_hub)
    app = create_app(gateway)
    print(
        f"REST gateway on http://{args.host}:{args.port}/v1 (backend={gateway.backend})",
        flush=True,
    )
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    except KeyboardInterrupt:
        print("Stopped.", flush=True)
    finally:
        db.close()
        if hasattr(wake_publisher, "close"):
            wake_publisher.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
