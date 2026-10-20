# MANA family agents — implementation in progress, 2026-10-20

Latest: [review-first message checkpoint](mana-family-review-first-checkpoint.md).
It supersedes the earlier v5 model/context limitations without rewriting their
negative receipts. Both APIs and the coordinated review-first message workflow are
implemented locally; real-family and production release acceptance remain separate.

This replaces the application-facing agent design, not the four operational
administrative agents. It does not rename, resume or deploy the earlier broad
OPERATION workspace work. The isolated released parent chat `f2c023f`, its private
key/history/quota and main/audio services remain unchanged on production.

## Owner's requirements and confirmed choices

- **Parent-Touch is the only parent-facing speaker.** One parent has one durable
  chat, never separate chats or visible competing agents. Parent-Touch communicates
  and coordinates; it does not change limits, permissions, locations or accounts.
- **Child-Safety owns child protection and behavioral analysis.** Reuse the ten
  existing protective MANA AI contracts; Parent Copilot's conversational role moves
  to Parent-Touch. Keep the legacy inference endpoints compatible. Specialist
  results, questions and proposed actions are internal data, not direct chat sends.
- Trigger Child-Safety on **new child data or new parent messages**, not periodic
  rereads or repeated inference on an unchanged version. It reads the correct
  parent's bounded saved conversation with an explicit cutoff. Historical family
  text is not a new sensor measurement or a source/action grant.
- Specialists propose a single information need with a stable key, evidence/date,
  priority and expiry. Parent-Touch sorts, filters/coalesces duplicate information
  needs and phrases at most **one active question**, then binds one answer before
  asking the next. The API must carry the invisible question/reply identity;
  natural-language relevance must not silently attach an answer to another child.
- The owner confirmed **2000 raw input+output tokens/day for Parent-Touch only**.
  Child-Safety needs a separate explicit server-wide budget and per-job/parent
  admission limits. No hidden additional budget, auto-renewal, provider retry or
  automatic release of an unknown model charge is allowed.
- Calls are through the trusted MANA application backend using the canonical
  profile/Firebase parent ID. Derive that ID from the backend's authenticated
  session. Fresh child ownership must precede new analysis or question delivery.
  The general inference token and 360REC clients must not read family history.
- Russian/Uzbek and other reply languages follow the parent, never an arbitrary
  specialist prompt. Data/prompt text cannot change grants, recipient or language
  authority. Raw child signals must not enter operational reports or logs.

## API shape — both APIs implemented locally, release acceptance still pending

All paths are under `/api/v1/mana-ai`; this remains an independent product API.

| Path | Purpose | Provider/mutation boundary |
| --- | --- | --- |
| `GET /agents` | Registered family roles, available contracts and support status | SQL/config observation only |
| `GET /parent-touch/chat` | Single history, quota, active reply identity and queue status | No source/model call |
| `POST /parent-touch/chat` | Parent message, optional explicit reply identity | One Parent-Touch generation under existing quota/unknown holds |
| `POST /parent-touch/messages` | Recommended review-first parent message, `202` | Durable admission -> separate specialist review -> one speaker generation |
| `GET /parent-touch/messages/{request_id}` | Same-family progress/final response | SQL observation only, never redispatch |
| `POST /parent-touch/deliver` | Deliberately admit one queued specialist communication | No fabricated parent message; one generation, no delivery retry |
| `GET /parent-touch/requests` | Backend observation of same-family question state | SQL only; no dispatch |
| `POST /parent-touch/requests` | A registered specialist's typed communication intent | Internal backend only; fresh ownership and durable dedup |
| `POST /child-safety/safety-monitor` and capability-specific peers | New dated child observations using existing typed protective contracts | Durable content/chat-version admission, separate analysis budget |
| `GET /child-safety/assessments/{id}` | Analysis/clarification progress and result | Same-family SQL observation |

Keep one endpoint-specific request/response schema for every protective capability.
Do not introduce a capability-discriminated generic `/mana-ai/analyze`, a second
chat, a user-selectable sender, arbitrary provider payload or contact/write tool.
Existing `/chat` must remain compatible and share the same Parent-Touch history;
both paths must use the same broker once that mode is enabled, not rival writers.

The Parent-Touch/directory paths above are now implemented behind
`MANA_PARENT_TOUCH_ENABLED=false` by default. Enabling it requires the existing
isolated `MANA_PARENT_CHAT_ENABLED` runtime and its strong backend credential.
`MANA_PARENT_TOUCH_QUESTION_LIMIT` bounds pending questions (default 100).
The subsequent Child-Safety increment below adds all ten protective admission
endpoints, SQL assessment paging/status and budget reads, behind a separate
default-disabled `MANA_CHILD_SAFETY_ENABLED` flag and explicit limits.

`GET /agents` deliberately reports Parent-Touch `available`, Child-Safety
`disabled` when its optional runtime is absent, `available` when installed, and
`unavailable` after an unclassified worker failure. Every new route uses `ParentChatBackendToken`,
not the general inference security scheme. The existing `/chat` contract is
unchanged and uses the same runtime/history/quota when Parent-Touch is enabled.

### Mobile/backend integration

Only the trusted application backend calls these routes. It derives `parent_id`
from its authenticated MANA profile, never an arbitrary mobile-supplied family ID.
The app still shows one chat and one message input; the backend supplies hidden
correlation fields, not separate specialist chats.

1. Read `GET /parent-touch/chat?parent_id=123`. `message_questions` maps assistant
   turns in that page to the exact question/child identity. `active_question` is
   the currently awaiting question, possibly on an older page; load its turn before
   presenting a reply UI. History/quota/question metadata share one SQL snapshot.
2. Send `POST /parent-touch/messages` with `parent_id`, a UUID `request_id`, `message`
   and, for an explicit answer, `reply_to_question_id` from that displayed question.
   Missing metadata does not silently attach unrelated prose to a child/question;
   a stale, foreign or already answered question returns `409 question_reply_mismatch`.
3. Observe its status until `completed`; `response.asked_question` describes only the question published
   by **that turn**. It remains unchanged on replay after the parent answers or
   another question becomes active. Read history for the current active state.
4. Internal specialists submit their dated `AgentQuestionRequest` to
   `POST /parent-touch/requests`. This validates the registered specialist and
   fresh connected child, deduplicates and queues; it does **not** send to the chat.
   `GET /parent-touch/requests` pages that parent's internal queue only.
5. `POST /parent-touch/deliver` accepts only `parent_id` and UUID `request_id`.
   It admits one queued communication and stores an **assistant-only** turn, with no fake
   parent message or push notification. It freezes the latest saved parent text as
   its language/script reference and rechecks fresh child ownership before inference.
   No earlier parent text gives `409 parent_language_not_established`; no ready
   question/another active question gives `409 no_question_ready_for_delivery`.
   These refused admissions perform no source/model call. When Child-Safety is
   explicitly enabled, its SQL event worker can admit this same delivery lifecycle.
   No HTTP history read starts delivery. V5 additionally maps `message_notices`
   to delivered assistant turns and exposes `pending_notices`; the latter is not
   a send confirmation. See the concise [integration guide](mana-family-agents-integration.md).

Reuse the same request UUID and **identical body** after transport loss. Replays
never read children, resize input, regenerate or publish a question twice. Both
message and delivery inference count raw input+output toward the **same** default
2000 daily tokens. A new nonce cannot repeat a deferred delivery for the same
question and frozen parent-language turn. A genuinely new parent message changes
that context, without refunding any earlier verified model cost.

Producer admission is persisted **before** a new ownership source call. Exact
nonce conflicts, identical-body new nonces and already answered information-key/
source-revision requests are deduplicated before I/O. Coalescing retains specialist
subscriptions and the original question/observation window; only queued priority
may increase. Rejected, failed or abandoned producer admissions do not expire into
an automatic source retry. A genuinely new observation/revision is separate work,
not permission to replay an unknown charge or relabel old data as current.

## Durable flow

```text
new child data / accepted parent message
  -> deduplicated, bounded Child-Safety job
  -> verified own-child facts + dated saved chat cutoff
  -> separately metered safety assessment
  -> internal result / information need
  -> Parent-Touch queue (priority, duplicate filtering, expiry)
  -> one admitted, own-child-validated Parent-Touch turn
  -> verified single question in the one chat
  -> explicit question-bound parent answer
  -> Child-Safety follow-up on the new version
```

Provider submission and unknown outcomes need durable claims before I/O. A lost
HTTP response observes the existing result; it cannot reread sources, regenerate,
release a hold, send the question twice or reassign its answer. Coalesced questions
retain every specialist subscription while sharing one conversation slot. An
urgent safety notice must remain distinguishable from routine clarification;
it may not gain direct-sender or automatic control authority.

Publishing a question, saving its parent-visible message, consuming verified usage
and journaling its follow-up must share a SQL transaction. Likewise, admitting a
parent reply must bind that exact stored turn to the active question atomically.
Do not deploy a sequence of independent best-effort post-response callbacks.

## Historical local increments (see the latest v5 checkpoint below)

Worktree: `/mnt/ssd2/mana-family-agents-20261020`, branch
`feat/mana-family-agents-20261020`, clean source baseline `bf1d12a` on the actual
parent-chat release, not the unrelated dirty operational tree.

Implemented so far:

- Strict family-agent/question contracts and an immutable injected registry.
  Only Parent-Touch can be a speaker. Child-Safety owns the ten existing
  non-copilot protective capability identities. New specialist identities require
  deliberate registered definitions, not model-supplied authority.
- A private opt-in SQLite v2 queue, reusing the dedicated parent-chat adapter.
  Cross-process SQL uniqueness enforces one active/offered/held question per
  parent and one open information need per child/key. Multiple agent requests
  coalesce without overwriting the original question or observation dates.
- Exact request-body conflicts, preserved intent replay, priority/FIFO selection,
  explicit queue ceiling, paged history, expiry of **unsent** questions only,
  admitted-turn binding, parent isolation and explicit answer-turn binding.
- A v1 chat/quota can migrate additively without changing its history, replay
  digest, verified usage or unknown holds. Unmodified v1 code refuses the new
  tables/version; do not present it as a working v2 rollback reader or restore an
  old database over newer history.
- `ParentTouchService` reuses the existing chat admission, fresh own-child source,
  quota, recent history and receipt handling. Its prompt contains only the frozen
  selected question and the fresh matching child's permitted name, not raw child
  IDs, other families or the entire queue. A revoked child blocks inference.
- Parent-Touch uses a strict structured reply: ordinary body plus at most one
  question bound to the admitted UUID. Explicit extra questions, wrong/missing
  identities and invalid JSON are withheld while verified raw usage is retained.
  Exact input sizing uses the same schema as generation; dropping old history
  preserves the admitted question and current facts without recapture.
- Question selection and explicit parent-answer binding now share **chat admission's
  transaction**. Verified usage, accepted answer and the question's awaiting-reply
  state share **settlement's transaction**. A simulated failing commit publishes
  neither message nor question and retains the original submitted hold. Unknown
  calls hold the question indefinitely; safe pre-inference abandonment can recover
  without letting its old process submit a model call.
- Authenticated HTTP/runtime wiring, directory, queue admission/observation, frozen
  reply identities and proactive assistant-only delivery now use that same lifecycle.
  Inactive mode remains the unchanged legacy service/store. New family metadata lives
  outside legacy response JSON. Public docs and generated TypeScript include the
  implemented routes, but do not advertise a working Child-Safety worker.
- The family schema is now **v3**, additively accepting v1/v2 histories without
  recapturing old turns. New metadata is absent on historical turns; do not invent
  question identities for them. Older v1/v2 code refuses v3; this is still **not**
  a tested rollback reader or a production release.
- Both standalone OpenAPI exporters now resolve their own source checkout before
  importing `app`. An unrelated editable Python installation must not leak its
  operational working changes into this product's generated contracts.

The subsequent runtime checkpoint adds an event worker, model adapter and automatic
question delivery. Full assessment/urgent-notice delivery and release acceptance
are still pending, and no production runtime was activated. A queue fixture pass
and punctuation validation are not semantic language/safety acceptance or proof
of real delivery. Revoked selected children fail closed before question inference;
automatic cancellation/filtering of obsolete queue items is not implemented.

Actual checks: **82 related cases** passed (including actual SDK over MockTransport,
not a real provider). Full clean-worktree **`make verify` passed**, original session
**71187**, exit **0**: **364 backend tests**, **1 skipped**, **2 opt-in live tests
excluded**; **26 UI tests /11 suites**, Ruff/format/ESLint, mypy **217 files**,
TypeScript, production UI build and zero npm vulnerabilities. Logs are in the main
workspace's ignored `output/family-agent-*-20261020.log`, especially
`family-agent-core-verify-20261020.log` and `family-agent-parent-touch-final-20261020.log`.
That is the historical core gate, not acceptance of the subsequent HTTP increment.
The HTTP increment's related suite has **97 passing tests** (overlapping the core
suite), plus a standalone checkout-resolution regression. Its terminal full gate
`OPENAI_API_KEY=unit-synthetic-key make verify` passed in original session **28013**,
actual exit **0**, log `family-agent-parent-touch-api-final-verify-20261020.log`:
**375 backend tests**, **1 skipped**, **2 opt-in live tests excluded**; **26 UI
tests /11 suites**; Ruff/format/ESLint, mypy **220 files**, TypeScript, production
UI build and zero npm vulnerabilities. `make audit-schema` passed after the
checkout-resolution fix; standalone product docs export reports **17 paths** and
zero provider/source calls. Secret scan passed for **381** tracked/unignored files.
The first full-gate attempt without a synthetic key failed at legacy test import;
its log remains `family-agent-parent-touch-api-verify-20261020.log`, not a pass.
None of these tests calls the live model, children, Firebase/GA4 or production.
This remains an intermediate checkpoint, not completion of the user-requested
two-agent API or goal.

## Earlier Child-Safety event/budget core acceptance

`SqliteChildSafetyStore` is an explicitly constructed, private **v4** adapter over
the family database. At core checkpoint `867d915` the application factory selected
v1/v3 only; the later increment below wires v4 into an explicitly enabled runtime.
No real server budget has been assigned or charged. `ChildSafetyLimits` requires
explicit job, parent/day and server/day raw-token ceilings, with
`job <= parent <= server`. It cannot inherit Parent-Touch's 2000-token allowance.

Implemented and tested:

- A durable parent-message outbox is inserted in the **same transaction** as a
  new parent chat admission, only when this v4 adapter is deliberately used.
  Replay, history GET, failed admission and assistant-only delivery do not create
  another event. Initializing v4 never recaptures historical parent turns.
- New child-data jobs have exact nonce/body conflicts and nonce-independent
  normalized observed-input deduplication. New request/revision labels, display
  language, evaluation time and equivalent UTC-offset representations cannot pay
  to reanalyze unchanged observations. A new parent message has its **own** review
  event; resending old child data after that message still returns the old data job.
- Each job freezes bounded same-family messages, including assistant-only questions,
  an explicit chat cutoff, and at most twenty exact saved assessment references.
  The separate latest-parent cutoff is a trigger identity, not the limit on visible
  assistant messages. Snapshots report their saved-result total; neither this
  bounded page nor recent SQL capture time proves complete/current coverage.
- Provider-independent SQL claims reserve the explicit per-job ceiling against
  both global and per-parent budgets before any future source/count/model I/O.
  `BEGIN IMMEDIATE` and a unique active-parent index prevent two workers from
  over-admitting or analyzing one family concurrently. Separate pending-job and
  daily-attempt ceilings provide backpressure even when failed work used no tokens.
  Eligibility is filtered before bounded result selection: exhausted/full parent
  queues cannot starve an eligible family behind an older queue prefix.
- Fresh connected-child authorization must be supplied by the future owning
  application service and frozen before submission. Scope changes, expired claims
  and model outputs cannot add another child. The real source-to-ledger connection
  is **not implemented or accepted** by the current ID-only fake authorization tests.
- Verified input/output usage is recorded **before** future schema/decision
  validation. Invalid decisions retain their known cost. Unknown submissions never
  requeue or release a reservation across restart/midnight. Expired pre-submission
  claims fail without dispatch; a late old worker cannot submit. Late verified
  receipts reconcile original admitted-day costs but cannot publish a decision.
  An over-hold receipt is retained and cannot later be overwritten by a cheaper one.
- Model settlement and final decision publication are separate: after metering,
  one result and its optional own-child specialist question commit atomically.
  A failed publication rolls back both without refunding the earlier verified cost.
  Child-Safety never inserts a parent-visible chat message. Tests demonstrate that
  the existing Parent-Touch lifecycle remains the only actual speaker.
- Raw child input is cleared after terminal known failure/completion; hashes and
  minimized derived results remain. Evaluation time, actual signal timestamp
  bounds, processing time and SQL capture time remain separate. Timestamp bounds
  are available signal instants, **not** proof of full observation-period coverage.
  Unknown in-flight input/holds remain private and durable; no automated cleanup
  may erase them as a way to retry. Future signal timestamps are refused on new work.
- Exact capability restoration avoids an unsafe generic-union guess: battery
  inputs can match both Safety Monitor and Behaviour Anomaly, so the persisted
  capability selects the original typed request. Parent Copilot is not a safety
  capability; result request/capability/parent/child identities must still match.

Actual gate: original session **37549**, terminal exit **0**,
`family-agent-safety-ledger-final-verify-20261020.log`: **398 backend tests**, **1 skipped**,
**2 opt-in live tests excluded**, **26 UI tests /11 suites**, lint/format, mypy
**223 files**, TypeScript/build and zero npm vulnerabilities. The **23** new ledger
cases and **74** focused related cases overlap that full suite. `make audit-schema`
passes with unchanged public paths/contracts; secret scan passes for **384** files.
Only fakes and temporary local SQLite databases were used; external source/model
calls and production spend are **zero**.

V3-to-v4 local migration preserves existing history, replay and unknown Parent-Touch
holds. Old v1/v2/v3 readers refuse v4; this remains fail-closed evidence, **not** a
working rollback/candidate-image acceptance. Never downgrade or overwrite new history.

## Remaining acceptance — preserve the full task

### Current runtime/API checkpoint

Implemented after the core gate: `ChildSafetyService`, `OpenAIChildSafetyModel`,
`ChildSafetyPromptBuilder`, `FamilyAgentWorker`, ten endpoint-specific submission/
receipt pairs, `GET /child-safety/assessments[/{job_id}]` and `/child-safety/budget`.
POST returns **202** with a durable job identity; it is not proof of verified child
ownership, completion or a chat send. GET and replay observe SQL only. Successful
saved results are internal, with proposals still unexecuted.

The enabled runtime reads one freshly ownership-filtered Manakids profile per
claimed job, checks owner/collection age, freezes connected children, loads only
captured same-family result references, and preflights exact model input. It makes
one generation with transport retries disabled, records strict raw terminal usage
before parsing `SafetyModelDecision`, and runs the captured semantic decision
through the existing deterministic/evidence/action-proposal validation service.
There is no second paid analysis call, fabricated sensor freshness or tool access.
SDK 2.53.0's `to_strict_json_schema` makes nested/default fields required for the
provider schema; reverify this private helper on SDK upgrades.

New information needs enter the existing Parent-Touch queue atomically with the
assessment. The SQL-only worker selector automatically admits a stable-ID
Parent-Touch delivery when no other question/turn is active and quota permits.
Assistant-only deliveries never trigger safety analysis. New parent replies do;
the specialist receives their frozen dated text and previous assessment metadata.
No Firestore/GA4 refresh, source scan/listener or periodic unchanged-data analysis
is introduced. Unclassified worker/storage failures stop dispatch instead of
automatically restarting; old-result replay/status remains available.

Configuration: retain the existing isolated backend credentials and enable
`MANA_PARENT_CHAT_ENABLED`, `MANA_PARENT_TOUCH_ENABLED`, then
`MANA_CHILD_SAFETY_ENABLED` only with an explicit `MANA_CHILD_SAFETY_LIMITS` JSON
object (required `server_daily_tokens`, `parent_daily_tokens`, `job_tokens`).
These are raw-token ceilings, **not a USD forecast**. Server-wide daily attempts
also bound zero-token source failures. Output cap and source/count/generation
timeouts must fit the explicit job allowance/SQL lease. No real budget was enabled.

Actual terminal gate: session **74434**, exit **0**, log
`family-agent-child-runtime-final-verify-20261020.log`: **416 backend tests**,
**1 skipped**, **2 opt-in live tests excluded**, **26 UI tests /11 suites**,
Ruff/format/ESLint, mypy **232 files**, TypeScript/build, zero npm vulnerabilities.
**41 focused tests** overlap that gate. Product docs now expose **30 paths**;
all old path definitions are unchanged. Schema synchronization and secret scan
**393 files** pass. An earlier format-only gate failure is retained in
`family-agent-child-runtime-verify-20261020.log`, not reported as a pass.
Tests cover actual SDK over MockTransport, all ten HTTP admissions and an actual
lifespan/background-worker question/answer loop with fake model/source ports.
This is not real-model semantic/safety quality, actual source acceptance or release.

The following was the remaining work at `e30fba4`, before v5. Items 1, 2 and
the feature-deactivation defect in item 4 are addressed by the later checkpoint;
do not treat the historical gates below as acceptance of newer changes:

1. Feed validated assessments into Parent-Touch's own bounded frozen context and
   implement result/urgent-notice delivery even when no clarification is needed.
   Currently automatic delivery carries questions, not every assessment result.
2. Add automatic communication delivery and a separate typed urgent-notice policy;
   retain Parent-Touch as the only speaker, no fake parent turns and one active
   clarification. A routine question must not masquerade as an urgent safety alert.
3. Complete failure/race/semantic acceptance for the new API/runtime and notices.
   Do not represent internal assessment summaries as direct specialist chat sends.
4. Verify compatible v4 closed readers and safe feature deactivation before release.
   Merely disabling Child-Safety currently selects a v3 reader that refuses a populated
   v4 database: safe refusal, but not acceptable availability/rollback. Never downgrade
   or replace history to work around it. No production deployment is approved here.
5. Complete the public API/authentication/configuration/lifespan/docs and backward
   compatibility contracts. Default-disabled migration/runtime until explicit
   activation, no accidental replacement of the deployed private parent-chat key.
6. Verify two-worker races, cross-family/child denial, stale ownership, missing
   source facts, RU/UZ phrasing, question-answer ordering, coalesced subscribers,
   lost acknowledgements, SDK failures, quota rollover and actual compatibility.
7. Run full repository gates, hermetic HTTP end-to-end examples and actual candidate
   image/rollback checks. Any paid diagnostic must be a separate bounded synthetic
   party, never a random customer's conversation. Deployment requires its own scope.

The model/queue boundary follows [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
typed decisions are validated by the host; schema adherence alone does not prove
semantic safety, consent, ownership, one-question phrasing or successful delivery.
No new source, model, production, SSH, key or schedule change has occurred here.

## Latest v5 communication / closed-profile checkpoint

This section supersedes the earlier remaining-implementation statements, not their
historical test receipts. Both APIs and the event worker are implemented locally;
**full real-model conversational quality and production release remain unaccepted**.

V5 adds an immutable parent/turn/hash-bound minimized report snapshot, including
all qualifications, actual signal/evaluation/processing dates, and at most one
highest-severity validated finding with its recommendation. Total report/finding
counts expose the bounds; this is not full/current coverage. New turns capture it
once. Fresh connected-child filtering removes revoked facts and unpublished
choices before inference, without selecting a replacement or releasing unknown
work. Old turns never recapture context. Legacy `/chat` response schemas/digests
remain unchanged.

Child result, typed notice and optional question now publish atomically. Validated
ALERT/BLOCK results queue urgent notices; WARN/family-digest results may queue
ordinary notices. Routine notices coalesce and defer without immediate paid
repetition. An urgent notice can accompany an already-awaiting question without
creating a second question; it still cannot bypass ownership, established language,
quota or model receipt validation. Only Parent-Touch inserts assistant messages.
This is not a real push, emergency-response guarantee or execution of proposals.

The provider schema itself now permits only the admitted question/notice IDs (or
null), forbids questions in ordinary body, and the host additionally rejects
transport identifiers/UUIDs in parent-facing prose. These guards do not prove
semantic relevance or single-question meaning. Exact token preflight and generation
use the same schema. A private two-value receipt failure code contains no raw
provider text/validation inputs and changes neither public errors nor accounting.
The standalone Parent-Touch prompt no longer inherits the legacy instruction to
ask its own ambiguous question. Concise greeting guidance reduces prompt/output
overhead without changing old `/chat` mode or the 2000-token ceiling.

Safety-off v5 selects `SqliteClosedSafetyBrokerStore`: existing context and normal
Parent-Touch requests remain available, with no safety model/admission/worker.
Parent-Touch-off selects a history/exact-replay-only reader that refuses new
inference. The v1-to-v5 migration preserves successful old replay and unresolved
holds without historical event/context recapture. No schema downgrade or old
database restore is supported. Old production images still refuse v5; the tested
fallback is **the same candidate with execution flags closed**, not those images.

Actual final gate: original session **42783**, exit **0**, ignored log
`output/family-agent-v5-notice-acceptance-verify-20261020.log`: **433 backend tests**,
**1 skipped**, **2 opt-in live excluded**, **26 UI tests /11 suites**, Ruff/format/
ESLint, mypy **237 files**, TypeScript/build, zero npm vulnerabilities. The focused
**82** cases overlap that gate. Schema synchronization passes; secret scan **399
files** passes after changing a plainly fictional provider key to the scanner's
explicit fake marker. The earlier pre-schema and pre-guard green gates are retained
separately and do not replace this final one.

Actual candidate image `mana-ai-family:local-v5-notice-20261020`, SHA256
`a934ed41c4aa6b44b53e69acd399afe50c026ee533ac34152bf4aa40aedf4165`, passed
`scripts/mana_family_agents_smoke.py` using its packaged application/dependencies,
`APP_ENV=production`, a read-only filesystem, temporary private SQLite, no network,
no capabilities and no-new-privileges. Actual SDK adapters used MockTransport.
The check exercised new parent message -> safety review -> protective assessment
-> automatic urgent notice -> exact/content replay -> safety-off and chat-closed
profiles, preserving schema/history. Four mocked generations/four synthetic profile
reads; zero real sources/provider calls. This is not an old-image rollback, external
ingress deployment or real-family acceptance.

### New independent real-model diagnostics — qualified, not a quality pass

Four separate fresh synthetic parties used the existing `gpt-5.4-nano`, default
`reasoning=none`, fake ownership profiles and new private local ledgers. No tests
called a real model; no Firebase/GA4/customer source was read. No original failed
party was replayed, relabelled or replaced. Receipts and ledgers remain in the main
workspace's ignored output directories:

| Party directory | Actual outcome |
| --- | --- |
| `family-v5-model-20261020-IpyWoS` | First reply withheld by format validation; one verified charge. Exact invalid prose was not saved; do not invent its precise cause. |
| `family-v5-model-fixed-20261020-i3zXiO` | Three schema-valid calls; delivery stopped at exact token admission, before a fourth generation. |
| `family-v5-model-compact-20261020-U2at2P` | Four verified calls and a delivered notice within 1946 chat tokens, but manual review **failed**: body discussed `question_id`/solicited unadmitted clarification. This is not a successful semantic loop. |
| `family-v5-model-notice-20261020-YJcnpl` | After identifier guards/finding context, analysis completed; notice generation was withheld. Only 144 output tokens fit and all were used; adapter reported `provider_output_invalid`. Original raw terminal metadata was not retained, so do not assert a more precise provider cause. Chat used exactly 2000; no retry/refund. |

Total **12 new generations**, 29175 input /4093 output tokens, all usage known,
no unresolved holds in these four parties. Conservative uncached standard-rate
estimate **$0.01095125**, not an invoice reconciliation; individual estimates
$0.00058915 /$0.00338140 /$0.00348515 /$0.00349555. Rates: $0.20 input /$1.25
output per million, from the official [metrics/pricing reference](https://developers.openai.com/cookbook/examples/agent_optimization/optimizing_agents_for_cost_and_quality#metrics-helpers).
Earlier zero-spend checkpoints refer to their own fake-only stages, not this party.

The 2000 limit includes schema/system/history, not just visible text. These examples
demonstrate that a greeting plus a useful qualified notice can consume it; shrinking
away evidence or silently increasing allowance is not an acceptable quality fix.
Do not activate real contacts or claim dependable danger delivery based on a fake
pass. Next acceptance must improve bounded communication quality/output admission
and measure RU/UZ question/answer/notice cases under the unchanged explicit budgets
(or obtain a separate owner budget/model decision). No broad model-quality,
business/safety-outcome, real-child source or production acceptance is established.

API handoff: [backend integration contract](mana-family-agents-integration.md).
The goal stays active. Production parent chat/main/audio, SSH, keys, OPERATION
agents, schedules and Firebase/GA4 configuration were not changed.
