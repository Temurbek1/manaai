# AGENTS.md

## Repository expectations

- The owner paused the broad Codex/Claude-style workspace goal on 2026-10-16 and
  explicitly resumed it on 2026-10-17. Read the historical
  `docs/operation-contact-admission-pause.md` and
  `docs/operation-contact-admission-checkpoint.md` before continuing.
  Preparation-admission work remains local and is not a production
  release; resuming the goal does not approve real contacts or a contact deployment.
- Work in English for code, comments, commit messages, and identifiers.
- The separate MANA parent application chat is enabled on production through the
  isolated `mana-ai-parent-chat:f2c023f` sidecar and exact `/api/v1/mana-ai/chat`
  ingress. Its clean source is `release/mana-parent-chat-20261016`, based on actual
  main/audio `e73c10a`, not this paused-workspace dirty tree. It has its own backend
  key and private volume; the shared inference key must not read personal history.
  See `docs/mana-parent-chat-release.md`. That separate release resumed no OPERATION
  AGENTS work, activated no source refresh, rotated no old key and restarted no
  existing production container.
- The separate application-facing `/mana-ai/chat` is a single durable chat per
  canonical MANA profile/Firebase parent ID, called by the trusted application backend,
  never the operational-agent workspace. Keep its history/quota SQLite adapter outside
  `app/mana_ai` and isolated from operation/marketing databases. Always enforce server
  authentication, fresh ownership-filtered child profiles and explicit observation dates.
  Backend-supplied observations grant no tool/write authority. Raw terminal input/output
  tokens count against the shared daily allowance; unknown submitted receipts retain
  durable holds, and idempotent replay must never re-infer or reread sources.
- User-facing documentation may be Russian when the product audience is Russian.
- Preserve Russian and Uzbek Latin interface support. Response language is presentation,
  never a source/action grant. Freeze it on chat admission and preserve exact Goal objectives,
  evidence/history and idempotent replay. Recipient language/consent remain independently
  verified. See `docs/operation-interface-languages.md`.
- The scoped RU/UZ production increment runs `38cdac4` API/Goals worker; the subsequent
  UI-only professional release runs clean-baseline `faf0a78`, preserving
  the `6babf75` profile and `a36d9f7b802c` schema. The private Retention contact foundation
  and migration are not deployed or exposed. Only closed `2ea7b9a`/disabled native execution
  is verified for reading language metadata. See `docs/operation-interface-language-release.md`
  and `docs/operation-professional-ui-release.md`. The analytics screen reads existing saved
  SQL reports only; no source auto-refresh, provider activation or contact code ships with it.
- The local default-disabled `OPERATION_WORKSPACE_RETENTION_CONTACTS_ENABLED` lane
  supports only two fictional adults, immutable RU/UZ templates and separate typed
  human preparation/approval through the owning Retention fake lifecycle. Private
  contact v2 binds the originating turn; legacy chat projections omit its action.
  Goals remain read-only. It is not deployed, a real send, a loaded full capability
  or receipt-memory/rollback acceptance. Keep default self-approval denial; private
  ownership alone does not implement two-person review; the optional local peer lane
  below is separate and undeployed. See
  `docs/operation-retention-contact-chat-checkpoint.md` before extending or releasing it.
- New local contact-bearing Goals use private v15 with an explicit underlying
  v1–v14 profile. Freeze minimized SQL event checkpoints before capture, bind them
  in continuation digests and never upgrade or recapture old tasks. At most three
  checkpoints survive; the explicit contact-event scan ceiling refuses overflow.
  Empty contact fields preserve old storage/digests and typed schemas. Local fake
  replay/restart and actual closed `2ea7b9a` compatibility checks are not candidate-
  image, production, real-contact or broad model-quality acceptance. Do not use
  `38cdac4` as a v15 rollback reader or downgrade populated contact tables.
- The subsequent default-disabled `OPERATION_WORKSPACE_RETENTION_PEER_REVIEWS_ENABLED`
  shares one exact fictional MANA intent with one active registered reviewer through
  personal cookie sessions and CSRF, never technical keys/development actor headers.
  Private grant/audit migration `c58fb7da240e` is local and undeployed. Keep action-
  before-grant lock order, current identity/expiry/revocation checks and default
  author self-approval denial. No topic/Goal/source access or future write authority
  is shared, and Goal v15 history never inherits grants. Local two-login fake/SQL
  checks are not real contact, candidate-image rollback or production acceptance.
  See `docs/operation-retention-peer-review-checkpoint.md` before extending it.
- The local default-disabled `OPERATION_WORKSPACE_CONTACT_TOOL_PROPOSALS_ENABLED`
  exposes one strict native `request_retention_contact_preparation` function only in
  new eligible MANA Retention/Orchestrator chat turns. Account raw terminal usage
  before arguments; process the native call before accompanying text. Persist its
  owner/topic/turn-bound choice outside legacy JSON, never provider execution receipts,
  reasoning or raw invalid prose. Confirmation must match the frozen choice before
  any target read. Goals remain read-only; there is no automatic preparation/share/
  approval/send or full post-execution function-output continuation. Eligible turns
  use one nonstreamed model call; no fallback/retry or historical-task upgrade.
  Only closed `2ea7b9a` is the local verified compatibility target; earlier native
  readers do not understand the new chat metadata. See
  `docs/operation-native-contact-proposal-checkpoint.md` for acceptance limits.
- The separate local default-disabled `OPERATION_WORKSPACE_CONTACT_TOOL_CONTINUATIONS_ENABLED`
  captures only new `native_contact_preparation_v2` turns. V1 requests never upgrade.
  Retain exact private input/call pairing and only encrypted opaque continuation,
  never raw/summary reasoning or provider execution receipts. One human-confirmed
  preparation belongs to one invocation; SQL claims one result-continuation turn
  before inference. Replays/new nonces only observe it, including failed/unknown
  calls. Freeze updated session conditions, preserve original model/language and
  account verified usage before final parsing; stop fences discard late decisions,
  not their verified costs. The final response cannot create another action/tool.
  Goals stay read-only, fake acceptance is not delivery or business improvement,
  and source grants/budgets are not inherited. See
  `docs/operation-contact-tool-continuation-checkpoint.md`; local compatibility is
  only closed `2ea7b9a`, not a candidate-image/production release or full parity.
- Contact result explanations must distinguish an already prepared SQL action from
  the earlier native preparation request. Host-owned lifecycle labels are observation,
  not approval, reviewer access or renewed eligibility; unknown outcomes permit no
  redispatch. The first paid local diagnostic failed this distinction; preserve that
  receipt and its negative review. The following single synthetic real-model pass
  does not establish broader quality, real contacts or release acceptance. See
  `docs/operation-contact-loop-quality-checkpoint.md`.
- The new local default-disabled `OPERATION_WORKSPACE_CONTACT_TOOL_LOOPS_ENABLED`
  captures only new native v3 contact turns. After a verified fake result, one
  remaining distinct fictional adult may be requested, never prepared/shared/
  approved/sent automatically. Every step retains its own human confirmations and
  owning policy; Goals remain read-only. Private root/receipt/window pairing is
  immutable and bounded to two invocations; old v1/v2 never upgrade. Unknown/cancelled
  child inference never frees a consumed invocation. Preserve original conditions,
  model/language and verified costs after stop fences. See
  `docs/operation-contact-tool-loop-checkpoint.md` for current local acceptance; this
  is not a deployed contact feature or full multi-action/model-quality acceptance.
- The local continuation UI observes private SQL history while its confirmed POST
  is pending; the paginated head must actually revalidate. Stop uses the admitted
  child ID, never undoes an already verified action or guarantees no model charge.
  Navigation/reload/status reads never redispatch work; pending UI state is scoped
  by owner/topic/origin turn. No stored contact protocol or SSE/source-refresh
  authority changes. See `docs/operation-contact-progress-checkpoint.md`.
- Keep the project production-oriented: explicit configuration, typed schemas, clear errors, and no hidden globals.
- The local manual contact control registry is separate from persisted agent definitions
  and analysis handlers. Never turn it into a scheduled capability or a Goal write tool.
  New turns observe stop scopes, while old turns retain their original snapshots/replay;
  re-arming grants no approval/send/source authority. Proposal admission limits and full
  owning-domain activation remain open. See `docs/operation-manual-action-controls.md`.
- Do not hardcode secrets. Use environment variables and keep `.env` files out of Git.

## Architecture rules

- Treat `docs/operation-agent-model.md` as the canonical MANA OPERATION AI product direction.
  The target has exactly four top-level operational agents: Operations Orchestrator, Growth &
  Conversion, Retention & Loyalty, and Technical Reliability.
- Model advertising, SMM, conversion, upsell, experiments, referral, win-back, admin analytics,
  review analysis, and incident creation as capabilities inside those four agents. Do not create a
  new top-level agent for a report row, integration, scheduled job, or action kind.
- Operational agents are action-capable, not analysis-only. New action families require typed
  domain contracts, policy, approval, idempotent execution, fresh-state validation, verification,
  uncertainty recovery, outcome measurement, audit, and a fake/sandbox executor.
- Operations Orchestrator may create and manage goals/tasks but must delegate infrastructure,
  financial, customer-contact, and deployment mutations to the owning domain agent. Do not give
  the orchestrator arbitrary provider payloads or unrestricted integration credentials.
- The shared durable Goals workspace supports private analysis objectives, SQL checkpoints,
  bounded strong-model planning/investigation/review, pause/resume/steering and separately
  confirmed read-only delegation. It is not a fifth agent, a full Orchestrator implementation,
  or proof of business-outcome improvement. Keep unknown in-flight costs reserved and never
  automatically retry a lost source read. See `docs/operation-goals.md`.
- The opt-in native agent workspace remains default disabled via
  `OPERATION_AGENT_WORKSPACE_ENABLED`; the scoped production deployment explicitly enables it.
  See `docs/operation-agent-workspace-profile-release.md` for current versions and limits.
  It adds conversational handoff, typed scoped evidence
  tools and in-flight steering, not unrestricted SQL/shell or full Orchestrator handlers.
  Read `docs/operation-agent-workspace.md` for the full acceptance scope and known release/rollback
  gaps. Handle native function calls before parsing accompanying text; account verified raw
  provider usage before validating structured content. Never equate a passing fake workflow
  or a single synthetic model evaluation with production readiness or complete feature parity.
- The inference-receipt checkpoint separates strict raw usage from answer/metadata
  validation and classifies only allowlisted provider failures. Ordinary streamed chat uses
  the pinned OpenAI 2.53.0 SDK SSE decoder's private `_iter_events` boundary to avoid token-type
  coercion. Reverify it on SDK upgrades; never add a second HTTP request or refund unknown
  usage. A successful new synthetic diagnostic does not resolve historical lost calls or prove
  full model quality. The scoped production sidecar runs `6babf75`, retaining the
  `b81f458` receipt boundary and `a7752dc` diagnostic. Its compatible UI was also
  updated; main/audio remain unchanged. See the active profile release,
  `docs/operation-inference-receipts-checkpoint.md` and the cohort release checkpoint.
- The deployed decision-schema diagnostic adds at most three allowlisted field/code
  facts to existing private recovery feedback after verified usage. Never persist raw
  validation input/context/messages or extra-key names, and do not treat unrelated SDK
  metadata validation as a decision correction. It changes neither the two-step cap nor
  checkpoint/approval/budget contracts. The complete synthetic cohort diagnostic is not
  real source or broad model-quality acceptance. That historical v10-only increment
  had a `b81f458` rollback; it cannot execute new v11–v14. Use the active profile
  release's closed `2ea7b9a` fallback for current state, preserving all private history
  and unknown holds. See `docs/operation-cohort-quality-checkpoint.md` for the earlier
  scoped release and remaining acceptance.
- Topic-owned session memory preserves user constraints and bounded completed/cancelled Goal
  result excerpts across chat/task continuation. It is private historical context, not fresh
  evidence or permission; never inherit previous source approvals or budgets. Freeze it before
  generation and preserve it on idempotent replay. Do not silently shorten user constraints.
  Keep new chat fields outside legacy-readable JSON; supported application rollback retains
  native chat/Goal metadata and never downgrades a populated workspace schema.
  The separate native human action-review lane currently delegates only scoped synthetic MANA
  `growth_experiment` draft creation to the existing Growth lifecycle. Persist the exact typed
  intent before dispatch; replay/unknown outcomes only observe SQL and never reissue a write.
  Goal tools remain read-only. Keep receipt memory historical/minimized, checkpoint v3 for
  action context, and business outcome `not_measured`; sandbox verification is not conversion
  improvement. Unverified historical proposals are read-only in chat. See the release checklist.
- Goals default to `analysis_scope=current`; never silently relax freshness to finish them.
  Explicit native `saved_snapshot` Goals may complete a dated, full historical analysis after
  review, but cannot request/approve a live source read or claim current/business measurements.
  Persist that scope in checkpoint v4 and strip it from the closed legacy projection. The UI
  choice appears only in explicit Goal mode; a native availability failure must preserve it,
  not submit a different current-data objective. No source/schedule activation is implied.
- The default-disabled `OPERATION_GOAL_LIMIT_EXTENSIONS_ENABLED` adds explicitly human-confirmed
  continuation of newly tracked native Goals under separate server ceilings. Keep the original
  request/scope, costs, recovery caps and consumed reads; no automatic budget renewal or narrowed
  substitute objective. Unknown model holds block generation/resume/extensions. Accept verified
  usage after an in-flight control only as cost reconciliation, never its fenced-out decision.
  Tracked Goals use private checkpoint v10 and at most 120 tool records; untracked histories
  remain limited to twelve. The previous production `38292de` reader cannot execute v10; the
  closed legacy `2ea7b9a` fallback retains it with execution disabled. See
  `docs/operation-goal-limit-extensions.md`; scoped production activation and actual checks
  are recorded in `docs/operation-goal-limit-release.md`. Keep the feature default disabled
  outside that explicit sidecar configuration.
- Native Goals can find/page closed same-owner/topic/product tasks captured before the current
  task started. Task prose is historical context only; original saved report IDs must pass current
  agent/product/freshness checks separately. Exact cross-role user-text dedup retains all words
  and `also_kinds` labels; it is not semantic compaction. Checkpoint v5 binds these extended
  contexts to their immutable analysis scope. Do not claim automatic long-session compaction or
  unlimited history: legacy topics retain 100-message admission; native topics use explicit
  configured capacity. The 400-unique-context and byte limits still fail closed.
- Session capture streams all same-owner/topic/product closed Goal conditions before its
  frozen cutoff, independently of the public API's latest-100 results. Do not restore that
  result-page limit for user constraints. Keep only three bounded result checkpoints; preserve
  complete quotes/role aliases, strict old checkpoint validation and no inherited read grants.
  `OPERATION_WORKSPACE_CONTEXT_GOAL_LIMIT=10000` bounds local SQL capture explicitly;
  exceeding it refuses capture, never silently supplies a prefix as the whole history.
- Public progress is a private SQL event journal, atomically written with successful Goal
  changes. Its authenticated SSE transport observes only: reconnecting, disconnecting or
  losing a cursor must never restart/cancel a task or repeat a source read. Keep raw tool
  results, internal reasoning, credentials and action/read grants out of stream payloads.
  REST state remains authoritative for controls. Goal progress is not model token streaming;
  the separate default-disabled ordinary-answer stream carries only display-only drafts.
  Final schema/usage validation and policy still gate handoffs/actions; lost receipts retain
  unknown cost holds, and reconnecting observation never redispatches generation.
- Established native model continuations may take at most two shared recovery steps for
  verified priced invalid decisions/unloaded citations and classified local saved-text
  paging mistakes, with typed corrective feedback or exact durable tool receipts,
  unchanged objective/evidence/permissions, and existing step/global/Goal budgets. Unknown
  usage, timeouts, incomplete receipts, unsafe continuations and lost source reads still stop.
  Paging corrections require a verified existing native continuation, keep the denied call
  in SQL, and queue a new model decision, never redispatch a tool directly. Scope/access
  denials, oversized sources and SQL/provider failures must not enter that correction lane.
  Pending format feedback uses private checkpoint v7; the supported old image sees a closed
  projection, never the new queue. See the quality checkpoint in operation-agent-workspace.md.
- Native saved-report paging uses private checkpoint v8: contiguous, fingerprinted SQL reads,
  up to 4000 characters per page and 32000 per report, under unchanged context/step/cost bounds.
  A complete text read is not complete population coverage or a fresh measurement. Partial
  text/quality notes still cannot pass completion. Do not lose the exact tail in independent
  review, inherit read grants, or silently narrow an objective when its budget is exhausted.
  The supported `2ea7b9a` rollback sees a closed 5000-character evidence projection and retains
  full private state; the released `737b75d` native reader does not understand v8. Never choose
  that image as a v8 rollback target without a separately verified compatibility bridge.
- The default-disabled `OPERATION_WORKSPACE_REPORT_DISCOVERY_ENABLED` captures
  `find_saved_reports` only on new native Goals; scoped production `6babf75` explicitly
  enables it. Private v11 binds
  that immutable bit/scope; continuation v2 supports at most 120 tool positions only
  under existing separately confirmed limits. Old v1 keeps twelve; never upgrade a
  historical tool set/digest or auto-renew limits. Cursor
  positions are observation metadata, not grants, fresh measurements or complete catalog
  coverage. Preserve empty-page continuation and never treat the preview as the whole database.
  Only the closed `2ea7b9a` fallback with execution disabled is verified for v11/v2;
  `a7752dc` cannot execute it. Release the compatible stream UI with the backend. See
  `docs/operation-saved-report-discovery.md` for actual local checks and remaining acceptance.
- Goal evidence retains exact source whitespace for fingerprinted saved-text receipts;
  never trim a fixture/source to make contiguous paging pass. The independent local
  catalog diagnostic loaded the entire source but stopped on budget before analysis/review;
  it is not full quality acceptance. Do not replay it or replace its original receipt
  with a pass. Exact token preflight is not implemented. See
  `docs/operation-catalog-quality-checkpoint.md` for the measured trace
  and unchanged production boundary.
- The default-disabled `OPERATION_WORKSPACE_SNAPSHOT_REPLACEMENT_ENABLED`
  captures exact runtime-owned snapshot provenance only on new tracked native catalog
  Goals with continuation enabled. Private v12/v3 never upgrades old tasks. Replace
  only position/hash-proven runtime snapshots after exact user/evidence coverage;
  retain provider lookalikes, messages, opaque history and tool pairing. Changed tool
  projections or missing facts retain old snapshots; cost/context bounds still stop.
  Byte reduction is not financial/model-quality acceptance. The previous production
  `a7752dc` cannot execute v12/v3; only the closed `2ea7b9a` fallback is verified with
  native execution disabled. See `docs/operation-runtime-snapshot-replacement.md`.
- The default-disabled `OPERATION_WORKSPACE_PAGE_PROJECTION_ENABLED` captures
  exact saved-page references only on new tracked snapshot Goals, private v13/v4.
  Preserve the original SQL receipt and full evidence; project only an exact typed,
  hash/range-proved duplicate present in that same input. Private output provenance
  binds its runtime position and original SQL call; revalidate/rebind it, never use
  provider lookalike heuristics. Missing/changed retained proof stops before generation
  without refetch/replay. Byte reduction and fake completion are not model-quality or
  financial acceptance. Only closed `2ea7b9a` rollback is verified; `a7752dc`/`dfe098f`
  cannot execute v13/v4. See `docs/operation-saved-page-projection.md`.
- Goal model timeouts are explicit with preserved SDK/model-wall defaults 120/180
  seconds. Keep the model wall limit at most 240 (below the current 300-second SQL
  lease) and at least SDK + 10. External read timeout remains separate at 180;
  neither timeout adds retries or releases unknown holds. The independent v13
  diagnostic loaded full text but lost its eighth model receipt at timeout; it
  did not complete analysis/review and must not be replayed. See
  `docs/operation-goal-timeout-checkpoint.md`; no production setting was changed.
- Known noncompleted Goal responses preserve only closed completion facts in the
  existing waiting reason/event; never expose provider prose or use them to retry.
  Explicit `queued`/`in_progress` raw receipts are provisional even with numeric
  zero usage and must keep admission holds in Goals, blocking chat and streamed
  chat. A named completion SSE event cannot override a pending payload. The new
  independent diagnostic has a manually verified full draft but incomplete model
  review; its old zero-usage record lacks terminal metadata and is not proof of
  zero billing or permission to repeat it. See
  `docs/operation-completion-receipt-checkpoint.md`; production remains untouched.
- The default-disabled native review verdict is captured only on new tracked
  paged-catalog Goals, private v14/v5. Review receives every original input word,
  full evidence/qualifications and the stored draft, but returns bound quoted checks,
  plan positions and a verdict, never a rewritten artifact or permission. Literal
  coverage/hash checks are not semantic quality. Preserve the exact draft and private
  receipt; public HTTP projections omit it while SQL completion requires it. Revision
  feedback is historical model opinion, not evidence/grants. Old tasks never upgrade;
  only the closed `2ea7b9a` fallback is verified with execution disabled. See
  `docs/operation-review-verdicts.md`; scoped `6babf75` explicitly enables the contract
  on new eligible tasks without upgrading old ones.
- A selected native tool must survive actual compaction as the same canonical
  pending invocation before dispatch. Provider outputs cannot supply runtime/SQL
  tool receipts. Lost/consumed/mismatched pairing stops with verified priced usage,
  never decision-format recovery, source execution or automatic replay. Native
  protocols, hard bounds and approval authority remain unchanged. The long-topic
  real-model diagnostic retained the original condition/full source through three
  compactions but stopped at next-call budget admission before analysis/review;
  do not call it a full quality pass. Limit messages distinguish admission from
  actual spend and never replace the task with a smaller objective. See
  `docs/operation-continuation-pairing-checkpoint.md`.
- One full native catalog/analysis/review synthetic task passed with an explicitly
  deferred compaction trigger and unchanged hard caps. It is local, not a proven
  optimal default, causal root-cause finding, real MANA measure or broad readiness.
  See `docs/operation-compaction-quality-checkpoint.md`; do not replay old attempts.
- The scoped `6babf75` operational API/Goals worker and compatible UI release enables
  catalog discovery, exact snapshot/page projection, independent bound review and an
  explicit 24000 trigger. The code fallback remains 8000, hard bounds/timeouts and
  source settings/schedules unchanged. Two complete long-topic synthetic cases and
  one historical saved-child-sample production Goal passed with settled usage; they
  do not establish unlimited context, optimal cost, current parent analysis or full
  parity. All seven old Goals/three unknown holds retain exact fingerprints. Use
  only closed `2ea7b9a`/disabled native execution for the verified v14 fallback; never
  restore an old database over new history. See the active profile release and
  `docs/operation-long-session-deferred-checkpoint.md`; authenticated production-browser
  and broader source/owning-domain-action acceptance remain open.
- Evidence collection, report creation, observation periods and SQL-save times are
  different. Recent `collected_at` never proves current coverage or a storage date.
  Shared chat/Goal guidance clarifies these roles without changing grants/freshness.
  The eight-case matrix's timestamp defect remains a qualified pre-fix result;
  the subsequent two-case real-model check is qualified synthetic evidence, not
  overall readiness or a rewrite of that party. Chat/Goal source labels identify
  collection and cache timing, never confirmed observation coverage; malformed or
  future dates fail closed for display without provider calls or permission changes.
  See `docs/operation-evidence-date-checkpoint.md` and the original matrix report.
- Clearly distinguish current implementation from target architecture: `growth-agent` is loaded
  with `growth.advertising` and `growth.funnel.analyze`; `retention-agent` is loaded with the
  read-only `retention.engagement.analyze`. `marketing-agent` is a temporary compatibility alias
  and historical ID, not a second scheduler. Advertising writes use `fake_meta`; Growth funnel
  sources and experiment writes are fake/sandbox. Retention defaults to fake sources and has
  explicit live read-only Manakids Admin API, GA4 aggregate, canonical Firestore event, and
  operational Firestore aggregate adapters. Live Meta remains read-only.
  `retention.parents.analyze` is a separate manual-only, MANA-only minimized Parent API summary;
  opt-in source, one bounded page, shared six-hour read cooldown, no default schedule. Do not
  treat current tariffs as paid subscriptions or mix these reports into 360REC chat context.
- The `retention.parent_activity.analyze` and `retention.child_telemetry.analyze`
  capabilities are manual-only and default disabled; the scoped production sidecar enables them.
  Parent GA4 uses one approved stream,
  five bounded HTTP attempts and qualified ten-group breakdowns. Child telemetry uses two
  document-ID prefix samples of at most 100 each, never full-population statistics. No auto-
  refresh, schedule, listener, pagination or transport retry is permitted. Only validated saved
  reports are shared between MANA rooms; read/write authority is not shared. New native reads
  use private checkpoint v9 even after grant consumption. The previous `9020b06` reader cannot
  roll back v9; supported legacy `2ea7b9a` sees a closed projection and preserves private state.
  See `docs/operation-manual-analytics.md` for limits and outstanding GA4 live acceptance.
- Owner-confirmed MANA behavioral events (screens, button clicks, sessions and navigation)
  describe parents only. Keep backend child inventories separate; never use child counts as
  the denominator for parent activity/retention. User/event geography and profile cities are
  not payment-confirmed order geography or evidence of regional sales.
- Keep capability configuration, schedules, run locks, audit, and kill switches independently
  scoped by `agent_id` plus `capability_key`. New actions use domain-specific action enums and the
  typed executor/policy registries; do not expand advertising `ActionType` across domains.
- Preserve the delivery order after Growth: finish Retention & Loyalty risk/action capabilities,
  then Operations Orchestrator, then Technical Reliability last. Do not represent Orchestrator or
  Technical Reliability, or unbuilt Retention actions, as implemented until their handlers,
  integrations, policies, UI, and tests exist.
- Keep FastAPI route handlers thin. Existing compatibility logic remains in
  `app/services/`; new operational business logic belongs in
  `app/mana_operation_ai/application/`.
- Keep public compatibility contracts in `app/schemas/`, MANA AI contracts in
  `app/mana_ai/`, and operational contracts in `app/mana_operation_ai/domain/`.
- `app/mana_ai` must never import repositories, ORM models, operational agents, Meta
  integrations, action executors, or `app.mana_operation_ai`.
- Keep MANA AI HTTP transport in `app/api/routes/`; `app/mana_ai` must not import FastAPI.
- Keep one public endpoint-specific request and response schema per MANA AI capability. Do not
  reintroduce a generic capability-discriminated `/mana-ai/analyze` endpoint.
- Operational domain code must not import FastAPI, SQLAlchemy, Redis, Meta SDKs, or the
  OpenAI SDK.
- External providers implement typed application ports. Translate provider payloads at
  adapter boundaries.
- Keep settings in `app/core/config.py` and load them through `get_settings()`.
- Preserve DRY and Single Responsibility. Add abstractions only when they remove real duplication or isolate a concrete responsibility.
- Prefer async code for I/O-bound provider integrations.

## Quality gates

- Run `make lint` after code changes.
- Run `make typecheck` after changing typed Python or TypeScript code.
- Run `make test` after changing routes, schemas, services, configuration, or UI flows.
- Run `make verify` before handing off a completed checkpoint or release.
- Run `ruff check .` after code changes.
- Run `mypy .` after changing typed Python code.
- Run `pytest` after changing routes, schemas, services, or configuration.
- Do not call the real OpenAI API from tests; use fakes or dependency overrides.
- Do not call Meta write APIs from tests. Use the fake Meta adapter; live Meta tests are
  opt-in and read-only.

## Common commands

- Backend: `uvicorn app.main:create_app --factory --reload`
- Admin UI: `cd admin-ui && npm run dev`
- Apply migrations: `make migrate`
- Create migration: `make migration name=description`
- Lint: `make lint`
- Typecheck: `make typecheck`
- Tests: `make test`
- Full verification: `make verify`
- Fake Meta lifecycle demo: `make demo`

## Docker and deployment

- Keep Docker builds reproducible and small.
- Do not copy `.env` into images.
- Production must run with `APP_ENV=production`.
- Keep `/api/v1/health/live` usable as a container healthcheck.

## API conventions

- Use `/api/v1` for public endpoints.
- Return Pydantic response models for all route handlers.
- Convert provider failures into controlled HTTP errors; do not leak upstream stack traces or secrets.
- Keep OpenAI model names configurable through `OPENAI_MODEL`.
