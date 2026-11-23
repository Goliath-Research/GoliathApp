# History and audit

GoliathApp keeps a complete, tamper-evident history of what happened on the platform. History must
exist with no gaps: a record is never silently changed or removed, and anything removed under a
retention policy leaves a verifiable trace.

This page is built up by a stack of pull requests:

| Slice | What it adds | Status |
|-------|--------------|--------|
| **H1 — Ledger core** | Append-only, hash-chained ledgers for every platform audit table and the event plane; verification and checkpoints | This page, sections 1–4 |
| H2 — Meta object history | `"Meta"."ObjValuesHistory"`: every object value, object lifecycle and instance link change, attributed | Follow-up PR |
| H3 — Run history and retention | Workflow run history ledger, no cascading deletes of runs, `platform/RetentionPolicy` purges with tombstones | Follow-up PR |
| H4 — Electronic signatures | `platform/ElectronicSignature`: signer, meaning, time and content hash bound to a record | Follow-up PR |

## 1. Ledgers

A **ledger** is a table whose rows are facts. `workflow_engine/sql_pg/platform_history_ledger.sql`
registers a table with `portal.sp_ledger_register(ledger_name, table, order_by, description, dedupe_columns)`.
Registration:

* adds four columns: `ledger_seq` (contiguous per ledger), `txid` (the writing transaction),
  `prev_hash` and `row_hash`;
* chains the rows that already exist, oldest first, the first time the table is registered (so an
  existing deployment keeps its history);
* installs `trg_ledger_before_insert`, `trg_ledger_guard` (UPDATE / DELETE) and
  `trg_ledger_no_truncate`, and revokes UPDATE / DELETE / TRUNCATE from `PUBLIC`.

Registered by the platform:

| Ledger | Table | Records |
|--------|-------|---------|
| `portal.record_editor_audit` | `portal.record_editor_audit` | Record editor saves, deletes, fleet and run actions |
| `portal.model_authoring_audit` | `portal.model_authoring_audit` | Child-namespace model authoring |
| `portal.security_admin_audit` | `portal.security_admin_audit` | Users, roles, grants, class and object ACLs |
| `portal.god_architect_audit` | `portal.god_architect_audit` | `platform/*` catalog changes and God Architect grants |
| `portal.session_active_role_audit` | `portal.session_active_role_audit` | Active role per session |
| `portal.external_identity_link_audit` | `portal.external_identity_link_audit` | External identity links at first sign-in |
| `onboarding.audit_log` | `"Onboarding"."AuditLog"` | Invitation lifecycle |
| `wf.event` | `wf.event` | Ingested events (deduplicated on `source`, `idempotency_key`) |
| `wf.event_delivery` | `wf.event_delivery` | How each event was applied |

`wf.event_delivery` no longer has foreign keys to runs, nodes or subscriptions: a history row keeps the
id it referred to even when the referenced runtime row is retired. Deleting a subscription keeps its
recorded events and deliveries, as before.

## 2. Hash chain

For each new row the insert trigger takes the ledger head (`portal.ledger_head`, locked for the rest
of the transaction), assigns `ledger_seq = last_seq + 1`, and computes

```text
row_hash = sha256(prev_hash || canonical_json(row without row_hash, null keys removed))
```

with `TimeZone = UTC`, `bytea_output = hex` and fixed float output, so the bytes are identical in
every session. Null keys are removed so a ledger table can later gain nullable columns without
changing old hashes. Ledger tables must only gain **nullable columns without defaults**.

Ledgers that use `INSERT … ON CONFLICT DO NOTHING` (event ingest) register `dedupe_columns`; a duplicate
is skipped before it takes a sequence number, so idempotent ingest never creates a gap.

The head lock serializes writers of one ledger until commit. Audit volumes are small; high-volume
ledgers added later (run history) keep their transactions short.

## 3. What is refused

| Operation | Result |
|-----------|--------|
| `UPDATE` on a ledger row | `GS409 … append-only: rows cannot be updated` |
| `DELETE` | `GS409` unless the transaction holds a purge authorization for that ledger |
| `TRUNCATE` | `GS409` |

A purge authorization is a row in `portal.ledger_purge_authorization` for the current transaction id.
Only platform `SECURITY DEFINER` functions write it (H3 adds the retention purge). Each purged row
leaves a `portal.ledger_tombstone` (sequence number and row hash), so the chain still links through it.

## 4. Verification and checkpoints

| Function | Returns |
|----------|---------|
| `portal.fn_ledger_verify(ledger)` | One row per problem; empty means intact |
| `portal.fn_ledger_verify_all()` | Problems across every ledger |
| `portal.fn_ledger_checkpoint()` | `ledger_name`, `last_seq`, `last_hash_hex` for each ledger |

Problems:

| Problem | Meaning |
|---------|---------|
| `missing_seq` | A sequence number has neither a row nor a tombstone: rows were removed outside a purge |
| `prev_mismatch` | `prev_hash` does not equal the previous entry's hash |
| `hash_mismatch` | Row content changed after it was written |
| `head_mismatch` | The head does not match the last entry |

**Threat model.** The guards stop every application role and every ordinary mistake. A database owner
can still disable triggers; the hash chain then exposes any edit or deletion on the next verification.
To make even a rewritten chain detectable, store `portal.fn_ledger_checkpoint()` output outside the
database on a schedule (for example in your document management system or object storage with
retention lock) and compare later checkpoints against it.

```sql
SELECT * FROM portal.fn_ledger_verify_all();   -- expect no rows
SELECT * FROM portal.fn_ledger_checkpoint();   -- export and keep
```
