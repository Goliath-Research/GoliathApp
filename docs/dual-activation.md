# Dual worker activation (tier 1)

## Product requirement (worker isolation)

**Workers must not connect to PostgreSQL for wakes, pub/sub, or any purpose.** They enroll, authenticate, **subscribe to wakes**, and **claim** only through **`goliath-gateway`** HTTP APIs (`contracts/openapi.yaml`, `goliath_worker.WorkflowRestClient`). The gateway alone holds database credentials; it publishes wakes after event ingest, workflow start, and related hooks. Wake delivery to workers is **gateway-mediated** (authenticated worker session; long-poll, SSE, WebSocket, or equivalent—**not** documented here as a final route until the gateway exposes it in the contract).

**Claim remains** `POST /v1/workers/tasks/request` — the **only** lease grant.

## Known defect: worker-side Postgres `LISTEN` (superseded — do not adopt)

The tree still contains **`PostgresWorkerWakeSubscriber`** (`goliath_worker/postgres_wake.py`) and env flags such as **`WORKER_WAKE_POSTGRES`** / **`WORKER_WAKE_PG_DSN`**, which open a **direct** Postgres connection for `LISTEN`. That pattern let workers receive `NOTIFY` without going through the gateway. **Treating the database as a worker wake bus is rejected for child apps and new deployments** — it violates isolation, spreads DSNs to worker hosts, and exposes the critical database to fleet machines.

- **Do not** enable `WORKER_WAKE_POSTGRES` for adopters; **do not** document worker `LISTEN` as the inheritance path.
- **Follow-up:** replace worker-side `LISTEN` with **gateway-only** subscribe + forward (this document remains the DTO and channel vocabulary spec until OpenAPI catches up).

GoliathApp and **goliath-gateway** support two ways to get idle workers moving toward READY work:

1. **Pull / claim (existing)** — workers call `POST /v1/workers/tasks/request` (`wf.sp_worker_request_task`). This remains the **safety net**, the **backlog path**, and the **only** path that grants a lease.
2. **Push wake (intended)** — after `POST /v1/events` or workflow start, the **gateway** publishes a **small wake** (pool / capability / program channel). Workers receive it **via the gateway** (authenticated session), **interrupt idle wait**, then **still claim** so ownership stays single: **notify via gateway bus, own via claim**.

This document is tier **1** (shared platform). Product-specific wakes (for example tier-2 satellite I&T issue #3 in the satellite repo) and live OPC telemetry fan-out are **out of scope** here.

## Problem

Events already create or advance workflow instances (`POST /v1/events` → `wf.sp_ingest_event`). Workers today discover READY actions only by polling claim. That adds latency when the response should start immediately. Pure push without claim is a poor fit for long jobs: duplicate starts, lost messages, and ambiguous retries.

Dual activation keeps poll/claim semantics (heartbeats, fail/requeue, capability matching, fleet drain/stop) and adds a **hint** so idle workers wake sooner.

## Non-goals (this slice and tier 1)

| Topic | Status |
|-------|--------|
| Live tier-2 OPC telemetry in the claim loop | **Excluded** — telemetry uses a separate bus (publish once, many listeners), not leased work. |
| Product-specific wake channels (field I&T, tier-2 workload spikes) | **Tier 2** — builds on these channel names and DTOs. |
| Production Redis / NATS / other external wake bus behind the gateway | **Optional later** — workers still see **only** the gateway; the gateway adapts internal or external publish. |
| Workers using Postgres `LISTEN` / DSN | **Superseded (defect)** — see “Known defect” above; **not** for adoption. |
| Changing lease SQL (`wf.sp_worker_request_task`) | **Unchanged** |
| Replacing claim with message-carried task payloads | **Rejected** — wakes carry no `input_json` and no lease. |

## Notify vs own

```mermaid
sequenceDiagram
  participant Source as Event / portal edge
  participant GW as goliath-gateway
  participant W as Worker VM

  Source->>GW: POST /v1/events (or authorized start path)
  GW->>GW: wf.sp_ingest_event (and DB hooks)
  GW->>GW: publish WorkerWakeMessage (internal / NOTIFY / future bus)
  Note over GW: Wake is gateway-originated; workers never LISTEN on Postgres
  W->>GW: subscribe to wake channels (gateway API; auth session — future contract)
  GW-->>W: WorkerWakeMessage (when a wake matches subscription)
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

### Event payload hints (optional override)

Adapters may attach optional overrides under `worker_wake`. When present, these fields **merge with** subscription-derived hints from the database (override rows first):

```json
{
  "event_type": "upload.landed",
  "source": "storage-adapter",
  "idempotency_key": "…",
  "payload": {
    "worker_wake": {
      "pool": "west",
      "capability": "align_bam",
      "program_id": "my-program@v1"
    }
  }
}
```

When `applied_count > 0`, the gateway loads claimable-task dimensions via `wf.fn_worker_wake_hints_for_event` (pool from instance `context_json.pool`, capability from READY actions, program from publish/study links). `payload.worker_wake` remains supported as an override; it is no longer required for wakes to fire.

## Channel naming

Prefix: `goliath.wake.v1`.

| Target | Channel pattern | Helper |
|--------|-----------------|--------|
| Pool | `goliath.wake.v1.pool.{pool}` | `wake_channel_for_pool` |
| Capability | `goliath.wake.v1.capability.{name}` | `wake_channel_for_capability` |
| Program | `goliath.wake.v1.program.{program_id}` | `wake_channel_for_program` |

Segments are normalized (unsafe characters → `_`). A message may publish to **multiple** channels when more than one dimension is set.

### Postgres `NOTIFY` channel mapping (gateway implementation detail)

When the gateway uses Postgres `NOTIFY` as its **internal** transport, channel identifiers are limited to **63 characters** and must not rely on `.` (logical names use dots). The gateway maps logical names to NOTIFY identifiers without changing the JSON payload (`WorkerWakeMessage`). **Workers do not use this mapping** — only gateway code may call `NOTIFY` / `LISTEN` on the database connection.

| Logical (pub/sub API) | Postgres `NOTIFY` channel |
|-----------------------|---------------------------|
| `goliath.wake.v1.pool.{segment}` | `gw1_pool_{segment}` |
| `goliath.wake.v1.capability.{segment}` | `gw1_capability_{segment}` |
| `goliath.wake.v1.program.{segment}` | `gw1_program_{segment}` |

Implementation: `goliath_worker.wake.logical_wake_channel_to_pg_notify`. Underscores in `{segment}` are preserved (they already replace unsafe characters in the logical name). When the NOTIFY name would exceed 63 characters, the channel becomes `gw1_{kind}_h{sha256(logical)[:16]}` (truncated to 63).

**Subscription (intended):** workers register interest in the union of channels implied by enrollment (pool), declared **capabilities**, and optional program binding — tier 2 may refine rules. `WorkflowRestClient.wake_channels_for_enrollment` builds that **logical** list for use **with a gateway-mediated subscriber** (not with direct `LISTEN`). Idle wait should **wake then always claim** once the gateway exposes subscribe in `contracts/openapi.yaml`.

**Historical:** `wait_idle_then_request_task` + `PostgresWorkerWakeSubscriber` used direct `LISTEN`; that path is **superseded** — see “Known defect” above.

## Failure modes

| Scenario | Behavior |
|----------|----------|
| **Lost wake** | Worker stays idle until the next claim poll (existing backoff). Poll remains the safety net. |
| **Duplicate wake** | Harmless; multiple workers wake and **claim**; `wf.sp_worker_request_task` gives at most one lease; losers get empty claim and return to idle/subscribe. |
| **Wake without matching READY work** | Claim returns idle; worker resubscribes or polls. |
| **Publisher down** | With gateway internal wake publishing disabled (`WF_WAKE_POSTGRES` unset when the gateway uses Postgres `NOTIFY`), `NullWorkerWakePublisher` default: no wake traffic; behavior identical to poll-only today. |
| **Stale wake_id** | Subscribers may ignore repeats; claim is authoritative. |

## Gateway publish hooks

| Edge | Status | Notes |
|------|--------|-------|
| `POST /v1/events` after `wf.sp_ingest_event` | **Automatic** | Hint query + optional `payload.worker_wake` override; coalesced NOTIFY when `WF_WAKE_POSTGRES=1`. |
| `sp_start_workflow_instance` (portal/API) | **Automatic** | Postgres gateway backend publishes after start via `publish_wakes_after_workflow_instance_start`. |
| Lease reclaim → READY | **Helper** | `publish_wakes_after_lease_reclaim` for non-quiet reclaim callers; claim-path quiet reclaim uses poll safety net. |
| Tier-2 product wakes | **Hook** | `worker_wake_tier2.register_tier2_wake_extension` (satellite tier-2 issue #3). |

Implementation entry points:

- `workflow_engine/rest/gateway.py` — injectable `wake_publisher`.
- `workflow_engine/rest/worker_wake.py` — ingest/start/reclaim publish helpers, hint merge, tier-1 publish.
- `workflow_engine/rest/worker_wake_tier2.py` — tier-2 extension registration stub.
- `workflow_engine/rest/wake_coalesce.py` — debounced publisher wrapper (NOTIFY burst control, payload size guard).
- `workflow_engine/sql_pg/wf_worker_wake_hints.sql` — `fn_worker_wake_hints_for_{event,instances,node_executions}`.
- `goliath_worker/wake.py` — DTO, channel helpers, NOTIFY mapping, `WorkerWakePublisher` / `WorkerWakeSubscriber` protocols, null implementations.
- `goliath_worker/postgres_wake.py` — Postgres `NOTIFY`/`LISTEN` (**gateway**: publisher; **worker** subscriber present but **superseded** for adoption — see “Known defect”).
- `workflow_engine/rest/postgres_wake.py` — `resolve_wake_publisher` for gateway startup.

## Worker subscribe while idle (required design)

**Target idle loop** for descendant worker processes (gateway-only; claim unchanged):

1. Open gateway **worker session** (`POST /v1/workers/session` or enroll with session).
2. **Subscribe to wake channels through the gateway** using the **same** authenticated worker session as claim (long-poll / SSE / WebSocket / equivalent — **follow-up** until listed in `contracts/openapi.yaml`). The gateway must **reject** unauthenticated subscribe attempts.
3. Block until a wake arrives or a **timeout** elapses (align timeout with the existing claim poll safety net).
4. On wake or timeout: **`POST /v1/workers/tasks/request`** — unchanged claim path.
5. If claim empty: return to step 2. If claim wins: **unsubscribe** or pause subscription during execution; heartbeats / submit / fail unchanged.

`goliath_worker.wake.NullWorkerWakeSubscriber` and **timed claim polling** remain valid: **poll-only** is always supported when wakes are unavailable.

### Configuration (gateway-oriented)

| Variable | Component | Meaning |
|----------|-----------|---------|
| `WF_WAKE_POSTGRES=1` | Gateway | When using Postgres `NOTIFY` **inside** the gateway process: `PostgresWorkerWakePublisher` on the gateway DSN. Default off → `NullWorkerWakePublisher`. |

### Superseded worker env (do not adopt)

| Variable | Status |
|----------|--------|
| `WORKER_WAKE_POSTGRES`, `WORKER_WAKE_PG_DSN` | **Superseded** — enabled direct worker `LISTEN`; **do not** set for new child apps. |
| `WORKER_WAKE_POLL_SECONDS` | Poll interval helper when not using wakes; unrelated to DSN. |
| `WF_WAKE_COALESCE_SECONDS` | Gateway debounce when using coalesced internal `NOTIFY`. |

## Security

- **Subscribe requires worker session** — same bearer session as claim (`Authorization: Bearer` + identity header on **gateway** routes). Anonymous subscribers must not receive fleet wakes (capability and pool metadata leaks work queue shape).
- **Publish is gateway-side** — only trusted gateway code (after DB ingest or authorized portal paths) holds credentials for internal or external wake transport; **workers never receive a database DSN for wakes**.
- Wakes carry **no secrets** and no PII by convention; adapters should keep hints minimal.

## Rollout plan

1. **Done (PR #23)** — design doc, DTO/protocol stubs, `NullPublisher` default, event-ingest hook, tests for channel naming and payload parsing.
2. **Done (PR #24)** — Postgres `NOTIFY`/`LISTEN` experiment (gateway publish + **worker `LISTEN`**); worker direct DB path **superseded** by gateway-only requirement above.
3. **This slice (PR #37)** — automatic subscription-derived wakes, coalesced NOTIFY, instance-start publish, tier-2 hook stub, integration tests.
4. **Tier 2** — Satellite product channels and OPC/telemetry separation (issue #3).
5. **Operate** — metrics on wake publish count, claim latency p50/p95 with wakes enabled, duplicate wake rate vs empty claims.

## Related docs

- [workers.md](workers.md) — claim loop and sessions
- `workers/WORKER_PROTOCOL.md` (repository root) — HTTP contract including wake fields
- GitHub: [GoliathApp #22](https://github.com/Goliath-Research/GoliathApp/issues/22)
