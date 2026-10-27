"""HTTP client for the workflow middle-tier REST API (contracts/openapi.yaml)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from goliath_worker.wake import (
    WorkerWakeSubscriber,
    wake_channel_for_capability,
    wake_channel_for_pool,
    wake_channel_for_program,
)

WORKER_IDENTITY_HEADER = "X-Goliath-Worker-Token"


@dataclass(frozen=True)
class TaskClaim:
    """One claimed READY task from POST /workers/tasks/request."""

    node_execution_id: int
    workflow_instance_id: int
    action_name: str
    capability: str
    input_json: Dict[str, Any]
    node_key: str = ""
    attempt_no: int = 1
    iteration_no: int = 0


@dataclass(frozen=True)
class WorkerControlAck:
    """Fleet control echoed from claim/heartbeat (wf.worker.desired_state)."""

    desired_state: str = "ACTIVE"
    command: str = "NONE"  # NONE | DRAIN | STOP


@dataclass(frozen=True)
class TaskPollResult:
    """Idle or claimed poll from POST /workers/tasks/request."""

    claim: Optional[TaskClaim]
    control: WorkerControlAck = WorkerControlAck()


@dataclass(frozen=True)
class HeartbeatAck:
    rows_updated: int
    control: WorkerControlAck = WorkerControlAck()


@dataclass(frozen=True)
class SubmitAck:
    accepted: bool
    instance_status: str
    next_ready_count: int


def _load_arc_resource_id() -> Optional[str]:
    explicit = os.environ.get("ARC_RESOURCE_ID", "").strip()
    if explicit:
        return explicit
    arc_env = Path(os.environ.get("METHYL_ARC_ENV", "/etc/methyl/arc.env"))
    if not arc_env.is_file():
        return None
    for line in arc_env.read_text(encoding="utf-8").splitlines():
        if line.startswith("ARC_RESOURCE_ID="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            return val or None
    return None


def _control_from_body(body: Dict[str, Any]) -> WorkerControlAck:
    return WorkerControlAck(
        desired_state=str(body.get("desired_state") or "ACTIVE"),
        command=str(body.get("command") or "NONE"),
    )


class WorkflowRestClient:
    """REST-only workflow worker client; no direct database access."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout_seconds: float = 120.0,
        arc_resource_id: Optional[str] = None,
    ) -> None:
        raw = base_url or os.environ.get("METHYL_API_BASE", "http://localhost:8080/v1")
        self.base_url = raw.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.arc_resource_id = arc_resource_id if arc_resource_id is not None else _load_arc_resource_id()
        self._worker_id: Optional[int] = None
        self._identity_token: Optional[str] = None
        self._session_token: Optional[str] = None

    def _default_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.arc_resource_id:
            headers["X-Arc-Resource-Id"] = self.arc_resource_id
        if self._session_token:
            headers["Authorization"] = f"Bearer {self._session_token}"
        if self._identity_token:
            headers[WORKER_IDENTITY_HEADER] = self._identity_token
        return headers

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = self._default_headers()
        if extra_headers:
            headers.update(extra_headers)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
                if not body:
                    return {}
                return json.loads(body)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 403:
                raise RuntimeError(
                    f"HTTP 403 {path}: enroll refused (portal IP/key not preregistered). "
                    f"Fail closed — no SQL fallback. {detail}"
                ) from exc
            raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Request failed {path}: {exc}") from exc

    def _post_json(self, path: str, payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return self._request_json(path, method="POST", payload=payload, **kwargs)

    def _get_json(self, path: str) -> Dict[str, Any]:
        return self._request_json(path, method="GET")

    def open_session(self, identity_token: str) -> Dict[str, Any]:
        """POST /workers/session — obtain a bearer session from the enrollment identity token."""
        headers = {WORKER_IDENTITY_HEADER: identity_token}
        body = self._post_json("/workers/session", {}, extra_headers=headers)
        self._identity_token = identity_token
        self._session_token = str(body.get("session_token") or "")
        if body.get("worker_id") is not None:
            self._worker_id = int(body["worker_id"])
        return body

    def enroll(
        self,
        cluster_key: str,
        external_worker_key: str,
        *,
        capabilities: Optional[list[Any]] = None,
        arc_resource_id: Optional[str] = None,
        open_session: bool = True,
    ) -> Dict[str, Any]:
        """POST /workers/enroll — mint worker_id + identity token from portal IP allowlist."""
        payload: Dict[str, Any] = {
            "cluster_key": cluster_key,
            "external_worker_key": external_worker_key,
        }
        if capabilities is not None:
            payload["capabilities"] = capabilities
        rid = arc_resource_id if arc_resource_id is not None else self.arc_resource_id
        if rid:
            payload["arc_resource_id"] = rid
        body = self._post_json("/workers/enroll", payload)
        self._worker_id = int(body["worker_id"])
        identity = str(body.get("worker_token") or "")
        self._identity_token = identity
        if open_session and identity:
            self.open_session(identity)
        return body

    def _require_worker_id(self) -> int:
        if self._worker_id is None:
            raise RuntimeError("worker_id unset; enroll or open_session first")
        return self._worker_id

    @property
    def worker_id(self) -> Optional[int]:
        return self._worker_id

    @property
    def session_token(self) -> Optional[str]:
        return self._session_token

    @staticmethod
    def wake_channels_for_enrollment(
        *,
        cluster_key: str,
        capabilities: Optional[Iterable[str]] = None,
        program_id: Optional[str] = None,
    ) -> list[str]:
        """Logical wake channels implied by enrollment (pool + capabilities + optional program)."""
        channels: list[str] = [wake_channel_for_pool(cluster_key)]
        for cap in capabilities or ():
            name = str(cap).strip()
            if name and name != "*":
                channels.append(wake_channel_for_capability(name))
        if program_id:
            channels.append(wake_channel_for_program(program_id))
        seen: set[str] = set()
        out: list[str] = []
        for ch in channels:
            if ch not in seen:
                seen.add(ch)
                out.append(ch)
        return out

    def wait_idle_then_request_task(
        self,
        subscriber: WorkerWakeSubscriber,
        wake_channels: Iterable[str],
        *,
        poll_timeout_seconds: Optional[float] = None,
        capability: Optional[str] = None,
        max_lease_seconds: Optional[int] = None,
        worker_token: Optional[str] = None,
    ) -> TaskPollResult:
        """Interruptible idle wait, then claim (notify via pub/sub, own via claim)."""
        timeout = (
            poll_timeout_seconds
            if poll_timeout_seconds is not None
            else float(os.environ.get("WORKER_WAKE_POLL_SECONDS", "30"))
        )
        wid = self._require_worker_id()
        self._ensure_worker_session(worker_token)
        if not self._session_token:
            raise RuntimeError("worker session not open; call enroll or open_session")

        channel_list = list(wake_channels)
        subscriber.subscribe(
            channel_list,
            session_token=self._session_token,
            worker_id=wid,
        )
        try:
            subscriber.wait_for_wake(timeout_seconds=timeout)
        finally:
            subscriber.unsubscribe()

        return self.request_task(
            capability=capability,
            max_lease_seconds=max_lease_seconds,
            worker_token=worker_token,
        )

    def _ensure_worker_session(self, worker_token: Optional[str] = None) -> None:
        """Reuse the open bearer when it already belongs to this identity token."""
        if not worker_token:
            return
        if self._session_token and self._identity_token == worker_token:
            return
        self.open_session(worker_token)

    def request_task(
        self,
        worker_id: Optional[int] = None,
        worker_token: Optional[str] = None,
        capability: Optional[str] = None,
        *,
        max_lease_seconds: Optional[int] = None,
    ) -> TaskPollResult:
        wid = worker_id if worker_id is not None else self._require_worker_id()
        self._ensure_worker_session(worker_token)
        if not self._session_token or not self._identity_token:
            raise RuntimeError("worker session not open; call enroll or open_session")

        payload: Dict[str, Any] = {
            "worker_id": wid,
            "max_lease_seconds": max_lease_seconds
            or int(os.environ.get("WORKER_LEASE_SECONDS", "300")),
        }
        if capability:
            payload["capability"] = capability

        body = self._post_json("/workers/tasks/request", payload)
        control = _control_from_body(body)
        if not body.get("has_task") or body.get("node_execution_id") in (None, ""):
            return TaskPollResult(claim=None, control=control)

        inp = body.get("input_json") or {}
        if isinstance(inp, str):
            inp = json.loads(inp) if inp else {}

        claim = TaskClaim(
            node_execution_id=int(body["node_execution_id"]),
            workflow_instance_id=int(body.get("workflow_instance_id") or 0),
            action_name=str(body.get("action_name") or ""),
            capability=str(body.get("capability") or ""),
            input_json=inp,
            node_key=str(body.get("node_key") or ""),
            attempt_no=int(body.get("attempt_no") or 1),
            iteration_no=int(body.get("iteration_no") or 0),
        )
        return TaskPollResult(claim=claim, control=control)

    def submit_result(
        self,
        node_execution_id: int,
        worker_id: int,
        worker_token: str,
        result_code: int,
        output_json: Optional[Dict[str, Any]] = None,
    ) -> SubmitAck:
        self._ensure_worker_session(worker_token)
        payload: Dict[str, Any] = {
            "worker_id": worker_id,
            "result_code": result_code,
        }
        if output_json is not None:
            payload["output_json"] = output_json

        body = self._post_json(f"/workers/tasks/{node_execution_id}/submit", payload)
        return SubmitAck(
            accepted=bool(body.get("accepted", True)),
            instance_status=str(body.get("instance_status") or ""),
            next_ready_count=int(body.get("next_ready_count") or 0),
        )

    def heartbeat(
        self,
        node_execution_id: int,
        worker_id: int,
        worker_token: str,
        *,
        extend_seconds: Optional[int] = None,
    ) -> HeartbeatAck:
        self._ensure_worker_session(worker_token)
        body = self._post_json(
            f"/workers/tasks/{node_execution_id}/heartbeat",
            {
                "worker_id": worker_id,
                "extend_seconds": extend_seconds
                or int(os.environ.get("WORKER_LEASE_SECONDS", "300")),
            },
        )
        return HeartbeatAck(
            rows_updated=int(body.get("rows_updated") or 0),
            control=_control_from_body(body),
        )

    def fail_task(
        self,
        node_execution_id: int,
        worker_id: int,
        worker_token: str,
        error_code: int,
        error_message: Optional[str] = None,
    ) -> None:
        self._ensure_worker_session(worker_token)
        payload: Dict[str, Any] = {
            "worker_id": worker_id,
            "error_code": error_code,
        }
        if error_message:
            payload["error_message"] = error_message
        self._post_json(f"/workers/tasks/{node_execution_id}/fail", payload)

    def create_workflow_instance(
        self,
        workflow_version_id: int,
        context_json: Optional[Dict[str, Any]] = None,
        *,
        start: bool = True,
    ) -> Dict[str, Any]:
        body = self._post_json(
            "/workflows/instances",
            {
                "workflow_version_id": workflow_version_id,
                "context_json": context_json or {},
                "start": start,
            },
        )
        return body

    def get_workflow_instance(self, instance_id: int) -> Dict[str, Any]:
        return self._get_json(f"/workflows/instances/{instance_id}")

    def list_actions(self) -> list[Dict[str, Any]]:
        body = self._get_json("/actions")
        return list(body.get("actions") or [])
