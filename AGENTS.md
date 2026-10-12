# AGENTS.md

## Repository expectations

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
- The shared durable Goals workspace supports private analysis objectives, SQL checkpoints,
  bounded strong-model planning/investigation/review, pause/resume/steering and separately
  confirmed read-only delegation. It is not a fifth agent, a full Orchestrator implementation,
  or proof of business-outcome improvement. Keep unknown in-flight costs reserved and never
  automatically retry a lost source read. See `docs/operation-goals.md`.
- The opt-in native agent workspace is an unreleased local checkpoint, default disabled via
  `OPERATION_AGENT_WORKSPACE_ENABLED`. It adds conversational handoff, typed scoped evidence
  tools and in-flight steering, not unrestricted SQL/shell or full Orchestrator handlers.
  Read `docs/operation-agent-workspace.md` for the full acceptance scope and known release/rollback
  gaps. Handle native function calls before parsing accompanying text; account verified raw
  provider usage before validating structured content. Never equate a passing fake workflow
  or a single synthetic model evaluation with production readiness or complete feature parity.
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
  verified priced invalid decisions/unloaded citations, with typed corrective feedback,
  unchanged objective/evidence/permissions, and existing step/global/Goal budgets. Unknown
  usage, timeouts, incomplete receipts, unsafe continuations and lost source reads still stop.
  Pending format feedback uses private checkpoint v7; the supported old image sees a closed
  projection, never the new queue. See the quality checkpoint in operation-agent-workspace.md.
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
