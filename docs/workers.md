# Distributed workers

Workers never open the database. They call the REST gateway defined in `contracts/openapi.yaml` and implemented in `workflow_engine/rest/gateway.py`. The client in this repository is `goliath_worker.WorkflowRestClient`.

Default base URL is `METHYL_API_BASE`, or `http://localhost:8080/v1`.

## Enrollment

Enrollment is two steps. The gateway mints credentials. It does not accept a caller-supplied token.

1. A portal caller inserts an allowlist row with `portal.sp_upsert_cluster` and `portal.sp_upsert_worker_enrollment(cluster_key, public_ip, external_worker_key)`. The enrollment status starts at `PENDING`. The cluster's `allowed_source_cidrs` gains `<ip>/32` when that CIDR is missing. `portal.sp_revoke_worker_enrollment` sets `REVOKED`.
2. The worker VM calls `POST /v1/workers/enroll` with `cluster_key`, `external_worker_key`, and optional `capabilities` (a JSON array) and `arc_resource_id`. No `worker_id` or `worker_token` is sent.

The gateway takes the client IP from the connection. When the direct peer is inside `GATEWAY_TRUSTED_PROXY_CIDRS` (default `127.0.0.1/32` and `::1/128`), it uses `X-Real-IP` or the last address in `X-Forwarded-For`. The IP is not read from the JSON body. An empty address is HTTP 400.

`wf.sp_worker_enroll` then:

- Requires an `ACTIVE` cluster and an allowlist row for `external_worker_key`.
- Rejects `REVOKED` and an unknown key.
- Requires the client IP to equal the stored `public_ip` or the host part before `/`.
- Upserts `wf.worker` (`status` `REGISTERED`, capabilities from the request, default `[]`).
- Replaces `wf.worker_token` with the SHA-256 digest of a token the gateway generated (`secrets.token_hex(32)`).
- Sets the enrollment row to `ENROLLED`.

HTTP 200 returns `worker_id`, `worker_token` (plaintext, once), `external_worker_key`, and `cluster_key`. A refused enrollment is HTTP 403. `goliath_worker` raises on 403 and does not fall back to SQL.

`WorkflowRestClient.enroll` is the client call. There is no enroll console script in this repository.

## Dual activation (push wake + claim)

Idle workers today use the claim loop below as a **pull** path. Tier 1 also defines an optional **push wake**: the gateway publishes a small notify on pool/capability/program channels; workers interrupt idle wait, then **still claim** so the lease stays single-owned. Poll remains the safety net. See [dual-activation.md](dual-activation.md) for message shape, channel naming, failure modes, and rollout.

## Claim loop

| Call | Gateway path | Database |
|------|----------------|----------|
| Authenticate | `POST /v1/workers/authenticate` | `wf.wf_worker_authenticate` |
| Claim | `POST /v1/workers/tasks/request` | `wf.sp_worker_request_task` |
| Submit | `POST /v1/workers/tasks/{id}/submit` | `wf.sp_worker_submit_result` |
| Heartbeat | `POST /v1/workers/tasks/{id}/heartbeat` | `wf.sp_worker_heartbeat` |
| Fail | `POST /v1/workers/tasks/{id}/fail` | `wf.sp_worker_fail_task` (HTTP 204) |

Request JSON always includes `worker_id` and `worker_token`. Claim accepts optional `capability` and `max_lease_seconds` (default 300, or `WORKER_LEASE_SECONDS` on the client). Submit sends `result_code` and optional `output_json`.

`capabilities` on the worker:

| Stored value | Claim behavior (`wf.wf_worker_is_omnibus`) |
|--------------|-----------------------------------------------|
| JSON array containing `"*"` | Any task capability. |
| NULL or `[]` | No capabilities. No task is returned. |
| Concrete names | Only tasks whose `wf.workflow_action.capability` is in the array. |

The request's `capability` field narrows inside that set. It cannot add a capability the worker lacks. A task with a null capability is allowed by `wf.wf_worker_capability_allowed`.

While `desired_state` is `DRAINING` or `STOPPING`, the response has `has_task` false and `command` `DRAIN` or `STOP`. Heartbeat returns the same control fields (`rows_updated`, `desired_state`, `command`). An empty poll may omit `has_task` or send a null `node_execution_id`; the client treats that as idle.

Optional checks, off unless the environment flag is set:

- `GATEWAY_WORKER_IP_BIND` — client IP must fall in the cluster `allowed_source_cidrs` when that list is non-empty.
- `GATEWAY_REQUIRE_ARC_ATTEST` — `X-Arc-Resource-Id` must equal the cluster `arc_resource_id` when one is stored. The client sends the header from `ARC_RESOURCE_ID` or from `METHYL_ARC_ENV` (default `/etc/methyl/arc.env`).

`GATEWAY_REQUIRE_ENTRA` is read into the auth config and does not gate worker routes. Workers authenticate with `worker_token`.

`WorkflowRestClient` also defines `create_workflow_instance`, `get_workflow_instance`, and `list_actions`. The gateway routes in this tree do not implement those paths.

## Session authentication

Workers use **gateway sessions**, not portal user sessions. After enrollment, `POST /v1/workers/authenticate` exchanges `worker_id` and `worker_token` for a short-lived `session_token`. Subsequent claim, heartbeat, submit, and fail calls send that bearer token (header `Authorization: Bearer …` on the client). The gateway hashes tokens at the database boundary (`wf.wf_worker_session_touch`, `wf.sp_worker_request_task`, and related procedures in `wf_worker_session_api.sql`).

| Concern | Portal user | Worker |
|---------|-------------|--------|
| Credential | Portal login → `portal.sp_session_open` | Enroll → `worker_token` |
| Storage | `"RBAC"."SessionTokens"` | `wf.worker_session` |
| DB role | `goliath_portal` (semantic + session procs) | `goliath_gateway` (`wf.sp_*` only) |
| HTTP surface | Application BFF (not in this repo) | `workflow_engine/rest/gateway.py` |

Workers never call `portal.sp_run_semantic_request`. Portal backends never call `wf.sp_worker_request_task` directly; they use the semantic client or future GraphQL façade.

## Fleet

One database leases work to many workers. Each enrolled VM polls with its own token. Capability arrays split the fleet. `max_per_worker`, `exclusive_worker`, and the affinity columns (see [workflow-engine.md](workflow-engine.md)) decide which READY row a given worker may take. `portal.sp_list_clusters` and `portal.sp_list_worker_enrollments` read the allowlist back.

`goliath_worker.work_share` is the optional `/work` permission helper for hosts that share a mount and differ in numeric uid. It is not required to claim a task.

Action execution, CLI tools, and in-process handlers are outside this repository. After a claim, the caller runs its own code and `submit_result`.
