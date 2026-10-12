# Native agent workspace: release and application rollback

Status: the scoped release is deployed; see [actual versions and checks](operation-agent-workspace-production-release.md).
This document is a bounded release checklist,
not authorization to change unrelated services or activate sources/schedules. The full
objective remains in [operation-agent-workspace.md](operation-agent-workspace.md).

## Storage contract

`c75f0a6e812b` adds nullable `workspace_status` and `workspace_payload` columns plus an index
to `operation_goals`; historical rows are not backfilled or rewritten. Ordinary analysis
Goals without native context keep the prior JSON contract and queue. Native checkpoints store
protocol version 1 without session memory, version 2 with analysis-only session memory,
version 3 when that memory includes scoped sandbox action history, or version 4 for
an explicitly chosen historical `saved_snapshot` deliverable,
the complete request/context/tool journal and actual status separately. Capacity/claim/control
logic in the new repository uses that actual status and the same revision fence.

For old code, native rows have a closed legacy status/strict-compatible JSON projection:
completed work remains completed; other native states appear closed/cancelled with an
explanation that the compatible workspace is required. This is a compatibility view, not an
actual user cancellation. Old workers cannot claim them and old command handlers reject them.
New code reads the original state from the versioned checkpoint, not that projection.

Historical scope remains private native state and never appears in strict legacy request JSON.
Current-data Goals retain protocols 1–3/default current scope. V4/scope mismatches fail closed;
historical Goals cannot obtain source-read approval or become current-data tasks through steering.
The historical result may finish with dated full evidence, not as a current metric or outcome.

Checkpoint v5 is required when new private task-history tools or nonempty `also_kinds` context
labels are present. Its explicit `analysis_scope` must match the frozen Goal request. Older
versions keep their prior scope/version rules; no stored history is rewritten or migrated.
Task prose/role labels never grant reads/actions or populate fresh evidence. Closed legacy
projections omit tools/session memory/new request fields, so the supported old `2ea7b9a` image
can read them but cannot execute native work. Do not roll back to an arbitrary unreleased
intermediate workspace image.

`d86a1b9f023c` adds nullable `operation_chat_turns.workspace_metadata` without rewriting old
conversations. Execution mode, native handoff and session memory are kept outside both the
strict legacy chat JSON and its legacy-readable `context_metadata`. The supported old image
sees a completed native handoff as an ordinary message with no executable next action; the new
reader restores the original handoff/memory. Schema downgrade refuses either native chat or
Goal history before dropping any workspace column. Rollback targets the recorded production
release, not every intermediate unreleased workspace protocol.

`e97b2c0a134d` adds `operation_workspace_events`, an indexed owner/topic/cursor SQL journal.
There is no backfill or rewrite of previous Goals/chat. New Goal state and its public event
commit together under the shared controls/claims/save fence; cursor allocation follows commit
order. Old images ignore the extra table. Downgrade refuses existing events or native history
before dropping the journal, even when the events belong to ordinary non-native Goals.

`f08c3d1b245e` adds `operation_workspace_actions`: immutable owner/topic/turn/proposal-bound
human intents admitted before the owning-domain executor is called. A unique proposal fence
and owner/request fence prevent a second workspace dispatch across processes or topics. The
receipt retains confirmed typed parameters and synthetic MANA scope; SQL domain execution and
verification remain authoritative even if the receipt acknowledgement is lost. No old action,
chat or Goal JSON is rewritten. Source-snapshot cleanup does not erase the settled action
history. Downgrade refuses receipts, events or native context before dropping any table.
`OPERATION_WORKSPACE_ACTIONS_ENABLED` is subordinate to the disabled-by-default native flag.
Only `fake_experiments`/`growth_experiment`/`create_experiment` on explicitly fictional MANA
parent funnel facts is supported. Historical unverified chat cards are read-only; the existing
professional action queue is unchanged. This is not a live experiment rollout or a write tool
for read-only Goals, and provider verification is not measured business improvement.

`OPERATION_WORKSPACE_CHAT_STREAMING_ENABLED=false` is a separate optional activation,
subordinate to native workspace and event journal flags. It adds no migration: draft metadata
uses the existing nullable workspace column, and typed `chat_text` notifications share the
existing journal with Goal progress under its commit-order fence. The supported old image
ignores those private metadata fields/table; `/events` stays Goal-only for older clients.
Drain active ordinary chat producers before rollback. Retain cancelled/failed drafts and cost
holds; a lost model receipt is not permission to refund or regenerate. Streaming activation
does not change source credentials, cooldowns, permissions or schedules.

An older API may create an ordinary Goal in a topic whose native Goal it sees as closed.
Therefore keep Goals creation/worker execution disabled during rollback. Do not serve a
mixed-version writable Goals deployment. The local compatibility probe does not replace
these release controls.

## Before activation

Pending known-priced format correction uses private Goal checkpoint v7. It is accepted only
with the original scoped continuation, typed `invalid_decision` feedback and the existing
shared two-recovery/step/cost bounds. Clear feedback returns to a v6 window; original history
and accounted costs remain. The supported old image reads only the closed compatibility
projection, not this feedback/queue. Preserve it during explicit pause/application rollback;
do not downgrade a populated schema or swap in an unreleased intermediate native reader.
The real synthetic benchmark first failed one structured decision; its malformed body was
not retained. Bounded fault-recovery evidence does not prove the exact original cause fixed
or authorize retrying unknown provider/source outcomes.

1. Verify/review the exact commit and contract; build the sidecar/worker and UI images.
   Run `make verify`, separate PostgreSQL migration/concurrency tests, native and legacy
   browser flows and `bash scripts/operation_workspace_compatibility_audit.sh`.
2. Record active image/config/schema references and take a protected SQL backup. Never
   print keys or overwrite application/Firebase data to prepare a release.
3. Disable new Goals admission, drain in-flight chat turns and stop/drain the Goals worker.
   Scheduler, source bindings,
   cooldowns, budgets, retention collection and audio must remain unchanged.
4. Apply the additive migration through the new release's migration tool. Keep the native
   workspace flag false until both the API and single Goals worker have compatible code.
5. Update only the operation sidecar/Goals worker and administrator UI. Do not replace the
   independent main API/audio, SSH authentication, Nginx routing or source/scheduler settings.
   The UI must route `/api/v1/admin/operation/workspace/:path*`, including its stream, to
   `OPERATION_CHAT_BASE_URL` alongside chat/Goals, not the independent main API. Build the
   UI with the intended scoped target; inspect the actual stream MIME type/cursor delivery.
6. Activate only after configured-source acceptance and the full scoped browser/API smoke
   checks are complete. Verify greeting vs analytical handoff, scope, approvals, controls,
   budget stops/reload and private-owner separation against the actual deployed version.

## Application-only rollback

1. Disable workspace/Goals admission and stop/drain **every Goals worker**; preserve the
   existing source/scheduler/main API/audio settings. Record unknown reservations; do not
   refund them or rerun a source to test whether it succeeded.
2. From the new release, use the protected `OPERATION_DATABASE_URL` configuration. Inspect:

   ```sh
   python scripts/operation_workspace_rollback.py
   ```

   The default performs only SQL reads and prints aggregate counts, no identities,
   contents, credentials or database URL. Any live lease blocks apply; wait for normal
   completion, or for the expired lost-work lease after workers are stopped. Do not
   manually clear a lease or set a consumed read back to unused.
3. With worker stop/drain confirmed, pause native Goals atomically:

   ```sh
   python scripts/operation_workspace_rollback.py --apply-pause --workers-stopped
   ```

   This affects native Goals only, preserving budgets, instructions, history and consumed
   reads. Started lost tools become unknown, unused read approvals are revoked, and native
   work remains paused. A live lease rejects the whole transaction. Repeated apply is
   idempotent. The flag is operator attestation, not automatic proof of stopped processes.
4. Restore the recorded operation API/UI images with Goals execution/admission disabled.
   Retain schema `f08c3d1b245e`, the action receipts, event journal and all native metadata.
   **Do not run old `alembic upgrade head`,
   schema downgrade, a whole-stack restart or a database restore that would erase history.**
   Old API/worker startup must not run an incompatible migration tool.
5. Verify health, login, old ordinary chat/history and the independent audio endpoint using
   non-mutating checks. Native compatibility cards must not offer executable continuation.

Rolling forward uses the compatible API/worker with the retained schema. Native Goals remain
paused until their owners explicitly resume; past unknown charges/consumed reads remain.
Do not interpret a compatibility projection's cancelled status as deletion of the checkpoint.

## Local safety evidence

The old-image probe uses only a newly created temporary synthetic SQLite DB, a read-only
probe-script mount, a validated local Unix Docker socket and `--network none`; no `.env`,
customer files, provider network or production volume is mounted. It checks actual old
strict-model chat and Goal deserialization, rejection of all old Goal controls, old-worker
queue isolation,
new-version reconstruction and explicit-pause recovery. It does not claim production was
updated or that every business analysis/action capability is implemented.
