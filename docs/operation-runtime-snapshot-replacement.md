# Exact runtime snapshot replacement for extended native work

Status: **local implementation, default disabled, not deployed**, 2026-10-14
(Asia/Samarkand). Production remains `a7752dc`. The full four-agent workspace
objective and real-model analytical acceptance remain open.

## User story and boundary

An administrator starts a private MANA analysis from chat. The API saves the exact
Goal, conditions and scoped evidence, the worker continues through typed tools,
and the UI observes progress/results across reconnection and reload. The model
needs the complete authoritative current state, not many copies of every earlier
state. This removes only proven superseded **runtime-owned input snapshots**;
it is not semantic compaction of user conversations or provider reasoning.

`OPERATION_WORKSPACE_SNAPSHOT_REPLACEMENT_ENABLED=false` is explicit configuration.
Capture requires native workspace, report discovery, model continuation and tracked
Goal limits. All dependencies and the new flag must be enabled at creation.
Tracked limits preserve unknown cost holds; no auto-extension is introduced.
The resulting server-owned `snapshot_replacement_enabled` is immutable and is not
an option in `GoalCreate`. Replay/restart never upgrades an older Goal. Turning off
runtime support or losing the continuing-model port stops before generation or
an already-approved external source dispatch.

Private checkpoint **v12** wraps the existing context/limit contracts and binds
the captured bit and exact analysis scope. Continuation **v3** is restricted to
these tracked native catalog Goals. V1/v2 and their old scope digests remain
unchanged. New fields are omitted from older private serialization and the closed
legacy projection; mismatched versions, scope, capture or protocol fail closed.
There is no SQL migration or history rewrite.

## Provenance, not role/JSON heuristics

The runtime records each own snapshot's item position and canonical item SHA-256
in private `RuntimeSnapshotRef` metadata. Only `prepare_continuation` creates those
references, before provider output is appended. The references are observation
metadata, not signatures, source grants, model instructions or user consent.

Both domain/persistence validation and the input adapter recheck the reference's
position/hash; the adapter also checks the exact runtime message shape/content.
A provider-created lookalike, even with the same role and text, is not selected.
Changed/corrupt references stop without another model request. Deleting earlier
runtime items rebinds retained positions, not SQL tool-journal positions.

Replacement requires all of the following:

- Same owner-bound Goal identity, topic, agent, product, original request,
  immutable captured contract and complete quoted session conditions.
- Every prior steering instruction remains an exact prefix of the latest list.
  Frozen historical checkpoint/action facts remain exact; only their existing
  recalculated freshness labels may differ.
- The previous tool-journal prefix is unchanged. If the existing model projection
  shortened/changed an older result, replacement is refused: the earlier snapshot
  is retained rather than silently losing that observation.
- Every previously loaded source remains present with the same binding/timestamps
  and exact text as a prefix of the latest evidence. Source fingerprints, whole-text
  hashes, loaded hashes/offsets and complete quality notes must remain consistent.
  Dropping a report, tail or qualification retains the earlier snapshot.
- The one fixed partial-text warning may disappear only after a complete hash-verified
  read with complete quality notes. Complete text still does not prove full population
  coverage, fresh measurements, confirmed payments or business improvement.

The latest SQL state replaces stale status, current plan/draft, controls, costs and
permissions. Every provider-generated decision, message, tool invocation/output
and opaque reasoning item remains independently in the continuation. No grant or
budget is inherited from a discarded snapshot, old task or historical result.

Provider history is pruned only before the latest **actual server compaction**,
following the [official stateless compaction guidance](https://developers.openai.com/api/docs/guides/compaction#server-side-compaction).
Opaque state is neither inspected nor edited. Compaction rebinds surviving snapshot
positions and drops references only to items already removed by that boundary.
Independent review still starts with one new full authoritative snapshot, excluding
the investigator's opaque reasoning. Pending function results retain their exact
durable SQL position/call and paired provider identifiers; replacement does not
redispatch a tool, lost read or generation.

The bounds are unchanged: 128 window items, configured private-window/current-context
bytes, 400 unique quoted contexts, source-text/page sizes, confirmed steps/budgets
and two classified recovery steps. Retaining a non-superseded snapshot may hit those
bounds and stop. This is not unlimited history or automatic long-session compaction.

## Measured local evidence

Twenty-four new tests cover exact snapshot/provenance replacement, provider
lookalikes, preserved quoted roles/steering, missing tails/notes/sources, changed
tool projections, complete contiguous text, compaction/review, corrupt metadata,
pending tool pairing, old serialization/idempotency, v12 restart/tamper rejection,
runtime/model disablement before requests/reads and required unknown-cost tracking.
The native fake workflow discovers an older verified report behind 22 invalid
bindings, reads all text and reviews the unchanged original objective in ten steps.
It does not evaluate real-model numerical quality.

A pure synthetic fifteen-window comparison, with the same complete source and
original request, produced **14,129 bytes versus 114,290 bytes** in the serialized
continuation. One current runtime snapshot and all fifteen provider decisions
remain. These are actual local serialized byte counts, **not token counts, API
bills or a guaranteed cost/accuracy improvement**. There were no paid calls.

Final `make verify`: **1048 backend / 136 UI**, Ruff lint/format, mypy **335**
tracked source files, TypeScript, production build and zero npm audit vulnerabilities.
Twenty PostgreSQL cases are skipped in the ordinary suite and passed separately
in an isolated PostgreSQL 17 migration round-trip/drift/persistence audit. The
additional v12 case retains exact provenance, cursor, immutable request and unknown
hold across restart and a closed legacy projection. Two live suites remain deselected.
The extra secret scan still reports seven pre-existing synthetic-key flags in older
unchanged SDK tests; its nonzero exit is not called a green security gate.

OpenAPI/TypeScript synchronization passed. The read-only capture flag is optional
in the UI compatibility type, so old API replies remain usable; no new button or
configuration wizard is added. The browser harness explicitly selects the new
contract and avoids forced compaction in that mode, exercising real runtime
replacement with fake model decisions and isolated SQL. Verified boundaries:

- Authenticated same-room handoff, durable progress/reconnection, inline question,
  reviewed result and historical follow-up; reload never reissues the task.
- Full saved text/catalog pages, separately confirmed same-Goal limit grant, lost
  browser reply observation, retained original request and no inherited read grant.
- 110-turn paging and complete conditions from 105 older Goals, scoped synthetic
  Growth action review/receipt, owner isolation, CSRF and mobile accessibility.
- The captured public flag is present but private continuation is withheld. The
  mobile reviewed-result screenshot was inspected. No live browser/customer/model
  or Firebase session was used; no authenticated production acceptance is claimed.

The exact final local image `mana-ai-operation:snapshot-v12-tracked-final-local-20261014`
(`b0a9416420a3e0407cf4e06213b0ba2be5cb3f1d46d5a4cacbd565510100a1a2`)
and actual supported `2ea7b9a` passed networkless read/pause/rollback checks.
Nonempty provenance, private full source including whitespace tail, scope/conditions,
consumed reads, unknown holds and explicit grants survive. Only synthetic SQLite
was mounted, not customer configuration or credentials; neither image was deployed.

Ignored evidence: `output/snapshot-replacement-v12-20261014/`. The first full gate
found the new UI field incorrectly required in old-response fixtures; the optional
compatibility type fixed it before the final green gate. Early local fixture
role/origin/serialization mistakes were corrected, without weakening the runtime
coverage/hash checks or shortening the fixture. Dev-generated `next-env.d.ts` was
restored by the final production build. No production, SSH, keys, source/schedule,
live Firebase/GA4/Manakids/Meta or paid inference changes occurred.

## Release and remaining full-goal work

The current `a7752dc` and earlier native readers cannot execute private v12/v3.
Only the closed `2ea7b9a` fallback is verified here, with native execution disabled
and the established drain/inspect/pause procedure. Retain private state and unknown
holds; never restore an old database backup over newer history. A future scoped
release needs fresh backup/protected-state checks and compatible API/worker/UI.
This checkpoint is outside the prior a7752dc production approval.

This does not turn the stopped [catalog quality attempt](operation-catalog-quality-checkpoint.md)
into a pass or reconcile any historical unknown cost. That attempt remains waiting
with its original receipt and $0.259170 known estimate; it was not resumed/recreated.
Still required: exact-proof removal of duplicate page text within current snapshots/
tool outputs, separately verified input-token preflight if billing/support permits,
an independent full strong-model analysis/review without narrowing the objective,
broader quality coverage, fresh GA4 acceptance, production browser acceptance and
the Retention-first domain action roadmap. The full objective remains active.
