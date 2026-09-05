# MANA platform architecture

## System shape

MANA is one deployable FastAPI service with two physically separated bounded contexts. They
share only safe technical facilities such as settings, request tracing, structured logging,
provider-neutral model access, and error conventions.

Within MANA OPERATION AI, the target product topology is exactly four top-level agents:
Operations Orchestrator, Growth & Conversion, Retention & Loyalty, and Technical Reliability.
Capabilities such as advertising, conversion, upsell, referral, admin analytics, and incident
creation live inside these agents. The authoritative boundaries and action model are defined in
`docs/operation-agent-model.md`.

```text
Mobile payload -> app/mana_ai -> validation -> AI processing -> typed response

Browser -> Next.js same-origin rewrite -> FastAPI Telegram OTP/session API
                                      -> auth application ports
                                      -> SQLAlchemy + Telegram Bot API adapters

Admin/API/scheduler -> app/mana_operation_ai/application
                    -> domain contracts and state machines
                    -> capability registry and typed source/action ports
                    -> SQLAlchemy, Meta Graph, fake Meta/funnel/experiment, logging adapters
```

Target operational control flow:

```text
Administrator -> Operations Orchestrator -> persisted goals/plans/tasks
                                      |-> Growth & Conversion capabilities
                                      |-> Retention & Loyalty capabilities
                                      `-> Technical Reliability capabilities

Operational sources -> immutable ingestion -> normalized facts/evidence -> agent analysis
Agent recommendation -> typed action -> policy/approval -> executor -> verification -> outcome
```

The orchestrator coordinates but does not bypass domain ownership. Provider, billing, messaging,
issue-tracker, and deployment actions are performed only by the owning agent's scoped, typed
executor. All four agents are expected to act as well as analyze, with risk-appropriate policy and
approval. Current live Meta remains read-only. The loaded operational agents are `growth-agent`,
which composes `growth.advertising` plus `growth.funnel.analyze`, and `retention-agent`, which
composes the read-only `retention.engagement.analyze`. Fake Meta and the in-memory experiment
sandbox are the only executable write adapters. Retention's live Manakids/Firebase adapters are
read-only and persist aggregate first-party facts only.

`app/mana_ai` cannot import `app.mana_operation_ai`. The AST test in
`tests/test_architecture_boundaries.py` also rejects operational repositories, database models,
Meta integrations, and action executors imported into the product context.

## MANA OPERATION AI layers

- `domain/`: Pydantic domain contracts, Decimal financial values, enums, state transitions, and
  provider-neutral advertising models. It has no FastAPI, SQLAlchemy, Meta, or OpenAI SDK imports.
- `application/`: registries, agent runner, analytics, policy, approvals, execution, reports,
  maintenance, Telegram OTP/session/user use cases, and typed ports. Use cases depend on protocols.
- `infrastructure/`: SQLAlchemy operation/auth repositories, Telegram Bot API delivery, Meta and
  fake-Meta adapters, first-party Manakids/Firestore readers, and notification adapter.
- `background/`: a persisted scheduler used by a standalone production worker; local in-process
  scheduling is optional and disabled by default.
- `api/`: versioned internal endpoints, Pydantic response models, RBAC, and HTTP error mapping.
- `admin-ui/`: Next.js App Router control room with strict React/TypeScript and synchronized
  FastAPI OpenAPI contracts.

## Admin rendering boundary

The admin root layout and route entry points are Server Components. They own stable HTML,
metadata, route loading/error boundaries, and composition. Authentication, SWR operational
freshness, filters, forms, confirmations, and mutations are isolated Client Components. The
browser calls same-origin `/api` URLs; a server-side Next.js rewrite forwards them to FastAPI using
private `FASTAPI_BASE_URL` configuration. Next.js contains no business endpoint, policy, identity
store, or provider integration.

`AdminShell` restores only the minimal backend session. The HttpOnly opaque ID remains invisible to
React; a readable CSRF value is reflected into `X-CSRF-Token` for unsafe same-origin calls. Actor UUID
and role come from the durable user/session join. Technical role keys are a separate server-client
compatibility path and are not represented in browser code.

Operational data is deliberately uncached in the browser transport. Volatile dashboards use
bounded polling plus focus/reconnect revalidation. Approval and kill-switch mutations force a
fresh read first, while FastAPI remains the final concurrency, authorization, and staleness gate.

## Dependency decisions

1. The generic agent registry contains implementations, not names. Each domain agent composes a
   typed `CapabilityRegistry`; central agent-name or job-type dispatch does not exist.
2. `AdsPlatform` isolates Meta payloads. Marketing analytics sees only normalized domain models.
3. SQLAlchemy rows are persistence envelopes. JSON domain payloads preserve versioned contracts;
   indexed columns support operational queries. ORM rows never leave the repository.
4. Agent and action state changes are checked against explicit transition maps.
5. Numeric KPIs are deterministic Decimal calculations. An LLM is not used to calculate or
   validate financial metrics. `OPENAI_MODEL` remains replaceable for the product AI gateway and
   later optional interpretation adapters.
6. The legacy `/api/v1/marketing` API and SQLite repository remain for compatibility. Local
   operation development can share the configured file; production uses PostgreSQL for operation
   coordination and keeps the legacy store separate.

## Persistence

Alembic owns the operational tables covering agents, capability configuration versions and
schedules, runs,
snapshots, analyses, findings, recommendations, proposals, approvals, decisions, executions,
verifications, reports, audit events, integration health, controls, and locks. UTC timestamps are
serialized with offsets in domain payloads. Money and financial thresholds serialize from Decimal.

Revision `8b7c2e4d901a` adds six durable authentication tables: users, HMAC-only OTP challenges,
HMAC-only sessions, authentication audit, rolling rate events, and a database guard used to
serialize cross-worker security mutations. The domain/application layers stay free of SQLAlchemy,
FastAPI, httpx, and Telegram payloads.

Revision `c41d9e7a2f30` adds capability scope to configurations, schedules, runs, and audit, preserves
legacy `marketing-agent` payloads, changes uniqueness to be capability-aware, and adds persisted
outcome evaluations.

## Request and execution flow

Manual run endpoints return `202 accepted` and use a background task. Scheduled runs and manual
runs call the same runner. The runner checks agent/capability status and kill switches, creates an
idempotent capability-scoped run, acquires a capability lock, and dispatches its typed handler.
Approval execution reads
provider state again, re-evaluates the active policy, checks the state hash and idempotency key,
writes only a typed action, reads again, and persists verification plus audit events.

## Extension points

- New capability in one of the four agents: add its typed task/configuration/evidence contracts,
  handler, source ports, action policy/executor when applicable, and register it with that agent.
- A new top-level operational agent requires an explicit architecture decision showing a genuinely
  new outcome owner, data authority, credential/policy boundary, and failure-isolation need. Do not
  add one for a new integration, schedule, report, or action kind.
- New ads provider: implement `AdsPlatform` and register it in `AdsPlatformRegistry`.
- New notification channel: implement `NotificationPort`; the current `log` channel is safe and
  does not log report contents.
- Distributed workers: multiple standalone scheduler workers coordinate through persisted
  occurrence and object leases; a future queue consumer can replace polling without changing
  agents.
- New database: set `OPERATION_DATABASE_URL` to a SQLAlchemy async URL and run Alembic.
