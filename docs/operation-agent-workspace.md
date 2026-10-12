# Agent workspace: Codex/Claude interaction model

## Objective and evidence

Latest status: the scoped native workspace release is deployed, with bounded production
checks recorded in [the release report](operation-agent-workspace-production-release.md).
Earlier checkpoints below are historical; they do not override that report or establish
complete Codex/Claude parity, current-source coverage or unbuilt business actions.

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
  Goal progress is distinct from the separately opt-in ordinary-answer text stream described
  below. Neither exposes internal reasoning.
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

### Scoped human action review, 2026-10-12

Local implementation, not released: native MANA Growth/Orchestrator conversation turns can
request a bounded review of existing Growth sandbox experiment proposals. The shared lane
delegates only to the owning Growth lifecycle; it does not register a full Orchestrator or
add write tools to analysis Goals. Human role, topic ownership, typed parameters, exact
fingerprint, expiry, fresh scoped synthetic evidence, self-approval, policy and kill switches
are checked. A SQL intent is saved before dispatch; replay only observes the existing result.
Lost provider/SQL/browser replies never automatically cause another workspace execution.

The receipt and actual domain execution/verification remain visible after reload and enter
the next turn's private minimized session memory. The next Goal inherits historical context,
not approval authority. Checkpoint version 3 isolates action memory from old strict JSON.
Sandbox drafts do not affect real users/payments; conversion impact remains `not_measured`.
Unverified legacy proposals are read-only in chat; their professional queue remains separate.
Live experiments, Retention actions, full domain Orchestrator and production activation remain
outside this checkpoint. Synthetic payment funnel fixtures are never admitted as real Goal
evidence. Fresh evidence admission and the retained unknown-cost/read protections are unchanged.

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

### Scoped action-review acceptance checkpoint, 2026-10-12

- `make verify` passed after the final immutable target-object guard: **746 backend tests**,
  seven PostgreSQL opt-in skips, two live-source opt-in exclusions; **113 UI tests**;
  Ruff, mypy (295 files), TypeScript, production Next build and npm audit: zero vulnerabilities.
- Separate isolated PostgreSQL 17 audit: upgrade/downgrade/upgrade/drift passed; seven tests
  passed, including 12 concurrent confirmations through independent SQL connections with
  exactly one sandbox provider dispatch. SQLite clean round-trip/populated-copy/drift passed.
- Real private-browser native and legacy flows passed. Native flow checks the existing
  typed Growth executor, human dialog, CSRF denial, actual SQL verification, injected lost
  browser reply with one POST only, receipt reload and same-room historical continuation.
  Keyboard/dialog focus, 320px layout and WCAG automated checks passed; decisions are scrolled
  inside the transcript instead of clicked through the composer. Screenshots are ignored
  local artifacts in `output/workspace-actions-final-20261012/`.
- HTTP/SQL negative tests cover wrong owner/product/role, self-approval, stale or unverified
  evidence, changed fingerprint/target, disabled lane, kill switch, concurrent replay,
  lost domain reply and lost receipt acknowledgement. Settled action context survives normal
  snapshot cleanup. Invalid v2/v3/action-product context fails closed without private contents.
- Final networkless source-overlay image `mana-ai-operation:actions-final-local-20261012`
  (`2bf355f298db`) built; its actual runtime startup and typed routes passed a networkless
  temporary-SQL smoke check. Two-image rollback probe passed with the actual supported old
  `mana-ai-operation:2ea7b9a` and this candidate, preserving native v3 memory, event journal,
  pause state and unknown reservations. OpenAPI/client, secret/quality-marker and compose
  checks passed. No image was published or production/source/schedule changed; no paid
  model or Firebase/GA4 request was made in this checkpoint. Fake lifecycle coverage is not
  evidence of live financial/customer-contact readiness or improved conversion.

### Saved-data/model acceptance and historical scope, 2026-10-12

Status: reviewed local progress, **not deployed**. Read-only production inspection confirmed
operation sidecar/scheduler image `2ea7b9a`, UI `a871ddf` and schema `b64e9c2f703d`; main
API/audio remains separate. The screenshot's discussion-only behavior is therefore still
expected on that deployment. Existing SSH password authentication worked; no auth setting,
source binding, schedule, permission, key or production data was changed.

A transaction explicitly marked `READ ONLY` exported just the latest already-minimized,
owner-confirmed MANA Parent summary. No user records or source provider were requested.
The saved first-page sample contains 10 parents and is dated 2026-10-09; its freshness is
unknown, not current. Existing engagement bindings/GA4 stream IDs remain unverified/empty.
This confirms that one authorized saved source can be consumed, not that the full conversion,
payment or mobile-analytics source plan is accepted.

Real GPT-6.1 Sol/medium, native-tool checks used isolated local SQL and a saved-only adapter
whose collection method refuses all calls. No scheduler/API lifespan was started for paid QA:

| Check | Observed path and outcome | Calls | Metered estimate |
| --- | --- | --- | --- |
| Original current-conversion request | Inspect → saved Parent report → plan → investigation → review; useful partial output, `waiting` for cohort/payment evidence; no fabricated conversion or room redirect | 5 | $0.061109 |
| Historical-sample request before explicit scope | Correct historical facts/limitations and completed review; current-only completion gate refused closure, exposing the scope gap | 5 | $0.064731 |
| 360REC conversion | Scoped inspection found no eligible report; retained a conditional next step, `waiting`; no MANA evidence or claimed database emptiness | 4 | $0.045934 |
| New explicit `saved_snapshot` request | Inspect → same dated saved report → plan → investigation → review; historical report `completed`, no claimed current retention/payments | 5 | $0.068500 |

Total **19 settled OpenAI calls, $0.240274 estimated usage**, zero unknown holds and zero
Firebase/GA4/Manakids/Meta requests or production mutations. Original party cap was $0.49;
the separately guarded explicit-scope check cap was $0.20. The original party was neither
resumed nor retried. Rates matched the inspected [standard short-context pricing](https://developers.openai.com/api/docs/pricing);
this is not an invoice, accuracy statistic or proof of business improvement. Minimized outputs
and persistent ledgers remain ignored local artifacts in `output/workspace-release-20261012/`.

The correction adds typed `analysis_scope=current` (default) / `saved_snapshot` (explicit
native Goal choice). Historical scope cannot request/approve a live read; current objectives
never silently acquire that narrower contract. Both require same-product, nonempty, dated,
unshortened cited evidence, a done plan and review. Future/undated/empty/cross-product facts
are rejected. The UI reveals one selector only in explicit Goal mode, preserves the choice
when native availability fails, and labels historical results after reload. This follows the
React review's minimal conditional controls/accessibility and retained SWR/auth boundaries.

Historical requests use checkpoint v4; default requests retain prior native versions and old
strict request JSON. V4/scope mismatches fail controlled; supported old code sees only a closed
projection. No new migration or rewriting of saved Goals is required. A networkless two-image
rollback audit passed with actual `2ea7b9a` and the new local runtime, including retained action
memory, explicit pause and unknown-read protection. Local real-browser flow now also creates,
clarifies, finishes and reloads an explicitly historical Goal; 320px and accessibility passed.

Final code checkpoint `make verify`: **757 backend tests**, seven PostgreSQL skips in that
command/two live suites excluded; **116 UI tests**, lint/format, mypy 296 files, TypeScript,
Next production build and zero npm audit vulnerabilities. Isolated PostgreSQL 17 migration
round trip/drift and seven concurrency/recovery cases passed separately. Contract sync,
secret scan and whitespace checks passed. Native browser audit passed with the new historical
choice and existing action/SSE/owner/CSRF checks. Visual mobile review also found that reload
left a closed result below the viewport; opening a topic now scrolls once after saved chat/Goals
resolve, without moving the reader on typing/background updates or making a provider call.
These are local acceptance results.

Scoped production release approval has been requested; activation/backup/migration/public
authenticated browser checks and actual-deployment rollback remain pending. Chrome's advertised
local port returned 404 for CDP endpoints and could not attach; public frontend HTTP was 200.
No production browser session was fabricated and no authenticated deployed-browser success
is claimed. The production scheduler/main API/audio were not recreated.

Publication of implementation checkpoint `e33ff82` was attempted without force to the existing
`feat/operation-admin-20260929` branch. GitHub returned 403 for `samanwirst`; authenticated
repository metadata confirms `pull=true`, `push=false`. The remote ref remains `2da1705`.
No permission, account or branch history was changed. Repository write access (or an authorized
maintainer publishing the retained commits) and scoped production approval are still needed;
do not claim that these local checkpoints were pushed or deployed.

### Private saved-task recall checkpoint, 2026-10-12

Local/unreleased. Official research revisited [Codex stored-thread paging](https://learn.chatgpt.com/docs/app-server#threads),
[Responses compaction](https://developers.openai.com/api/docs/guides/compaction) and
[Claude session resume](https://code.claude.com/docs/en/agent-sdk/sessions). Full persisted
history and model-visible context are distinct. OpenAI compaction returns opaque state, not
an auditable lossless replacement for our explicit user constraints; this checkpoint does
not add that provider call or claim native compaction is complete. The established Python/SQL
stack stays unchanged rather than installing a TypeScript AI SDK or rewriting it as eve.

- Typed `find_saved_tasks` returns at most five closed task references, with literal objective
  substring search, stable date/ID ordering and a bounded cursor. `read_saved_task` returns a
  result page up to 4000 characters, with exact offset/next_offset, total length, shortening,
  observation references and a historical-only marker. SQLite `instr`/PostgreSQL `strpos`
  provide equivalent literal/case-sensitive substring semantics, including `%`/`_`/Unicode.
- Both tools require the current owner/topic/product and a task closed before the current
  Goal began; foreign/future/active references and cursors are refused. They read SQL only,
  add no evidence/grant/cost history and never invoke a provider. Original saved reports may
  now be looked up by exact ID beyond the first 20 catalog entries, with the same loaded
  agent/product verification and freshness/completeness checks. Unverified fake Growth facts
  remain inadmissible. History-only text cannot satisfy the evidence completion gate.
- Full task-result pages remain in the durable journal/model context, not shortened like
  obsolete catalogs. Exact cross-role text dedup removes redundant copies while retaining
  every word and all `also_kinds` roles. The regression reconstructs 100 chat messages and
  100 matching closed Goals: 500 role-labelled copies become 100 exact quotes, with every
  objective/criterion/constraint/instruction label retained. No semantic discard, cap increase
  or automatic forgetting is used; byte/400-unique-quote guards still fail before a paid call.
- Extended task tools/role labels use checkpoint v5 with explicit frozen analysis scope.
  Protocol/scope/alias mismatches fail closed; legacy JSON stays strict-compatible. The
  actual old `2ea7b9a` and networkless new runtime rollback/pause probe passed, retaining
  aliases, action history, original scope and unknown reservations. No migration is added.
- Real Sol/medium local check used one already-minimized saved MANA Parent report and a
  private local copy of the prior QA analysis, with four newer synthetic distractor tasks.
  The model autonomously planned, searched, read offsets 0/4000, revalidated the original
  report, investigated and reviewed: **seven settled calls, $0.079756**, zero unknown holds
  under a $0.49 cap. Manual review confirmed exact task/report/date citations, sample limits,
  no tariff/payment or child/parent conflation, and D7 described as a proposed measurement,
  with undefined window boundaries explicitly retained. No source/production requests or
  writes. This is one narrow quality example, not statistical/full-goal acceptance.
- Real private-browser fake-model flow adds same-room historical task search/read/report
  revalidation, completed result/reload, private-owner isolation and existing action/SSE/CSRF/
  mobile accessibility checks. New tool names are accepted by the bounded SSE validator;
  arguments/results remain out of the public stream. No extra default interface control.

Final local gates: `make verify` passed with **767 backend tests**, eight isolated PostgreSQL
skips here/two live suites excluded; **118 UI tests**, mypy 297 files, lint/format, TypeScript,
Next production build and zero npm vulnerabilities. Separate PostgreSQL 17 round-trip/drift
and **eight** cases passed, including actual JSON/literal search/cursor/scope queries. Native
browser/API/SQL recall/reload and old/new image pause/rollback passed. Runtime startup and
typed scoped SQL tool lookup passed in a networkless temporary-DB container; schema sync,
secret scan and whitespace checks passed. Artifacts are ignored under `output/task-recall-20261012/`
and `/tmp/manaai-history-*`; no image was published or production state changed.

The 100-message per-topic cap was also found in the actual repository; paged transcript
delivery, safe automatic compaction/retrieval for longer sessions and its exact-constraint
contract remain required. This checkpoint does not close that gap or the full objective.
No push/deployment was retried: the recorded GitHub write-access and scoped-release approval
blockers remain. The independent API/audio, SSH, source settings/schedules and keys are untouched.

### Long-topic transcript checkpoint, 2026-10-12

Native workspace history now uses owner/topic-bound cursor pages at
`GET /workspace/topics/{topic_id}/messages` (default 20, maximum 30). Opening a
page performs SQL reads only: no expiration rewrite, provider call, new Goal,
source read, consent grant or cost settlement. Queries project public fields
without loading repeated private `session_memory`; the compatibility detail
window also projects only the latest 100 turns. An additive composite SQL index
(`a36d9f7b802c`) supports owner/topic/time/UUID keyset ordering, including timestamp ties.
The new UI requires the advertised paged API, rejects foreign-topic pages and
does not silently switch to legacy history on a failed page. Older deployments
without the advertisement keep their existing reader. Earlier messages load on
upward scroll with position preservation; a small earlier-history control is
available only when more messages exist. Reload starts at the latest 20 turns.
Client cache keys include the authenticated owner, and cursor requests stay in
the selected topic.

`OPERATION_WORKSPACE_TRANSCRIPT_ENABLED=true` is gated by the still-opt-in
`OPERATION_AGENT_WORKSPACE_ENABLED`. When both are enabled,
`OPERATION_WORKSPACE_TOPIC_MESSAGE_LIMIT=1000` replaces the old 100-turn admission
cap; allowed explicit capacity is 100–10000. Legacy/disabled-pagination paths
retain 100, and shared hourly/daily/model/source budgets are unchanged. Addressed
replay, stop, analysis status and action reviews use exact owned-turn lookup,
not a search in a truncated display window. Recent dialogue is the last six
completed turns with an exact older-turn count; original user messages stream
from SQL into frozen context regardless of transcript pagination. Existing
exact deduplication/400-unique-quote/byte guards still apply before a paid call.
This is not semantic compaction, unlimited model context or permission to forget
early user constraints. Native automatic compaction/retrieval remains unfinished.

Final local gates: `make verify` passed with **772 backend tests** (nine PostgreSQL
skips here, two live suites excluded), **122 UI tests**, mypy 299 files, Python/TS
checks, lint/format, Next production build and zero npm vulnerabilities. PostgreSQL
17 migration round-trip/drift and **nine** integration cases passed separately.
Native private-browser verification covered all 110 synthetic turns, anchored
upward paging, zero history POSTs, the 111th reply with the original condition,
111 unique rendered turns after head refresh and latest-page reload; legacy
browser/Goals/approvals and WCAG checks also passed. Networkless current runtime
HTTP/SQL smoke, actual `2ea7b9a`/new-image rollback/pause, standalone UI smoke,
bundle/secret scan, OpenAPI synchronization and whitespace checks passed.
Earlier harness failures (incorrect bootstrap-owner fixture, repeated browser
global declarations and shared-test active admission) were fixed and the full
relevant checks repeated. No paid model or external data request was made: test
provider/source cost **$0**. Logs live under `/tmp/manaai-transcript-*`, ignored
screenshots under `output/transcript-20261012/`; runtime image
`mana-ai-operation:transcript-local-20261012` is local/unpublished only.

This checkpoint is local only. Production activation, GitHub publication,
deployed private-browser acceptance and the other full-goal obligations remain
open; no Firebase/GA4 reads, new schedules, independent API/audio changes, SSH
changes or credential edits are part of it.

### Native model continuation checkpoint, 2026-10-12

The opt-in Goal model now implements actual stateless Responses item chaining and
server-side compaction, not a model-written summary pretending to be compaction.
The implementation follows the [official compaction guide](https://developers.openai.com/api/docs/guides/compaction):
`store=false`, encrypted reasoning included, a server compaction threshold, and
pruning only items before the latest **server-side** compaction item. The standalone
`/compact` endpoint is not used and its canonical output must not be pruned.

Private continuation is a typed application-port result, scoped by owner,
goal/topic/agent/product, unchanged request and all original quoted conditions.
The adapter validates/materializes supported SDK item types, rejects system/developer
authority, raw reasoning, unknown functions, duplicate/missing tool acknowledgements,
unsettled tool records and oversized windows. A pending function receives its actual
SQL receipt, including denial/unknown status, before another model decision; it is
never executed from a saved opaque item. Every new window reasserts the full current
conditions, steering, evidence and permission snapshot. Review starts fresh without
the investigator's opaque reasoning. Compaction is not an evidence or read grant.

Checkpoint v6 isolates continuation/recovery fields from strict legacy JSON. The
payload and scope digests are checked on reload; older workers cannot claim it.
Goal list/detail/control/create and workspace handoff responses strip provider
continuation, and public events expose only a truthful compaction progress note.
No ciphertext or raw model reasoning reaches the UI. Controls/CAS still win a
model-result race; missing/changed/disabled continuation never silently invokes
the legacy model path. Original byte/400-unique-quote guards remain: this does not
solve arbitrarily large original user-condition histories or imply unlimited context.

Local configuration, disabled by default and gated by the native workspace:

- `OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED=false`;
- `OPERATION_WORKSPACE_COMPACT_THRESHOLD=8000`;
- `OPERATION_WORKSPACE_MODEL_WINDOW_BYTES=192000`;
- `OPERATION_WORKSPACE_MODEL_MAX_OUTPUT_TOKENS=8192` (legacy calls remain 4096).

Reservations include the actual private window and native output allowance before
I/O. Goal/day/month monetary limits are unchanged; verified usage settles normally,
unknown usage stays reserved, and lost source/response I/O never retries automatically.
Known invalid evidence citations now receive at most two **new bounded reasoning
steps** with typed feedback. The invalid draft is not published, IDs are not silently
dropped or admitted as evidence, and no source consent is inferred. Successful saved
report loading clears obsolete feedback. Repeated invalid output stops truthfully.

Real-model QA revealed both a catalog-only citation mistake and known incomplete
output at the old 4096-token allowance. These were not hidden as successful analyses:
the citation gate stopped the draft, verified costs were retained, and the same
local ledger/unchanged objective was continued after targeted fixes. Native output
allocation is now separate, explicitly configured and conservatively reserved.
No production, Firebase/GA4/Manakids request, source scan, new schedule or domain
mutation is part of this checkpoint; real-model evaluation uses only a previously
minimized saved MANA Parent report. Publication/deployed acceptance and the full
objective remain unfinished.

Real-model result (same local ledger, no repeat party): **8 requests, 8 server
compactions, $0.261311 settled, zero unknown holds**, completed historical Goal.
The first citation error and two known output-limit failures are included in that
total, not omitted from the evaluation. Exact report loading succeeded after bounded
feedback; the final plan/investigation/fresh review completed after the native
output allowance was corrected. No source/domain/production requests occurred.
This is one inspected quality case, not statistical model-quality or full-goal proof.

Manual data-quality/analysis validation: the final result cites the original report
ID and `2026-10-09T17:06:18.388488Z`; counts 208985 (API count), 10 (sample), 3/7
(tariff present/absent), 9/6 (parents with child/connected-child relationships) match
the minimized saved source. It keeps the historical/unknown-freshness caveat,
nonrandom-page limitation, parent/child distinction and tariff/purchase-date versus
payment distinction. It does not compute actual retention/conversion/churn or causal
improvement. Proposed D7 is explicitly a future parent-only measurement, UTC
`[t0+168h, t0+192h)`, mature common denominator, deduplication, undefined empty
denominator, and boundary checks. No event/KPI availability is invented.
Confidence: usable **with the stated caveats** for this historical-summary QA only.
Underlying raw-key uniqueness, full-population coverage/current state and behavioural
cohorts cannot be independently verified from a minimized ten-parent aggregate.
The engineering artifact is `output/continuation-20261012/model-quality/step-8.json`;
the source is `output/workspace-release-20261012/saved-parent-report.json`, and the
budget/attempt markers remain in the same ignored evaluation directory. Neither
opaque context nor an API key is written into exported step JSON.

Final local verification: `make verify` passed with **780 backend tests** (ten
PostgreSQL skips in that run/two live suites excluded), **122 UI tests**, mypy
303 files, lint/format, TypeScript, production UI build and zero npm vulnerabilities.
Separate PostgreSQL 17 migration/drift and **ten** cases passed, including v6
continuation persistence, owner isolation and pause. The actual native browser
flow ran with continuation enabled and fake Responses windows, covering inline
questions, receipt chaining, reload, source/action consent, task recall, 110-turn
history and WCAG checks. Actual old `2ea7b9a`/new-image pause/rollback retained v6
opaque state, original scope/action aliases and unknown source holds. Networkless
runtime HTTP/SQL, schema sync, standalone UI/bundle/secret and whitespace checks
passed. Local image `mana-ai-operation:continuation-local-20261012` is unpublished;
no production switch, key, source setting or scheduler was changed. GitHub write
permission still reports `push=false`, and scoped backend/worker release approval
is outstanding. Full native activation/deployed acceptance is not claimed.

### Durable ordinary-answer streaming checkpoint, 2026-10-12

Ordinary conversation now has a separate, default-disabled incremental answer lane.
`OPERATION_WORKSPACE_CHAT_STREAMING_ENABLED=false` requires both the native workspace
and event journal flags. The one initiating POST still owns generation; an authenticated
GET SSE subscription only observes committed local SQL notifications. Reconnect/replay
cannot start a model call, source read, Goal or action. Existing legacy chat remains unchanged.

The OpenAI SDK decodes the provider stream. Only the unfinished structured `answer` field
is sent as a display-only draft; reasoning, plans and next-action fields are not streamed.
Terminal usage settles before final JSON/schema validation. A cut, unpriced or missing receipt
retains its unknown reservation, with no retry. Actions/handoff depend on the fully validated
final response and existing server policy, never a draft. Closing observation does not stop
generation; the existing explicit stop control closes the producer when it next yields.
Already sent model work may still incur a charge.

Draft text/revision lives in the additive chat metadata, outside legacy strict JSON. Each
append and terminal notification commits atomically with its chat state. Chat and Goal writers
share the same short SQL transaction fence, preserving event-ID commit order across producers;
no model/network I/O runs under that fence. Per turn: at most 16,000 draft code points,
128 append notifications plus one terminal notification; provider JSON is bounded to 64 KiB
and the wire stream to 1 MiB. Long generation may reach the draft-update cap before its final
validated reply. A cancelled/failed turn keeps its draft in collapsed details. Lost producers
are marked failed on the existing stale-turn recovery path, without automatic generation.

`/topics/{topic_id}/notifications` is the typed mixed cursor page; `/stream` uses distinct
`chat_text` and `workspace` event names. The existing `/events` contract remains Goal-only.
Browser cursors stay owner/topic-scoped. Unicode offsets, revision gaps, missing cache rows,
duplicates and cut frames are checked; a gap triggers a local SQL GET repair, not a POST.
No new default UI controls, hotkey hints or repeated accessibility announcements were added.

One separately bounded actual-model synthetic check produced 18 monotone previews and one
validated final answer with `next_action=none`: correct parent-funnel calculations, no inferred
cohort retention, tariff-payment proof or child denominator. The local ledger settled one call
at 819 input/435 output tokens, **$0.005988 using configured rate cards**, not an invoice claim.
No application/source/production I/O occurred. Durable receipt and the one-call-only ledger:
`output/chat-stream-20261012/quality.json` and `budget.db`. Do not restart the paid check.
This is a narrow wire/grounding check, not evidence of full agent quality or business improvement.

Local gates passed: `make verify` (790 backend tests, 127 UI tests; 12 PostgreSQL-only skips
and two excluded opt-in live tests), separate PostgreSQL 17 migration round trip/drift and
12 integration tests, native streaming and unchanged legacy browser flows. Tests cover atomic
draft/final journal rollback, stop/append races across connections, commit ordering between
Goals/chat, bounded storage, Unicode/gap repair and model receipt failure accounting. Supported
old-image rollback retains previews and native private state. The unpublished local overlay
image `mana-ai-operation:chat-text-local-20261012` passed networkless HTTP/SQL/replay/ownership
checks; API synchronization, standalone UI, bundle and secret checks passed. GitHub still
reports `push=false`; scoped release approval remains outstanding. No production activation,
new source permissions, Firebase reads, schedules or SSH changes occurred.

### Complete closed-Goal condition capture, 2026-10-12

The latest-100 result page is no longer used as the source of all user conditions. A failing
regression demonstrated that a legacy Goal's original no-contact/$5/parent-only conditions
disappeared after 105 completed tasks, despite the deduplicated context fitting every limit.
Session capture now streams the complete same-owner/topic/product closed history before the
frozen cutoff, validates every checkpoint, preserves exact quoted conditions/role aliases,
and retains only three result excerpts with the exact omitted-result count. This also covers
old native session-memory quotes beyond the visible page; an incompatible old checkpoint
fails closed rather than quietly disappearing. Public task lists remain bounded to 100.

The SQL iterator uses batches of eight, an explicit
`OPERATION_WORKSPACE_CONTEXT_GOAL_LIMIT=10000` (range 1–10000), and deterministic date/ID
ordering. Capture exceeding this archive bound fails before any model call; the independent
400-unique-quote and input-byte bounds remain unchanged. Stream/cursor resources close even
on early failure. This is lossless condition capture within explicit limits, not an unlimited
context window, semantic summary or relaxation of consent. Existing frozen chat/Goal snapshots
are not rewritten. Prior findings still need separately admitted source evidence.

The bound counts inspected closed topic rows. Product ownership is checked after strict
decoding, so a missing/damaged old product field cannot filter away the original prohibition.
Valid other-product records never enter the context; incompatible or corrupt records fail
capture with a controlled error. No raw checkpoint contents appear in that error.

The design follows the official distinction between
[memory, compaction and reviewed artifacts](https://developers.openai.com/cookbook/examples/agents_sdk/building_reliable_agents_memory_compaction):
SQL remains authoritative for original conditions, source lineage and lifecycle state;
model working memory is not the record of truth. No paid compaction/extraction or external
data collection was added to this capture fix. No schema/API migration or production/key/
source/schedule change was made. Full release acceptance remains outstanding.

Local evidence: `make verify` passed (794 backend tests, 127 UI tests, 13 separately opt-in
PostgreSQL skips and two excluded live suites). Separate PostgreSQL 17 migration round trip,
drift and 13 cases passed, including a 105-Goal native/legacy condition archive and owner/
product/time filtering. Actual private-browser flow passed full-condition handoff from the
first of 105 historical tasks through scoped saved-data tools, question, investigation,
independent fake-model review and reload. This is workflow evidence, not live LLM quality.
SQL/HTTP cases also cover exact cross-role quotes, explicit overflow before generation,
corrupt old protocol/product fields, unchanged original records and frozen idempotent replay.
Unpublished local image `mana-ai-operation:goal-archive-local-20261012` passed a networkless
105-Goal HTTP/SQL/model-port/replay/ownership smoke and the actual old/new rollback probe;
five backend source hashes match the workspace and no `.env` is present. Contract sync,
standalone UI, bundle, type/lint/format and secret gates passed. No paid API call was made.
GitHub still reports `push=false`; scoped release approval remains outstanding.

### Native workspace quality and priced-output correction, 2026-10-12

The local opt-in `scripts/operation_workspace_evaluate.py` pins eight administrative cases:
automatic conversion analysis, aggregate-vs-cohort retention, DAU/WAU, tariff/payment proof,
activity/sales geography, unsupported customer contact, MANA/360REC isolation and the full
retention/funnel/payment objective with missing evidence. Default CLI execution is offline;
paid execution requires `--confirm-paid --output <fresh-directory>`, an exclusive attempt
directory and one shared ledger capped at 16 calls/$0.49. It uses actual chat/handoff/Goals
services, current strong-model settings, private SQL and synthetic minimized reports. No
application factory, customer source, domain executor or production setting is activated.
Protocol checks are separate from manual semantic review; no LLM judge or automatic quality
score is billed. Expectations are fixed before results, following official
[agent evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices#single-agent-architectures).

Observed result, not an unconditional eight-case pass:

- Seven initial conversation cases selected the correct route and passed manual grounding
  review: 20%→15%, −5 pp/−25% without inferring no churn; DAU/WAU not D7; tariffs/sample
  not population payments; activity cities not sales; no unbuilt contact execution; no
  MANA evidence transferred to 360REC. The exact screenshot's analysis request created a
  durable same-room Goal, cancelled locally after its route-only inspection.
- The eighth actual Goal discovered/loaded the scoped report and initially stopped on a
  completed, priced response that failed structured-output parsing. Its original malformed
  content was not retained, so the exact cause remains unproven; do not claim a specific SDK
  bug or hide this first-attempt failure. A separately marked one-call diagnostic on the
  same ledger produced a valid partial investigation, and independent review correctly
  waited for real behavioral/funnel/payment evidence rather than declaring the full objective
  achieved. Synthetic D1=60%, D7=28%, previous D7=40%/−12 pp remained explicitly synthetic.
- A subsequent two-call synthetic parse-fault injection tested the new real runtime recovery:
  known usage settled, prior draft/evidence retained, scoped v7 corrective feedback queued,
  next bounded review call completed, and the Goal again waited for missing real data.
  This demonstrates priced-format recovery, not reproduction of the original malformed body.
- Entire original batch, diagnostic, normal review and fault probe: **16 calls total**,
  **$0.177108 by configured rate cards**, all settled, unknown holds zero. Day/month snapshots
  are the same spend and must not be added. These are ledger estimates, not an invoice or
  broad production quality score. Source requests and production changes were zero. The
  attempt markers/ledger are exhausted; do not start another paid party to replace failures.

Established native continuations now classify a verified-priced invalid structured decision
as `invalid_decision` and may queue a corrective reasoning step. It shares the existing total
two-recovery cap with unloaded citations, retains original objective/context/evidence/consent,
and uses normal Goal step/global cost admission. No malformed decision is published or
executed. Invalid output is not silently repaired. First-call failures without a confirmed
continuation, unknown usage, timeouts, incomplete response or unsafe continuation still stop;
no lost model/source read is automatically retried. A concurrent pause/steer fences recovery.

Pending new format feedback is versioned as private checkpoint v7, bound to the immutable
analysis scope and a valid continuation. Clearing it returns to the compatible v6 window;
the recovery count/history remains. Legacy JSON stays closed/unchanged. Automated tests
cover known-error→valid continuation, the two-step cap, unknown-I/O stop, SQL restart and
cost-preserving control; PostgreSQL and supported old/new pause rollback retain the v7 state.

Engineering artifacts: `output/workspace-quality-20261012/party/` (original eight-case files,
`results.json`, diagnostic/review/fault markers and `final-accounting.json`). Manual review
and synthetic fault evidence do not prove source completeness, real retention improvement,
deployed quality or parity across every Codex/Claude task. Full release/source acceptance and
extended context work remain open; GitHub still reports `push=false` and scoped release
approval is outstanding. Production/audio/SSH/Firebase/GA4/schedules/keys were unchanged.

Final local gates: `make verify` passed with 800 backend/127 UI tests, 13 PostgreSQL-only
skips and two excluded live suites; separate PostgreSQL 17 migration/drift and 13 integration
cases passed, including v7 feedback persistence/pause. Native browser/tool/question/review/
scope/reload flow, API synchronization, standalone UI, bundle/secret/type/lint checks passed.
The unpublished image `mana-ai-operation:quality-recovery-local-20261012` was rebuilt from
the existing stable `2ea7b9a` dependency base after two local overlay exports reported missing
Docker layers; no daemon restart, image deletion or project cleanup occurred. Actual networkless
runtime/105-Goal HTTP/SQL/model-port/replay/owner smoke and old/new v7 rollback passed, with
five backend source hashes matching the workspace and no `.env` in the image. These remain
local engineering/quality evidence, not release permission or overall Goal completion.

### Remaining full-goal work

Do not mark the overall Codex/Claude interaction objective complete from this checkpoint:

- Repeat regression, PostgreSQL concurrency/recovery, contract/security and browser checks
  after subsequent changes; the current local checkpoint's final gates passed as listed above.
- Extend real-model quality coverage beyond the small reviewed synthetic/saved-data checks,
  then separately verify any newly approved source bindings without a scan or new schedule.
- Expand Goal-step streaming/continuation and extended-context behavior with
  explicit interruption/reconnection semantics; ordinary answer streaming is now a local opt-in.
  Completed results now enter ordinary conversation as bounded historical checkpoints, not
  fresh evidence. Very long user-context histories still fail closed at an explicit byte/count
  limit without calling the model; scalable retrieval/compaction of extended sessions remains.
- Expand conversational owning-domain action coverage beyond the now-verified synthetic
  Growth draft lane, following Retention-first delivery and explicit live authority. Do not
  claim unbuilt Retention/Orchestrator/Technical handlers or real payment/conversion evidence.
- The scoped sidecar/UI release and production diagnostic are recorded in
  [the release report](operation-agent-workspace-production-release.md). Repeat that scoped
  verification after further changes; preserve the independent main API/audio and scheduler.
- Retain the actual deployment's rollback controls and additive schema. The local older-image
  proof is not a destructive production restore drill or permission to downgrade history;
  confirm paused native Goals stay paused after any future rollback/roll-forward.
