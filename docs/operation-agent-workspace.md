# Agent workspace: Codex/Claude interaction model

## Objective and evidence

Owner request, 2026-10-11: implement the observable working experience of Codex and
Claude agents for MANA administration and its own data. This is not a claim to
reproduce proprietary prompts, identical model accuracy, branding or unrestricted
coding tools. The acceptance target is real task execution through bounded domain
tools, not a chat that merely describes a plan or redirects users between rooms.

Primary sources inspected:

- [Codex App Server](https://developers.openai.com/codex/app-server): threads,
  turns/items, progress events, steering/interrupt, model controls and approvals.
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling):
  model tool requests, application execution/results, strict schemas.
- [Claude agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop):
  context → model → tool → result → next decision, rather than a fixed prompt chain.
- [Claude sessions](https://code.claude.com/docs/en/agent-sdk/sessions) and
  [user input](https://code.claude.com/docs/en/agent-sdk/user-input): continuation,
  human questions and approvals inside a working session.

The established FastAPI/application ports/SQL runtime is retained. A Vercel/eve
rewrite, Codex shell process, Claude subscription login, unrestricted SQL,
filesystem or provider credentials is not needed for the administrative story.

## Full acceptance scope (not completed by documenting it)

1. One conversation entry point: ordinary questions remain cheap conversation;
   analytical requests start durable work without the user choosing a different
   room or knowing the difference between a chat and Goals. Explicit discussion
   and long-lived Goals remain available.
2. A model-driven typed tool loop: discover sources, inspect saved evidence,
   delegate supported source reads, ask a focused question, use results and
   revise the approach. Missing/stale evidence must not produce fabricated facts.
3. Visible, truthful progress/tool statuses and plans, independent review and
   cited final output; no disclosure of private chain-of-thought.
4. In-flight steering, stop/pause/resume/cancel, idempotent controls and retained
   session context/checkpoints across page closure and process replacement.
5. Human approvals inside the conversation. New provider reads and domain writes
   remain separately confirmed; a natural-language "yes" grants no arbitrary
   permission. Only an actual owning-domain executor may perform a mutation.
6. Model/reasoning controls, cost/unknown-hold admission and source-wide cooldown;
   no automatic reissue of a lost read or model call.
7. Grounded MANA sources and measurable analysis. Parent behavior is separate
   from children, tariffs are not payments, user cities are not order cities,
   and 360REC does not receive MANA evidence.
8. Tested browser → API → SQL → tool/provider boundary → model result flows,
   fake/sandbox mutations and bounded opt-in live checks; release/rollback evidence.
9. Durable context management for extended work, including explicit limits and
   preserved user constraints, not silently truncated or invented agreements.

These items define the objective throughout implementation; passing a narrow
component test does not establish feature parity or close the overall goal.

## Architecture

Exactly four top-level rooms remain. The shared workspace is infrastructure,
not a fifth agent or a claim that full Orchestrator/Technical handlers are built.
It may delegate read-only work from the Orchestrator room without moving the user.
Business/financial/contact/infrastructure mutations remain with their owning
domain. Retention risk/action delivery precedes full Orchestrator, Technical last.

Existing private SQL Goals supply queue claims, revision fences, checkpoints,
budgets and recovery. Native model function calls select typed application tools;
the trusted runtime rechecks ownership, product binding, permissions and admission.
Provider payloads are minimized at adapters; tools expose no raw identifiers,
contact lists, child content, GPS, credentials or arbitrary query/URL execution.

Tool calls are persisted before execution. Local saved-data tools are repeatable
but bounded; external reads consume a one-use approval before I/O. Unknown
in-flight outcomes wait for reconciliation rather than being automatically rerun.
Progress is public work evidence, not generated claims that a tool ran.

## Implementation checkpoints

Status must be updated from actual tests/flows, not intent:

- Research and scope: official source comparison and current chat/Goals gap found.
- Typed tools and adaptive durable loop: local implementation; native strict Responses
  functions, scoped saved catalogs/evidence, separately confirmed single-use reads and
  focused questions. No new arbitrary query or domain-write tool.
- Unified conversation dispatch and in-flight steering: local implementation; private
  workspace endpoint, UUID-derived idempotent handoff, preserved bounded user context,
  concurrent steering fences the prior result without issuing a duplicate call.
- Progress, questions/approvals and context continuity UI: local implementation; automatic
  Agent mode, actual persisted tool statuses, inline question choices, unchanged read
  approval, pause/resume/cancel and reload continuity. Public task/plan/tool progress now uses
  a private SQL journal and authenticated SSE with cursor replay and REST reconciliation;
  it does not stream model tokens or internal reasoning.
- Version-safe checkpoint storage: local implementation; additive migration `c75f0a6e812b`,
  versioned native checkpoints/queue status separate from strict legacy Goal JSON. Older
  workers see only a closed projection; native controls/context remain in the new checkpoint.
  Explicit rollback preparation pauses native work without refunding unknown costs or
  repeating reads. No production migration was performed.
- Completed-analysis continuation: local implementation; frozen topic/owner/product-scoped
  session memory is reconstructed from SQL before a turn starts. Prior user constraints remain
  complete; up to three public result excerpts retain source IDs, dates and explicit shortening.
  A follow-up explanation does not start another Goal or source read. The next task inherits
  context, not prior evidence authority, costs or approvals. Additive chat metadata migration
  `d86a1b9f023c` keeps the supported old chat reader compatible as well as the Goal reader.
- Full quality, source integration acceptance and production release: pending.

### Discussion-only screenshot and admission fix, 2026-10-12

The owner supplied an Orchestrator response to "Как можно поднять конверсию. Изучи текущие
данные": no saved reports in that chat, domain handlers planned, and a suggestion to move to
Growth. This matches the legacy discussion instructions, not evidence that the native
workspace inspected the database. The last recorded production release is still the separate
discussion/Goals version; native workspace activation is not claimed by local commits.

- Native availability is checked independently for chat and Goals. When either service
  advertises the native workspace, auto mode never silently sends to discussion while the
  other check is pending, failed, disabled or mismatched. The draft is preserved and no
  message/admission POST is issued. A manual availability retry performs GETs only; sending
  afterwards still requires an explicit submit. Users may explicitly select discussion.
- Older deployments with no native flag retain normal chat compatibility. Technical rooms
  and viewers do not gain native execution. No source settings or feature defaults change.
- A lost handoff response triggers a scoped Goals GET, never a message retry. A task that
  was already created becomes visible in the same topic and takes over the composer for
  steering. The user's draft is retained; no second task/model/source request is inferred.
- Legacy discussion receives an explicit server-owned indication that ordinary shared Goals
  are configured. Its instructions distinguish planned Orchestrator domain mutations from
  same-room read-only analysis: recommend selecting "Цель", not moving to Growth solely
  because the initial conversation has no saved reports. Discussion itself starts no task.
- The native path remains automatic and preserves the original request. Its existing HTTP
  regression exercises the exact conversion request through scoped source discovery,
  saved evidence, investigation, independent review and idempotent replay.

Production activation, real-source acceptance, conversational action lifecycle and extended
context acceptance remain separate unfinished parts of the full objective. This fix does not
claim that paid conversion evidence exists or that an analysis improved conversion.

Local checkpoint evidence: `make verify` passed with 733 backend tests, 110 UI tests,
Python/TypeScript checks, lint/formatting, production UI build and zero dependency audit
vulnerabilities. Six PostgreSQL tests remain separately opt-in and two live suites were
excluded; no schema change was made in this fix. OpenAPI/client synchronization,
secret/quality-marker scans and compose validation passed. Dedicated prompt-grounding and
bounded-evaluation tests passed (125 tests); the discussion instructions remain within the
existing 8192-byte ceiling and no evaluation budget was increased. Native and legacy browser
flows passed with actual local HTTP/SQL persistence and fake models/providers, including
same-room handoff, progress, inline clarification, reload, owner isolation and accessibility.
No paid OpenAI or live Firebase/GA4/Manakids/Meta request was issued and production was not
modified. These checks establish the local flow, not production activation or live model quality.

### Local evidence, 2026-10-11 (not a production claim)

- Initial `make verify`: 688 backend tests passed, 6 PostgreSQL tests skipped,
  2 opt-in live tests excluded; 95 UI tests passed; build and dependency audit passed.
  Later changes require a final rerun before handoff.
- Second `make verify`: 692 backend and 95 UI tests, build, audit and type/lint gates passed.
  PostgreSQL 17 audit: six tests passed, including native tool recovery and in-flight steering.
  Legacy browser flow and the updated agent mobile flow passed. Later model transport fixes
  still require a final regression run.
- Final local checkpoint `make verify`: 698 backend tests passed, six PostgreSQL tests
  skipped in the ordinary suite/two opt-in live tests excluded; 96 UI tests, build and
  dependency audit passed. Separate PostgreSQL 17 migration/claim/recovery audit: six passed.
  Contract sync, secret/quality-marker scans and `git diff --check` passed. The feature is
  still unreleased, not a claim that every full acceptance item is satisfied.
- Focused HTTP/SQL/tool/model tests cover automatic analysis from the Orchestrator room,
  no paid calls for greetings/disabled execution, owner/RBAC isolation, no cross-app evidence,
  retained constraints, in-flight steering/paused steering, strict native arguments and
  actual usage accounting. Source/model boundaries are fakes, not quality proof for live LLMs.
- `AUDIT_AGENT_WORKSPACE=true scripts/browser_e2e.sh` passed after fixing the harness's
  initial room and revealing/reaching clarification choices on a narrow viewport:
  automatic handoff → three model-selected saved-data/question tools → inline answer →
  independent review → result → reload → owner isolation. Desktop/mobile WCAG checks passed.
  Screenshots are ignored local artifacts in `output/agent-workspace-20261011/`.
- No production, Firebase/GA4, IAM, SSH, audio or independent API configuration was changed.
  The feature flag remains false by default.
- Live synthetic evaluation initially exposed SDK JSON parsing before native function handling.
  Three independently stopped diagnostics retain $0.210323 in unknown conservative holds;
  they were not automatically retried/refunded. A fourth classified parse failure recorded
  $0.002322 in verified usage after the raw HTTP accounting fix. A non-generating model lookup
  confirmed access. No raw response text, keys or headers were exposed in diagnostics.
- After separating native tools from structured decision bodies and handling functions before
  commentary parsing, the real `gpt-6.1-sol` workflow completed in five steps: inspect sources →
  read saved evidence → plan → investigate → review. Default 4096 output-token configuration,
  no source reads, five model calls, 13528 input/4814 output tokens, verified usage $0.068985.
  Manual output review confirmed D1=60%, D7=35%, previous D7=30%, +5 percentage points;
  parents/children, tariffs/payments and cohort vs causality limitations were kept separate.
  This is one synthetic workflow, not proof of production source completeness/model quality.
- All nine generation attempts across diagnostics/evaluation: verified accounted usage
  $0.071307 plus unknown holds $0.210323 = $0.281630 conservative total, not a billing invoice.
  Day/month totals describe the same spend and must not be added together. No Firebase, GA4,
  Manakids or production requests were issued. No further paid party is pending.

### Native checkpoint/rollback evidence, 2026-10-12

- Focused persistence tests verify all six Goal states, legacy/new queue isolation, capacity,
  ownership/idempotency/revision fences, complete context/tool reconstruction after restart,
  read-only rollback inspection, all-or-nothing refusal while a live lease remains and
  retained consumed reads/unknown costs on explicit pause.
- An isolated legacy-row migration test verifies that `c75f0a6e812b` does not rewrite
  historical JSON. Schema downgrade is refused once any native history exists, including
  completed Goals. New ordinary Goals keep nullable workspace fields empty.
- `bash scripts/operation_workspace_compatibility_audit.sh` passed using the actual locally
  installed `mana-ai-operation:2ea7b9a` image with `--network none` and a synthetic SQLite DB.
  Its strict models read native compatibility projections, all five old control commands
  are denied, old workers claim only ordinary Goals, and the new code reconstructs the
  original context/approvals/tools/budget unchanged. Explicit pause then preserves history,
  revokes unconsumed approvals and marks lost source work unknown; neither version retries it.
- Supported application rollback retains the additive schema; do not invoke an old Alembic
  migration or downgrade/drop the metadata columns. See the bounded
  [release/rollback procedure](operation-agent-workspace-release.md).
- Final `make verify` after metadata/recovery changes: 708 backend tests passed, six
  PostgreSQL tests skipped in the ordinary suite/two opt-in live tests excluded; 96 UI tests,
  build, formatting, lint, typecheck and dependency audit passed. Separate PostgreSQL 17
  additive migration/concurrency/recovery round trip: six passed. Contract/security scans
  and native/legacy browser E2E with the actual new SQL storage passed. Mobile native
  screenshots were inspected; the normal legacy flow still covers sandbox approval/action
  execution and manual Parent cooldown without live provider requests.
- The new local `mana-ai-operation:workspace-local-20261012` image built successfully.
  A two-image, networkless compatibility audit passed: old-image control/claim protection
  plus new-image checkpoint reconstruction before/after explicit rollback preparation.
  This is a local runtime check, not an image publication or production deployment.

### Completed-analysis continuation checkpoint, 2026-10-12

- A completed/cancelled Goal's public result now enters the next conversation as historical
  context. Its source IDs, collection/expiry dates, quality limitations and shortening flag
  remain explicit. Source freshness is recalculated for each model request without mutating
  the saved snapshot. Historical context never substitutes for current cited Goal evidence.
- Memory is reconstructed only from SQL owned by the same user/topic/product and frozen
  before generation. At most three result excerpts (2000 characters each), the newest 100
  closed Goals and 400 exactly deduplicated user-context records are supported. Omitted older
  checkpoints are counted; result excerpts may shorten further for the model with a marker.
  User constraints are never abbreviated. Oversized context fails before a paid model call,
  preserving the complete SQL messages/results. This is bounded continuation, not unlimited
  context compaction or automatic recovery of arbitrarily old agreements.
- Handoff copies the original chat snapshot, including an empty snapshot, rather than
  reconstructing it after the turn. New tasks start with zero spent steps/cost and no inherited
  evidence or source approvals. Idempotent lookup works beyond the 100-Goal history page;
  replay does not generate another response or rebuild memory from later conversations.
- A previously missing rollback check was found: the actual old chat reader merges legacy
  `context_metadata`, so native fields in that column were incompatible. New additive migration
  `d86a1b9f023c` isolates those fields. Goal memory uses checkpoint protocol 2; protocol/scope
  mismatches fail closed. Both chat-only and Goal-only histories prevent destructive downgrade.
- Local browser → real API/SQL → fake model flows passed: finish/review a Goal, explain its
  result using the retained period/source, reload without a duplicate Goal, and keep other
  administrators isolated. The legacy browser flow also passed; PostgreSQL 17 migration
  upgrade/downgrade/upgrade, drift and six concurrency/recovery tests passed. No production
  source, Firebase/GA4 or paid OpenAI call was used for this checkpoint.
- Final `make verify`: 723 backend tests passed, six PostgreSQL tests skipped in the ordinary
  suite/two live suites excluded; 96 UI tests passed, with successful formatting, lint,
  Python/TypeScript checks, UI build and zero high-level dependency-audit findings. Separate
  SQLite migration/drift, synchronized OpenAPI/client, secret/quality-marker and compose
  configuration checks passed. The native browser continuation flow was repeated after the
  final scope/quality guards; its cleanup was followed by a successful production UI build.
- The standard local runtime build completed. A networkless source-overlay candidate,
  `mana-ai-operation:session-final-local-20261012` (`a3da4e584703`), uses that image's installed
  dependencies and the exact final application/migration/rollback-script sources. The two-image
  compatibility audit passed against the actual old `2ea7b9a` image and this candidate, including
  strict chat/Goal reads, old command/claim protection, complete current-memory reconstruction
  and explicit-pause recovery. No image was published or deployed.

### Durable public progress checkpoint, 2026-10-12

- Additive migration `e97b2c0a134d` journals successful Goal changes atomically. All Goal
  create/claim/control/save/recovery writes share a transaction fence, so a later committed
  event cannot move the cursor past an earlier uncommitted event. Rejected optimistic writes
  and idempotent command/request replay do not publish duplicates. Pages contain at most 50
  events; the global SQL cursor is an ordering token, not a product/user metric.
- GET `/api/v1/admin/operation/workspace/topics/{topic_id}/events` and `/stream` verify
  owner access before returning history. SSE rechecks existing authentication/role during
  delivery. Periodic cookie-session checks use a read-only identity lookup, avoiding a
  `last_seen_at` SQL write on every heartbeat; ordinary request/login behavior is unchanged.
  Event payloads contain public status, phase, bounded plan/message and typed tool
  names/statuses; no tool arguments/results, session memory, credentials, internal reasoning
  or read/action grants. A bounded ASGI response also cancels blocked network sends.
- Default stream lifetime is 45 seconds with 10-second heartbeats and one-second local SQL
  polling. `OPERATION_WORKSPACE_EVENTS_ENABLED=true` is gated by the default-false native
  workspace flag. Polling is configurable from 0.5–10 seconds, lifetime from 15–120 seconds,
  and connections from 1–128 (default 32 per API process, maximum 3 per owner/process).
  This is not a distributed global connection limit. The observer makes no provider calls.
- Browser subscriptions are cleaned up on topic/owner navigation; cursors are scoped to both
  in session storage. Only complete validated frames advance the cursor. Duplicate/cut frames,
  revoked access, restored-database cursors and incompatible responses are handled explicitly.
  A 25-second inactivity watchdog aborts only observation, with bounded jittered reconnect
  delay. Controls still use current REST state/revision, not stream metadata. Executing Goals
  reconcile every 15 seconds while connected, or 2 seconds on fallback; waiting/paused Goals
  reconcile every 15 seconds. Terminal cards do not keep an idle subscription open.
- Workspace routing now uses the same `OPERATION_CHAT_BASE_URL` as chat/Goals. Previously
  this namespace fell through to the independent main API in split-backend deployments.
  No production routing, source bindings, schedules, credentials or audio API were changed.
- Local verification includes SQL paging/replay/atomic rollback, ownership/role checks,
  connection expiry/backpressure, browser parser/reconnect/watchdog and distinct backend-target
  routing. PostgreSQL 17 upgrade/downgrade/upgrade and drift checks plus six integration tests
  passed; the Goal test now checks the actual shared event journal across two connections.
  Native browser → API → SQL → authenticated stream → UI delivery/reconnection passed:
  task ID/revision/tool IDs/cost/steps were unchanged across reconnection, followed by an
  inline clarification, reviewed result, historical continuation, reload and owner isolation.
- Final `make verify` passed: 731 backend tests, 104 UI tests, Python/TypeScript checks,
  formatting/lint, production UI build and zero dependency-audit vulnerabilities. Six
  PostgreSQL tests passed separately after the final auth changes. SQLite clean round trip,
  populated-copy upgrade/drift, OpenAPI/client synchronization, secret/quality-marker scan
  and compose configuration checks passed. Native and legacy real-browser flows were rerun
  after the final read-only auth recheck and REST-fallback changes, including accessibility.
- Final networkless source-overlay image `mana-ai-operation:stream-final-local-20261012`
  (`c3a7508dc1ba`) uses the previous verified local runtime's installed dependencies and
  the exact current application/migration/rollback-script source. The two-image compatibility
  audit passed with the actual old `2ea7b9a` image and this candidate, retaining the event
  journal and complete native context before/after explicit pause. No image was published,
  production migration performed, source/schedule activated or paid provider request made.
  This checkpoint does not establish production readiness or full Codex/Claude parity.

### Remaining full-goal work

Do not mark the overall Codex/Claude interaction objective complete from this checkpoint:

- Repeat regression, PostgreSQL concurrency/recovery, contract/security and browser checks
  after subsequent changes; the current local checkpoint's final gates passed as listed above.
- Extend real-model quality coverage beyond the single synthetic evaluation, then separately
  verify approved configured sources without a scan or new schedule.
- Expand user-visible durable streaming/continuation and extended-context behavior with
  explicit interruption/reconnection semantics; durable public progress is not token streaming.
  Completed results now enter ordinary conversation as bounded historical checkpoints, not
  fresh evidence. Very long user-context histories still fail closed at an explicit byte/count
  limit without calling the model; scalable retrieval/compaction of extended sessions remains.
- Integrate supported action proposals/owning-domain execution into the conversational
  work lifecycle without claiming unbuilt Retention/Orchestrator/Technical capabilities.
- Produce a scoped sidecar/UI release and rollback, keep the independent main API/audio and
  scheduler/source settings unchanged, and inspect the actual deployed browser/API behavior.
- Repeat the scoped release/rollback checks against the actual deployment configuration;
  the local older-image proof is not a production acceptance test or permission to downgrade
  the schema. Confirm paused native Goals stay paused after rolling forward.
