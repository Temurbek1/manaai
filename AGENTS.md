# AGENTS.md

## Repository expectations

- The owner clarified the testing restriction on 2026-10-23: free tariffs may be
  granted only to explicitly designated test accounts, never ordinary customers.
  Keep `MANA_CONVERSION_TRIAL_GRANTS_ENABLED=false` by default; enabling conversion
  alone does not authorize its write lane or a production rollout. Automated
  tests remain fake/MockTransport-only. Any scoped live test requires a fresh
  exact-account preflight, durable one-shot dispatch claim and no repeat of a
  known/unknown grant. Do not reset paid/trial state or pick arbitrary customers
  to make a test pass. Parent `4`'s already consumed grant must not be repeated.
  The test exception does not authorize shared production changes or restarts.

- A completed 2026-10-23 read of `/api/v1/tariffs/` returned five real paid plans,
  including tariff `3`, 60,000 UZS /30 days. Missing-catalog claims below are
  historical. The new catalog port/adapter and ordinary-price comparison are
  local only, not runtime-wired, a durable read-admission layer or an approved
  campaign. Never infer renewal, checkout or discount terms from monthly flags,
  `old_price` or provider descriptions. Future wiring must durably claim before
  HTTP and preserve unknown/replay boundaries. Read
  `docs/mana-conversion-catalog-source-checkpoint.md`. No new live read, offer
  activation, model party, contact or release is authorized by these local tests.

- One owner-authorized live manual test on reset parent `4` granted one non-paid
  Maxsus day on 2026-10-23, purchase `74311`; GET confirmed the receipt and consumed
  trial. Never repeat that write or invent a parent-chat acceptance. The original
  empty tariff had `is_paid=null`, which remains unknown for automatic policy;
  the manual test relied only on the owner's explicit reset/test authority.
  New optional grant metadata is validated without adding it to legacy SQL JSON.
  Read `docs/mana-conversion-grant-live-checkpoint.md`. This is not live Parent-Touch
  publication, real paid conversion, all-parent coverage or a deployment approval.

- On 2026-10-22 one explicitly requested test-parent `4` login/GET returned all
  three account fields and passed the existing strict adapter. Missing-field
  evidence below is historical, not the current live contract. The owner first
  clarified that these fields were added to grant POST responses; their later
  presence in Parent List is now independently observed. Read
  `docs/mana-conversion-live-account-checkpoint.md`. Do not repeat the read or
  issue a grant to reproduce it. Field presence does not establish free-start
  semantics, all-parent coverage, activity/consent, real offers or release authority.

- The subsequent `9b343d3` postfix has a separate settled eight-generation RU/UZ
  party (standard-uncached estimate $0.02096025) and actual current-image v9/v10
  hermetic checks. Narrow financial/action checks retain a Russian-trial phrasing
  caveat; no broad quality or production capacity is implied. Original party1
  remains unchanged/qualified. The full goal is externally blocked on deployed
  source fields, authoritative population/activity/consent events and real offers.
  Read `docs/mana-conversion-postfix-checkpoint.md`; do not activate a source,
  contact or release, repeat paid cohorts, or replace missing real integration
  with more synthetic milestones. Wait for the missing owning-backend inputs.

- The bounded local commercial real-model party completed four isolated RU/UZ
  cases with eight settled generations, standard-uncached estimate $0.02035250.
  Paid terms passed narrow manual checks; free-day billing wording is qualified,
  not an all-four semantic pass. Preserve every original private artifact and
  unknown/cost boundary. The subsequent four-language template/guidance correction
  scopes no-payment/no-transaction to the grant itself and invents no future
  renewal fact. Its original checkpoint had no postfix acceptance; see above. Read
  `docs/mana-commercial-model-quality-checkpoint.md`; separate 2000-token case
  ledgers do not prove production shared-budget capacity. Never replay old paid
  parties or treat a fake pass as business/source/contact release acceptance.

- The subsequent local `MANA_CONVERSION_ACCOUNT_SOURCE_ENABLED` lane defaults
  off and adds private v10. Eligible explicit backend events claim SQL before
  one bounded exact-parent read; replay/GET/restart never reread. Six-hour parent
  cooldown and rolling 24h global ceiling (100 by default) include failed claims;
  pending/unknown reads never auto-retry or clear at midnight. Source facts only
  veto the full backend snapshot; they do not classify overlapping entitlements,
  invent free-period starts, consent/activity or paid conversions. Gate offer
  publication, frozen availability, trial claims and unclaimed marketing push.
  Only current same-code closed-v10 retains this history; v9/production images
  cannot read it. No production activation, refresh or all-parent producer is
  included. See `docs/mana-conversion-account-admission-checkpoint.md`.
  The subsequent hermetic `8532a9f` image verifies v10 and the prior v9 mode,
  including unchanged unknown source/model holds through same-image closure and
  reconstruction. It is not old-image rollback, real model/source/contact quality
  or production-budget throughput acceptance. See
  `docs/mana-conversion-account-candidate-checkpoint.md`; the harness's synthetic
  20,000 safety ceiling never changes production's shared 2000/day setting.

- The subsequent local account-only Parent List adapter strictly requires the
  newly announced `is_paid`, `created_at` and `agent_trial_used` keys, retaining
  explicit null as unknown and rejecting coercions. Its original `c7c411d`
  checkpoint was not runtime-wired; see the later local v10 lane above. Neither
  increment is scheduled, an all-parent producer, contact authority or a release. A bounded
  post-announcement production check still lacked all three keys. Do not turn
  `created_at` into a free-period start without confirmed semantics, or one
  selected non-paid record into proof that no overlapping paid entitlement exists.
  See `docs/mana-conversion-account-source-checkpoint.md` before wiring it: durable
  exact-event admission must precede any live read so replay/restart cannot reread.

- The subsequent local `MANA_CONVERSION_CONVERSATION_ENABLED` lane defaults off
  and adds private v9. Freeze only new parent turns' exact last-published offer/
  availability and known grant receipt. Model text never activates days or pays.
  Backend acceptance must match both the latest offer and the reply's frozen
  binding; old turns never recapture. Only confirmed dates and fresh explicit
  account facts allow the new expiry reason, with paid offers only. Terminal
  non-paid result messages have their own recorded time and assistant-only SQL
  publication, never a fake child notice, model receipt or implicit push consent.
  Current closed-v9 preserves all history/holds; v8/`f8d095e` images cannot read it.
  See `docs/mana-commercial-conversation-checkpoint.md`; source population feed,
  candidate release and measured paid conversion remain unproven.

- The 2026-10-21 conversion/proactive increment is local, default disabled and
  not a production contact release. Parent-Touch remains the only speaker and
  may initiate before the first parent text only with fresh backend-verified
  language and separate safety-chat/push permissions. Never invent a parent
  message, locale or consent. Private SQLite v8 atomically commits assistant
  history and a privacy-minimized push outbox; freeze a one-shot SQL claim before
  the documented Manakids send. Provider queueing is not delivery, zero devices
  is not success, and unknown/submitting attempts never auto-retry after restart.
  Revalidate current marketing consent/paid state/offer before a commercial push.
  Current closed v8 readers preserve history/holds; old production `f8d095e`
  cannot be used as a v8 rollback reader. Keep the old production and all source
  refresh settings unchanged. See `docs/mana-parent-proactive.md`.
  Agent tariff grants are explicit parent-accepted, non-paid free days, never
  payment/transaction creation or proof of paid conversion. Current Parent List
  does not expose authoritative paid/free status, activity or contact settings;
  do not infer them from tariff names or claim all real parents are tracked.
  Read `docs/mana-conversion-work-in-progress.md` for unfinished goal obligations.

- On 2026-10-20 the owner separately authorized the scoped family-agent production
  release and explicitly set Child-Safety's total server daily budget to 2000 tokens
  for all parents. `f8d095e` now runs in the existing isolated parent-chat sidecar,
  with Parent-Touch/safety/review-first enabled, same key/volume and private v6.
  Chat remains 2000 raw tokens per parent/day. Automatic processing means new
  messages/submitted observations, not Firebase/GA4 bulk refresh or OPERATION work.
  See `docs/mana-family-agents-release.md` for actual image/backup/closed-reader
  boundaries and qualified verification. Old no-release statements below describe
  their historical local checkpoints, not permission to downgrade new history.
  The initial GitHub push was refused for `samanwirst` (pull-only). The owner then
  selected `samango1` with verified repository Write access; the feature branch
  was successfully published on 2026-10-20. No credential bypass, force push or
  additional production restart was used. Keep the initial failure historical.

- The owner started a separate application-family agent redesign on 2026-10-20:
  Parent-Touch is the only parent-facing speaker/communication manager;
  Child-Safety owns the existing protective analyses and proposes internal questions.
  Trigger safety work on new child data/parent messages, never unchanged-context
  periodic inference. Parent-Touch retains 2000 daily tokens; Child-Safety requires
  a separate explicit server budget. See `docs/mana-family-agents.md` for actual
  implemented versus unfinished API/runtime/worker scope. This does not replace
  the four administrative OPERATION agents or authorize deployment/source refresh.
  Local default-disabled runtime now wires ten private Child-Safety endpoints,
  SDK-raw metering, existing analysis validation and a SQL event worker. Its v5
  private adapter adds dated minimized report context and host-owned notices to
  the earlier v4 outbox, normalized input dedup and separate explicit server/
  parent/job token claims. Only Parent-Touch publishes questions or notices.
  Urgent validated ALERT/BLOCK assessments may interrupt an awaiting question,
  never create a second question or execute controls. Ordinary notices coalesce
  and can remain deferred without automatic paid repetition. They are not push
  delivery or an emergency-response guarantee. Freeze context at admission, keep
  exact signal/evaluation/processing dates and all quality notes, and recheck
  fresh connected-child ownership before inference. Unknown calls retain holds
  across restart/day changes; never requeue or erase them. SDK strict-schema
  conversion uses pinned 2.53.0's private helper; no parse-first billing or retry.
  V5 safety-off mode uses an explicit broker-only reader; disabling Parent-Touch
  uses a history/replay-only reader. Neither downgrades schema nor starts a safety
  worker. Old production images refuse v5: same-candidate closed profiles are
  distinct from an old-image rollback. No deployment is approved here.
  See `docs/mana-family-agents-integration.md` for backend wiring and the latest
  checkpoint for actual gates/candidate/quality limits. Do not mistake synthetic
  SDK/runtime passes for real-family quality or delivery. Standalone docs exporters
  must resolve this checkout, not an unrelated editable Python installation.
  The subsequent slot/language increment is recorded in
  `docs/mana-family-conversation-checkpoint.md`. Parent-Touch's provider schema
  contains text/bool slots, never runtime UUIDs; bind them only to the frozen SQL
  choices after metering. Preserve dated evidence/qualifications and known notice
  UTC observation dates in text. Conservative RU/UZ/EN hints are presentation only;
  neutral replies inherit one same-family reference, not source/action authority.
  New private safety context v2 freezes pending needs/recent bound answers and an
  optional typed review-only bit. V1/earlier v2 never upgrade. Old `1bea31c` workers
  cannot execute new v2 even though SQL remains v5; use current closed profiles.
  New default-disabled roles have isolated configurable GPT-5.4 speaker /mini safety
  defaults, leaving old OPENAI_MODEL/chat/audio/stateless paths unchanged. Separate
  safety limits remain mandatory. A qualified RU/UZ seeded-question pass is not
  broad safety quality or a real-model specialist-originated-loop pass. Preserve
  negative parties, known costs, deferrals and unknown holds; never replay them.
  Exact-context quota refusals have no automatic next-day redispatch. The explicit
  backend continuation in `docs/mana-family-specialist-checkpoint.md` admits only
  prior-day pre-generation quota refusals with no receipt/hold and unchanged
  primary choice/language context. Never apply it to unknown or paid calls.
  Real-model specialist loops pass mechanically but still expose independent
  speaker judgments before the new specialist review. Implement a captured durable
  review-first workflow rather than treating prompt tuning as owning-role quality.
  No release is authorized by that historical checkpoint.
  The subsequent local default-disabled `MANA_PARENT_TOUCH_REVIEW_FIRST_ENABLED`
  implements `/parent-touch/messages` admission/status and private SQLite v6.
  New captured messages wait for Child-Safety before one claimed Parent-Touch
  communication; old synchronous turns/digests never upgrade. Preserve language,
  exact bounded guidance/dates, fresh reviewed-child ownership and separate budgets.
  Five-minute preparation expiry must fence queued/late review publication without
  refunding known/unknown costs. GET/replay, restart and midnight never regenerate
  a claimed/failed communication. V6 supports current closed broker observation/
  exact replay and history-only profiles, not old v5/production image rollback.
  See `docs/mana-family-review-first-checkpoint.md` for actual gates and qualified
  RU/UZ synthetic evidence; this is not broad real-family or release acceptance.

- The parent application chat is separate from the operational-agent workspace.
  The original isolated production release was `mana-ai-parent-chat:f2c023f` on
  `ai.360rec.uz`, with exact chat ingress and a separately issued backend token.
  See `docs/mana-parent-chat-release.md` for actual checks/rollback; main/audio,
  operations, UI and scheduler containers are unchanged by that release.
  Keep one private durable history and daily input+output allowance per canonical
  MANA profile parent ID. Backend-only credentials must not be shared with mobile,
  360REC or general inference clients. The production chat can run as an isolated
  sidecar: exact `/api/v1/mana-ai/chat` ingress only, its own key/volume, no scheduler,
  operational database, Firebase/GA4 refresh or audio worker. Unknown submitted
  model usage remains held; never retry, refund or erase it automatically. See
  `docs/mana-parent-chat.md`. This release does not resume the owner's paused broad
  operational workspace goal or ship its preparation-admission work.

- Work in English for code, comments, commit messages, and identifiers.
- User-facing documentation may be Russian when the product audience is Russian.
- Keep the project production-oriented: explicit configuration, typed schemas, clear errors, and no hidden globals.
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
- Clearly distinguish current implementation from target architecture: `growth-agent` is loaded
  with `growth.advertising` and `growth.funnel.analyze`; `retention-agent` is loaded with the
  read-only `retention.engagement.analyze`. `marketing-agent` is a temporary compatibility alias
  and historical ID, not a second scheduler. Advertising writes use `fake_meta`; Growth funnel
  sources and experiment writes are fake/sandbox. Retention defaults to fake sources and has
  explicit live read-only Manakids Admin API, GA4 aggregate, canonical Firestore event, and
  operational Firestore aggregate adapters. Live Meta remains read-only.
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
