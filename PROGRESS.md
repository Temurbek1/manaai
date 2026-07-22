# Implementation progress

Updated: 2026-07-22

All 15 platform checkpoints and the live Meta read-only milestone are complete. Live GET access was
verified against the selected account; live Meta writes are permanently forbidden and none was
attempted.

## Telegram OTP authentication baseline

Status: recorded before authentication changes on 2026-07-22

- Git baseline: clean `feat/nextjs-admin-panel` at `192bb6f`, matching its remote branch. Telegram
  work starts from that exact commit on the separate `feat/telegram-otp-auth` branch.
- The human Next.js login currently asks for an internal API key, development actor ID, and role.
  The browser stores these values in module memory and sends `X-API-Key`, `X-MANA-Actor-ID`, and
  `X-MANA-Role` on every request; refresh intentionally loses the session.
- FastAPI has no administrative-user, OTP-challenge, or server-session tables/cookies. In
  production, shared role-specific API keys resolve to synthetic actors; local mode trusts the
  caller-supplied actor/role headers. RBAC and self-approval checks consume that resolved actor.
- The shared application and operation role keys remain necessary for compatibility APIs,
  service-to-service clients, automation, and existing hermetic tests. They will remain as an
  explicit technical authentication path but will be removed from the human browser flow; normal
  local runtime will no longer trust browser-selected identity or role.
- The generated OpenAPI contract exposes the current operation session response. The Next.js
  client has no cookie/CSRF transport yet. Compose already keeps the browser same-origin through
  the private FastAPI rewrite and enables credentialed CORS.
- No existing users can be mapped automatically to Telegram because the current identities are
  shared-key role aliases rather than user records. The configured bootstrap Telegram IDs will
  create the first durable admins idempotently.
- The ignored local `.env` contains a Telegram bot token under the legacy variable name
  `BOT_TOKEN`; its value was not read. Runtime configuration will prefer
  `MANA_TELEGRAM_BOT_TOKEN` while accepting that legacy alias without logging or modifying it.
- Migration plan: add typed users/challenges/sessions/audit records and Alembic migration; add
  HMAC-protected OTP policy, persistent rate limits, Telegram and isolated fake senders, cookie and
  CSRF authentication, user-management APIs/UI, browser E2E, deployment configuration, and full
  auth/admin/audit verification before normal push.

## Next.js migration baseline

Status: recorded before migration on 2026-07-22

- Git branch at audit time: `main`, tracking `origin/main` and ahead by 25 existing local commits.
  The configured remote is `origin`; no staged changes existed.
- The worktree already contained the completed but uncommitted MANA OPERATION AI platform,
  security, persistence, Meta read-only validation, deployment, documentation, tests, and admin UI
  work described by the checkpoints below. Those changes predate the Next.js migration.
- The original admin UI was an entirely untracked React 19 + strict TypeScript Vite SPA under
  `admin-ui/`, with a single `App.tsx` router, in-memory role-key session context, SWR-backed pages,
  Vitest coverage, an nginx production image, and a Vite development proxy to FastAPI.
- Next.js migration changes at this baseline: none. Vite files, dependencies, build output shape,
  Docker runtime, browser scripts, Make targets, and documentation were still unchanged.
- Sensitive/runtime inputs remain outside Git: `.env`, databases, generated live evidence,
  verification screenshots, and the supplied PDF source material will not be committed.
- Planned history: first preserve the pre-existing platform/backend, Meta safety, original admin UI,
  deployment, tests, and documentation in logical commits; then commit the Next.js foundation,
  route/page migration, test and E2E expansion, and deployment/documentation verification as
  separate migration commits on `feat/nextjs-admin-panel`.

## Next.js admin migration

Status: completed and verified

- Replaced the single-view Vite SPA with Next.js 16 App Router routes for overview, Marketing,
  approvals, runs/audit, and agent management. Server route/layout boundaries compose focused
  interactive feature clients.
- Preserved server-verified, memory-only authentication and all RBAC restrictions. Added controlled
  401 expiry, self-approval denial, fresh approval/kill-switch reads, and inline confirmation for
  global/per-agent emergency controls.
- Preserved the generated FastAPI contract and same-origin browser transport. Private
  `FASTAPI_BASE_URL` config powers local/Docker server rewrites without exposing credentials.
- Migrated Vitest coverage to 16 Jest scenarios and updated the real FastAPI/fake-provider browser
  lifecycle for native routes, direct nested refresh, keyboard behavior, and mobile layout.
- Replaced the nginx/static image with Next.js standalone output and `/healthz`; removed Vite
  configuration, entry points, dependencies, and obsolete runtime files.
- Added `make admin-verify`, standalone production smoke, Vite-absence validation, Docker build,
  and an opt-in non-mutating live Meta admin-page smoke.
- Replaced the stale version-specific external report-packager path with a repository-owned,
  typed, secret-scanning portable HTML generator and browser smoke.
- `make admin-verify` passes synchronized OpenAPI generation, Prettier, ESLint, strict TypeScript,
  16 Jest tests, optimized/standalone builds, npm and secret audits, fake-provider browser E2E,
  Vite-absence validation, and the non-root Docker image build.
- `make audit-verify` passes all repository, mutation, dependency, SQLite/PostgreSQL migration,
  browser, production, and Docker gates. The opt-in bounded live workflow and real Marketing-page
  desktop/mobile smoke pass with zero proposals or executions.

## Checkpoint 1 - Repository audit and baseline

Status: completed

- Inspected the FastAPI routes, services, schemas, SQLite persistence, Meta/OpenAI integrations,
  tests, configuration, Docker deployment, and both supplied PDFs.
- Recorded supported Meta reads, entity coverage, token/configuration handling, missing write and
  worker behavior, risks, and architecture decisions in `docs/current-state-audit.md`.
- Fixed the baseline test leak in which the ignored developer `.env` changed test behavior.

Verification: original gates reproduced; the final hermetic suite is included below.

## Checkpoint 2 - Architecture decision and bounded contexts

Status: completed

- Added physical `app/mana_ai` and `app/mana_operation_ai` boundaries.
- MANA AI exposes payload-only typed capability contracts and has no operational imports.
- Added an AST import-boundary test and boundary documentation.

Verification: architecture tests pass in the full suite.

## Checkpoint 3 - Generic operation-agent core

Status: completed

- Added typed domain contracts, registries, provider ports, lifecycle results, health, audit, and
  explicit run/action state machines.
- Agent and ads-platform registration are extension based; the core has no agent-name dispatch.

Verification: domain, registry, transition, and architecture tests pass; strict mypy passes.

## Checkpoint 4 - Persistence and migrations

Status: completed

- Added async SQLAlchemy 2 persistence for agents, versioned configurations, schedules, runs,
  snapshots, metrics, findings, recommendations, proposals, approvals, executions, verification,
  reports, audit, controls, and locks.
- Added Alembic revision `a57f606d9211_create_operation_agent_platform.py`.

Verification: repository integration tests pass; a clean migration creates 19 tables including
`alembic_version`; `alembic check` reports no new upgrade operations.

## Checkpoint 5 - Meta provider adapter

Status: completed

- Wrapped the legacy client in a provider-neutral typed adapter and added a mutable fake Meta
  provider for full lifecycle tests.
- Added safe breakdown query plans, pagination, request diagnostics, attribution, rate-limit
  handling, retry/backoff, normalization, unavailable semantics, and a separate live-write gate.

Verification: adapter pagination, 429, normalization, redaction, and write-gate tests pass.

## Checkpoint 6 - Marketing analytics engine

Status: completed

- Added deterministic Decimal KPI calculation, baseline comparison, audience/region/placement/time
  ranking, creative quality/fatigue, budget constraints/waste, anomalies, and data-quality findings.
- Missing evidence remains explicitly unavailable; LLMs do not calculate financial metrics.

Verification: metric, threshold, ranking, and unavailable-data tests pass.

## Checkpoint 7 - Recommendations and policy engine

Status: completed

- Added all required typed recommendation kinds: increase/decrease, pause/resume, scale/disable
  audience, maintain, observe, and propose-test.
- Added versioned typed configuration and policy checks for thresholds, confidence, action allow
  lists, approvals, budget limits, cooldowns, and daily execution limits.

Verification: recommendation and policy tests pass.

## Checkpoint 8 - Approval, action, and verification lifecycle

Status: completed

- Added approval expiry, RBAC, self-approval prevention, idempotency, fresh provider-state checks,
  stale failure, dry-run/live gates, provider execution, re-read verification, and full audit.
- Added database-backed provider-object locking around policy recheck, read, write, and verification
  so concurrent proposals cannot race on the same advertising object.

Verification: API tests cover approvals, dry-run, stale proposals, object-lock contention, explicit
retry, kill switches, and permissions; the fake-provider E2E applies and verifies a real fake write.

## Checkpoint 9 - Scheduler and reports

Status: completed

- Added configurable six-hour analysis and nightly report schedules plus reconciliation, retention,
  locking, retries, timeouts, and approval expiry maintenance.
- Nightly reports persist structured and human-readable forms and use a channel-neutral notification
  port; reports expose pending and failed actions and data quality.

Verification: scheduling/timezone and nightly-report API tests pass.

## Checkpoint 10 - Admin API

Status: completed

- Added versioned internal endpoints for dashboard, generic agents, statuses, configurations and
  versions, schedules, runs, snapshots, findings, recommendations, proposals, approvals, execution,
  reports, health, audit, and global/per-agent kill switches.
- Routes use typed response schemas, pagination/filtering/sorting, correlation IDs, RBAC, and
  controlled errors; manual runs return 202 and execute outside the request handler.

Verification: FastAPI API tests and generated OpenAPI validation pass.

## Checkpoint 11 - Admin UI

Status: completed

- Added a Next.js 16 + React 19 + strict TypeScript admin app with registry-driven navigation, dashboard,
  Marketing Agent, approval, run/audit, and agent-management pages.
- Added responsive configuration/schedule controls, health/KPIs/entities/breakdowns, safe bulk
  decisions, action history, reports, emergency controls, and a generated OpenAPI contract.

Verification: Prettier, Next-aware ESLint, strict TypeScript, 16 Jest flows, production and
standalone builds, zero npm audit findings, and browser testing of
Overview/Marketing/Approvals/Runs all pass, including the Docker and repository-wide gates below.

## Checkpoint 12 - End-to-end tests

Status: completed

- E2E proves snapshot collection, deterministic analytics, best/weak creative, cheap/expensive
  audiences, recommendations, approval, fake provider change, verification, audit, and report.

Verification: `make demo` passes (1 test).

## Checkpoint 13 - Security review

Status: completed

- Added safe production defaults, independent Meta write gate, role keys, stable production actor
  identity, per-agent/global kill switches and limits, structured logging, and secret redaction.
- Tests isolate the local `.env`; UI/API/log contracts do not return tokens or keys.

Verification: redaction/security tests and repository secret-pattern scans pass. No `.env` was read,
printed, copied into an image, or added to Git.

## Checkpoint 14 - Refactoring and duplication removal

Status: completed

- Kept provider calls in adapters, use cases in application services, persistence in infrastructure,
  and thin API routes; moved schedule calculation and shared registry behavior into focused modules.
- Removed implemented-slice TODOs, placeholder passes, disabled tests, and central provider/agent
  conditionals.

Verification: Ruff, mypy, import-boundary tests, and marker scans pass. Alembic's standard template
retains only its generated empty-migration `pass` fallback.

## Checkpoint 15 - Final documentation and verification

Status: completed

- Added all required architecture, boundary, platform, Marketing Agent, safety, admin, runbook,
  testing, and capability-matrix documents plus `.env.example`, root `AGENTS.md`, and Make targets.
- Capability matrix covers both PDFs and distinguishes implemented, foundation, and planned work.
- Added production API/standalone-Next.js admin Docker images and Compose deployment with
  migrations and liveness.

Final evidence is recorded in `docs/live-read-only-test-evidence.md`. The final opt-in Make target
passed Ruff/ESLint, strict Python/TypeScript checks, 95 hermetic backend tests, 16 frontend tests,
focused and mutation safety suites, SQLite/PostgreSQL migrations, dependency/secret/schema/Compose
checks, production build, browser E2E, the marked live GET test, live nightly workflow, read-only
admin desktop/mobile smoke, and portable report verification.

## Live Meta read-only milestone

Status: completed on 2026-07-22

- Validated Graph/Marketing API `v25.0`, token health, and exactly one accessible hashed account
  alias through GET-only calls.
- Proved bounded structure/Insights compatibility for 13 query plans. The completed seven-day period
  was genuinely empty, so the agent emitted one `insufficient_data` finding and two advisory
  recommendations without proposals or executions.
- Persisted reversible calibration configuration version 7 in the initial validation and version 13
  in the final immutable rerun, with every account override unavailable/inherited plus
  structured/human nightly report evidence.
- Generated a sanitized canonical artifact and portable HTML report that passed source, desktop,
  mobile, overflow, and external-request verification.
- Added explicit live-test opt-in, manual Ads Manager reconciliation placeholders, least-privilege,
  attribution, rate-limit, retention, calibration, and incident runbooks.

Remaining human step: enter Ads Manager UI values in `docs/meta-data-reconciliation.md`. This does
not block API read-only operation, but it blocks any claim of API/UI numeric reconciliation.
