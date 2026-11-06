"""Gateway-only event transport (uses ``goliath_worker.WorkflowRestClient``)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from goliath_worker.client import WorkflowRestClient


class GatewayEventTransport:
    """POST ``/v1/events`` with worker auth; duplicate idempotency keys return ``duplicate: true``."""

    def __init__(self, client: WorkflowRestClient) -> None:
        self._client = client

    def ingest(
        self,
        worker_id: int,
        worker_token: str,
        *,
        event_type: str,
        source: str,
        idempotency_key: str,
        payload: Dict[str, Any],
        correlation_key: Optional[str] = None,
        occurred_at_utc: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._client.post_event(
            worker_id,
            worker_token,
            event_type=event_type,
            source=source,
            idempotency_key=idempotency_key,
            payload=payload,
            correlation_key=correlation_key,
            occurred_at_utc=occurred_at_utc,
        )
