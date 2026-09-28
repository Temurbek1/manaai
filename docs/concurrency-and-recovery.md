# Concurrency and recovery

## Transaction boundaries

The repository uses database constraints plus insert-first behavior rather than preflight scans:

- proposal and approval request are inserted in one transaction;
- only one configuration version is active and concurrent version conflicts return `409`;
- run and execution idempotency keys are unique and concurrent creators receive the persisted row;
- approval decision, approval-request state, and proposal state transition together;
- proposal, execution, and optional verification finalize in one transaction;
- one execution per proposal, one analysis per run, and one report per run/type are constrained;
- SQLite enables foreign keys; PostgreSQL migrations prove the same relationship graph.

Provider writes are serialized by a database lease named from provider, object type, and provider
object ID. The lease covers fresh-state read, policy re-evaluation, dispatch, read-after-write, and
finalization. Expired leases can be recovered; owner checks prevent another worker from releasing a
live lease.

## Action recovery states

| Event | Persisted result | Recovery |
| --- | --- | --- |
| stale hash, expired proposal, missing policy/config, wrong currency/minimum, kill switch, or daily limit before dispatch | no provider write; controlled failed/retryable transition according to safety class | create a new proposal or resolve the control; never bypass the check |
| provider not-found/permanent rejection before acceptance | failed execution/proposal | inspect object/permissions; new proposal required |
| transient pre-dispatch read failure | approved proposal remains retryable | retry explicit execution after provider recovery |
| timeout/connection loss/5xx after POST dispatch | proposal and execution stay `executing`, `write_outcome_uncertain` | maintenance or explicit execution re-reads provider state; it does not blind-POST |
| provider accepts but intended state is not visible yet | bounded read attempts; then `executing/verification_unavailable` | later reconciliation |
| provider applies a different or partial value | `partially_applied` with mismatch verification | kill switch/human review; do not automatically compensate |
| process dies after provider change but before final DB commit | lease eventually expires; persisted executing/idempotency record is reconciled | recovery reads state and commits verification exactly once |

`tests/test_action_recovery.py` simulates a timeout after the fake provider has applied a change,
proves only one dispatch, and then proves restart-style reconciliation. Domain/API tests cover
eventual consistency and mismatched values.

## Scheduler recovery

Each due occurrence has an identity `schedule-occurrence:{schedule_id}:{scheduled_at}`. A worker:

1. reads due schedules;
2. acquires that occurrence lease;
3. atomically consumes the due occurrence by moving `next_run_at` to a future cron slot,
   before any provider I/O; a stale due-list cannot claim it again;
4. runs at most `OPERATION_SCHEDULER_MAX_ATTEMPTS` attempts, retrying only explicit transient
   errors/timeouts/lock contention, with a distinct occurrence/attempt idempotency key;
5. records completion and advances to a future slot after both success and failure;
6. releases the lease.

If the worker dies before claiming, the due occurrence can be claimed after lease expiry. If it
dies after claiming, that occurrence is consumed and is **not automatically replayed**. This
at-most-once policy deliberately trades a possibly missed report for no duplicate paid collection.
Historical overdue slots are skipped; there is no catch-up scan storm. Terminal failed runs never
reopen with the same idempotency key. Two-worker races, stale claims, finite retries and dead-worker
lease recovery are tested. Cron calculation works in UTC while matching local wall-clock values, skips
nonexistent DST minutes, and does not duplicate a folded minute.

The job runner has a whole-job timeout. Provider reads have request timeouts/retries; writes have no
blind transport retry. Schedule update preserves identity, validates timezone, and atomically
compares the persisted occurrence before advancing, so a concurrent schedule edit cannot be
overwritten by an old claim.

Consecutive permanent failures are persisted per agent/capability schedule. At
`OPERATION_SCHEDULER_PERMANENT_FAILURE_THRESHOLD`, the schedule is disabled, its circuit is opened,
an audit event is written, and an ERROR alert is logged and shown in the schedule editor. Manual
runs of that capability are blocked too. Editing analysis configuration does not reset the trip;
explicitly saving the repaired schedule as enabled resets it. Existing disabled schedules stay
disabled at bootstrap; newly created Retention schedules are disabled by default.

Retention collection cancels and drains siblings at both the source and nested HTTP-batch layers.
All Firestore sources in a run share one explicit budget for requested document-read bounds,
pages and HTTP attempts. Every retry reserves its full page/query limit before dispatch; cancelled
or ambiguous requests are not refunded. See the live product activity runbook for billing caveats
and canary limits.

## Database evidence

`scripts/postgres_audit.sh` starts an isolated PostgreSQL 17 container, upgrades, downgrades,
upgrades again, checks schema drift, and runs 16-way lease/schedule/run contention. The container is
removed afterward. `scripts/sqlite_migration_audit.sh` does the same clean round trip for SQLite and
upgrades a copy of the existing development database when present.

SQLite is supported for local/single-process work only. PostgreSQL is the required production
coordination store.
