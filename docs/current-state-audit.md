# Historical pre-implementation baseline audit

This document records the repository baseline before the operation vertical slice. It is retained
as implementation history and is not a statement of current production readiness. See
`adversarial-audit.md` for the independently verified current state.

Audit date: 2026-07-22

## Repository baseline

The repository is a small FastAPI 0.116 service on Python 3.12 with a conventional
`app/api`, `app/schemas`, `app/services`, and `app/core` layout. It has no frontend,
task runner, ORM, migration system, role model, or operational-agent abstraction.
Persistence is implemented with direct `sqlite3` calls against the path configured by
`MARKETING_DATABASE_PATH`.

The existing public API is versioned under `/api/v1` and provides:

- liveness and readiness probes;
- two OpenAI test endpoints;
- raw marketing record ingestion and filtering;
- Meta asset discovery and synchronous/async Insights ingestion;
- a deterministic marketing graph and pattern engine;
- an OpenAI Structured Outputs marketing report and report evidence retrieval.

The baseline gates on 2026-07-22 were:

- `ruff check .`: passed;
- `mypy .`: passed in strict mode;
- `pytest -q`: 31 passed, 1 failed. The failing configuration test inherited
  `META_ACCESS_TOKEN` from the developer's ignored `.env`, exposing a test-isolation
  defect. No secret value appeared in test output.

## Existing Meta Ads integration

`app/services/meta_marketing_client.py` is an async `httpx` Graph API client. The API
version, fields, page size, maximum pages, attribution windows, account IDs, business
ID, app ID, and access token are configured through `Settings`. The access token is a
Pydantic `SecretStr` loaded from `META_ACCESS_TOKEN`; it is added only to outbound
requests and is not returned by the configuration endpoint.

Supported read operations are:

- app and business metadata;
- owned pixels;
- owned/client/configured ad accounts;
- campaigns, ad sets, ads, and ad creatives;
- custom conversions and custom audiences;
- synchronous Insights at account/campaign/ad-set/ad levels;
- Meta async Insights job creation, status polling, and result ingestion;
- Graph pagination through `paging.next` with a configured maximum page count.

Existing normalized calculations cover spend, impressions, reach, clicks, link clicks,
conversions, conversion value, CTR, frequency, CPC, CPM, CPA, and ROAS. Existing
patterns cover spend concentration/waste, efficiency, outliers, fatigue, breakdown
segments, creative/audience/hierarchy rollups, delivery status, measurement health,
unmapped conversion signals, trends, and data-quality gaps.

The existing implementation assumes `ads_read` and `business_management` for the
documented server-side system-user workflow. App review and business verification may
also be required. No write operation, `ads_management` workflow, approval, idempotency,
or post-write verification exists. There is no retry/backoff or explicit rate-limit
classification, request-ID diagnostics, supported-breakdown matrix, locking, or
background synchronization. Sync is performed inside HTTP requests.

## Product-document findings

`MANA AI.pdf` defines privacy-sensitive mobile inference capabilities: safety
monitoring, family digest, adaptive screen time, location intelligence, content and
fraud protection, AI/game safety, parent and child copilots, family agreements, and
behaviour anomaly detection. These capabilities operate on payload data supplied by a
mobile application and must not be coupled to company operations or repositories.

`MANA OPERATION AI (1).pdf` defines an internal agent system: marketing analysis every
six hours and nightly reporting, conversion, retention/referral, technical analysis,
admin analytics, and a future orchestrator that correlates and delegates work across
agents. Operational agents need repositories, integrations, scheduled work, approvals,
actions, verification, reports, and auditability.

## Problems and risks

1. Product inference and operational marketing share one top-level service namespace;
   there is no enforceable bounded-context boundary.
2. Domain contracts are API Pydantic schemas and business logic depends directly on
   concrete SQLite, OpenAI, and Meta implementations.
3. Direct SQLite schema creation on application startup cannot reliably evolve or prove
   clean-database migrations.
4. Marketing money and ratios use binary floating point rather than `Decimal`.
5. Meta payload dictionaries leak beyond the integration boundary.
6. HTTP-triggered sync is not protected by retries, timeouts at the job level, locks, or
   recovery.
7. There is no lifecycle persistence, state-machine enforcement, configuration
   versioning, policy evaluation, approval, execution limit, kill switch, or audit
   trail.
8. API-key authentication has no operational roles, actor identity, or self-approval
   protection.
9. The test suite can inherit local `.env` secrets and therefore is not hermetic.
10. There is no admin UI or typed frontend API contract.

## Architecture decisions

- Preserve all existing `/api/v1/marketing` behavior while adding two explicit Python
  packages: `app/mana_ai` and `app/mana_operation_ai`.
- Permit both contexts to depend only on narrowly named technical facilities in
  `app/core` and existing provider-neutral services; never place business logic in a
  generic `shared`, `utils`, or `helpers` module.
- Enforce the MANA AI import boundary with an automated AST test.
- Implement the operational context as domain, application ports/use cases,
  infrastructure adapters, API, background execution, and a separate `admin-ui`.
- Introduce SQLAlchemy 2 async persistence and Alembic for operational tables while
  retaining the legacy SQLite repository during the backwards-compatible transition.
- Keep provider responses inside advertising infrastructure adapters. The Marketing
  Agent consumes provider-neutral typed snapshots and actions.
- Use deterministic `Decimal` analytics for all financial metrics. The model gateway is
  optional interpretation/reporting infrastructure and never calculates metrics or
  invents missing values.
- Default to dry-run, permanently forbidden live Meta writes, approval-required fake-provider
  actions, no implicit spend permission, and global/per-agent kill switches.
- Provide a fully mutable in-memory fake Meta adapter for tests and demonstrations; live Meta is a
  credentialed, bounded, read-only provider with no execution capability.
- Use a documented in-process scheduler for a single local/API process, with database
  locks and manual endpoints. Production multi-replica deployments must run one
  scheduler process or replace the runner behind its port.
