# Dual worker activation (tier 1)

GoliathApp and **goliath-gateway** support two ways to get idle workers moving toward READY work:

1. **Pull / claim (existing)** — workers call `POST /v1/workers/tasks/request` (`wf.sp_worker_request_task`). This remains the **safety net**, the **backlog path**, and the **only** path that grants a lease.
2. **Push wake (new)** — when event-triggered or portal-started work should start quickly, the gateway (or a future edge) publishes a **small wake** on a pool / capability / program channel. Subscribed workers **interrupt idle wait**, then **still claim** so ownership stays single: **notify via pub/sub, own via claim**.

This document is tier **1** (shared platform). Product-specific wakes (for example [GoliathGroundStation #3](https://github.com/Goliath-Research/GoliathGroundStation/issues/3)) and live OPC telemetry fan-out are **out of scope** here.

## Problem

Events already create or advance workflow instances (`POST /v1/events` → `wf.sp_ingest_event`). Workers today discover READY actions only by polling claim. That adds latency when the response should start immediately. Pure push without claim is a poor fit for long jobs: duplicate starts, lost messages, and ambiguous retries.

Dual activation keeps poll/claim semantics (heartbeats, fail/requeue, capability matching, fleet drain/stop) and adds a **hint** so idle workers wake sooner.

## Non-goals (this slice and tier 1)

| Topic | Status |
|-------|--------|
| Live GoliathGroundStation OPC telemetry in the claim loop | **Excluded** — telemetry uses a separate bus (publish once, many listeners), not leased work. |
| Product-specific wake channels (Ground Station I&T, Omics spikes) | **Tier 2** — builds on these channel names and DTOs. |
| Production Redis / NATS wake bus | **Optional later** — tier 1 production path is Postgres `NOTIFY`/`LISTEN` (see below). |
| Changing lease SQL (`wf.sp_worker_request_task`) | **Unchanged** |
| Replacing claim with message-carried task payloads | **Rejected** — wakes carry no `input_json` and no lease. |

## Notify vs own

```mermaid
sequenceDiagram
  participant Source as Event / portal edge
  participant GW as goliath-gateway
  participant Bus as Wake bus (pluggable)
  participant W as Worker VM

  Source->>GW: POST /v1/events (or future start edge)
  GW->>GW: wf.sp_ingest_event
  GW->>Bus: publish WorkerWakeMessage (optional)
  Bus-->>W: wake on subscribed channel
  W->>GW: POST /v1/workers/tasks/request (claim)
  GW->>GW: wf.sp_worker_request_task
  Note over W,GW: Loser on claim returns idle; winner runs action
```

- **Notify**: cheap, idempotent-friendly signal that *something* may be claimable for a pool/capability/program.
- **Own**: exactly one worker holds the lease after a successful claim; heartbeats and submit/fail unchanged.

## Wake message shape

JSON fields (see `goliath_worker.wake.WorkerWakeMessage`):

| Field | Required | Meaning |
|-------|----------|---------|
| `wake_id` | yes | Dedup key for subscribers (for example `event:{event_id}:{idempotency_key}`). |
| `reason` | yes | Producer label (for example `event_ingest:upload.landed`). |
| `pool` | one of pool / capability / program | Fleet pool or cluster key workers subscribe to. |
| `capability` | one of pool / capability / program | Narrow wake to workers with that capability. |
| `program_id` | one of pool / capability / program | Domain program id (tier 2 may add finer channels). |
| `event_id` | no | Source `wf.event.id` when wake follows ingest. |
| `workflow_instance_id` | no | Hint for observability; **not** a lease grant. |
| `occurred_at_utc` | no | ISO-8601 UTC timestamp; defaulted at publish time. |

Wakes **must not** include task input, node execution ids for claiming, or lease tokens.

### Event payload hints (gateway hook, first slice)

When ingesting events, adapters may attach optional hints under `worker_wake`:

```json
{
  "event_type": "upload.landed",
  "source": "storage-adapter",
  "idempotency_key": "…",
  "payload": {
    "worker_wake": {
      "pool": "omics-west",
      "capability": "align_bam",
      "program_id": "methyl-pipeline-v2"
    }
  }
}
```

`workflow_engine.rest.worker_wake.publish_wakes_after_event_ingest` runs after a **non-duplicate** ingest with `applied_count > 0`. Future hooks (portal instance start, graph deploy edges) should call the same helper.

## Channel naming

Prefix: `goliath.wake.v1`.

| Target | Channel pattern | Helper |
|--------|-----------------|--------|
| Pool | `goliath.wake.v1.pool.{pool}` | `wake_channel_for_pool` |
| Capability | `goliath.wake.v1.capability.{name}` | `wake_channel_for_capability` |
| Program | `goliath.wake.v1.program.{program_id}` | `wake_channel_for_program` |

Segments are normalized (unsafe characters → `_`). A message may publish to **multiple** channels when more than one dimension is set.

### Postgres `NOTIFY` channel mapping

Postgres channel identifiers are limited to **63 characters** and must not rely on `.` (logical names use dots). The gateway and workers map logical names to NOTIFY identifiers without changing the JSON payload (`WorkerWakeMessage`).

| Logical (pub/sub API) | Postgres `NOTIFY` channel |
|-----------------------|---------------------------|
| `goliath.wake.v1.pool.{segment}` | `gw1_pool_{segment}` |
| `goliath.wake.v1.capability.{segment}` | `gw1_capability_{segment}` |
| `goliath.wake.v1.program.{segment}` | `gw1_program_{segment}` |

Implementation: `goliath_worker.wake.logical_wake_channel_to_pg_notify`. Underscores in `{segment}` are preserved (they already replace unsafe characters in the logical name). When the NOTIFY name would exceed 63 characters, the channel becomes `gw1_{kind}_h{sha256(logical)[:16]}` (truncated to 63).

Workers subscribe to the union of channels implied by their enrollment (pool), declared **capabilities**, and optional program binding — tier 2 may refine subscription rules. `WorkflowRestClient.wake_channels_for_enrollment` builds that list; idle wait uses `wait_idle_then_request_task` (wake, then **always** claim).

## Failure modes

| Scenario | Behavior |
|----------|----------|
| **Lost wake** | Worker stays idle until the next claim poll (existing backoff). Poll remains the safety net. |
| **Duplicate wake** | Harmless; multiple workers wake and **claim**; `wf.sp_worker_request_task` gives at most one lease; losers get empty claim and return to idle/subscribe. |
| **Wake without matching READY work** | Claim returns idle; worker resubscribes or polls. |
| **Publisher down** | With `WF_WAKE_POSTGRES` unset, `NullWorkerWakePublisher` default: no external dependency; behavior identical to poll-only today. |
| **Stale wake_id** | Subscribers may ignore repeats; claim is authoritative. |

## Gateway publish hooks

| Edge | Status (this PR) | Notes |
|------|------------------|-------|
| `POST /v1/events` after `wf.sp_ingest_event` | **Stub wired** | Uses `RestGateway(wake_publisher=…)`; default no-op. |
| Portal / study start → new READY work | **Documented** | Call `publish_wakes_after_event_ingest` or a sibling helper when instance start is exposed on gateway. |
| Action completion → downstream READY | **Future** | May publish capability-scoped wakes from graph metadata. |

Implementation entry points:

- `workflow_engine/rest/gateway.py` — injectable `wake_publisher`.
- `workflow_engine/rest/worker_wake.py` — `publish_wakes_after_event_ingest`, payload parsing.
- `goliath_worker/wake.py` — DTO, channel helpers, NOTIFY mapping, `WorkerWakePublisher` / `WorkerWakeSubscriber` protocols, null implementations.
- `goliath_worker/postgres_wake.py` — Postgres `NOTIFY`/`LISTEN` publisher and subscriber (dedicated connections; not the gateway request pool).
- `workflow_engine/rest/postgres_wake.py` — `resolve_wake_publisher` for gateway startup.

## Worker subscribe while idle

Recommended idle loop (product worker process):

1. Open gateway **worker session** (`POST /v1/workers/session` or enroll with session).
2. `WorkerWakeSubscriber.subscribe(channels, session_token=…, worker_id=…)` — the bus implementation must **reject** subscribe without a valid session (same trust boundary as claim).
3. `wait_for_wake(timeout=…)` OR block on broker with timeout aligned to poll safety net.
4. On wake or timeout: **`POST /v1/workers/tasks/request`** (unchanged claim path).
5. If claim empty: go to step 2. If claim wins: **unsubscribe** during execution; heartbeats/submit/fail unchanged.

`goliath_worker.wake.NullWorkerWakeSubscriber` preserves poll-only behavior for hosts without a bus.

### Configuration

| Variable | Component | Meaning |
|----------|-----------|---------|
| `WF_WAKE_POSTGRES=1` | Gateway | Use `PostgresWorkerWakePublisher` on the gateway DSN (`METHYLPIPELINE_DB` / `PG*`). Default off → `NullWorkerWakePublisher`. |
| `WORKER_WAKE_POSTGRES=1` | Worker | Use `PostgresWorkerWakeSubscriber` via `resolve_worker_wake_subscriber()`. |
| `WORKER_WAKE_PG_DSN` | Worker | Optional LISTEN connection string; defaults to `METHYLPIPELINE_DB` / `PG*`. |
| `WORKER_WAKE_POLL_SECONDS` | Worker | Idle wait timeout before claim safety-net poll (default `30`). |

Wake-enabled workers open a **separate** Postgres connection for `LISTEN` only; they still **never** claim via SQL. Subscribe requires the same bearer **worker session** as claim (validated before `LISTEN`).

## Security

- **Subscribe requires worker session** — same bearer session as claim (`Authorization: Bearer` + identity header). Anonymous subscribers must not receive fleet wakes (capability and pool metadata leaks work queue shape).
- **Publish is gateway-side** — only trusted gateway code (after DB ingest or authorized portal paths) should hold publisher credentials for the external bus in production.
- Wakes carry **no secrets** and no PII by convention; adapters should keep hints minimal.

## Rollout plan

1. **Done (PR #23)** — design doc, DTO/protocol stubs, `NullPublisher` default, event-ingest hook, tests for channel naming and payload parsing.
2. **This PR** — **Postgres `NOTIFY`/`LISTEN`** as the production wake broker; `WF_WAKE_POSTGRES` gateway opt-in; worker idle subscribe + claim in `WorkflowRestClient`; NOTIFY channel mapping documented above. Redis/NATS remain optional later brokers implementing the same logical channels and JSON payload.
3. **Tier 2** — GoliathGroundStation and Omics product channels and OPC/telemetry separation verified.
4. **Operate** — metrics on wake publish count, claim latency p50/p95 with wakes enabled, duplicate wake rate vs empty claims.

## Related docs

- [workers.md](workers.md) — claim loop and sessions
- `workers/WORKER_PROTOCOL.md` (repository root) — HTTP contract including wake fields
- GitHub: [GoliathApp #22](https://github.com/Goliath-Research/GoliathApp/issues/22)
