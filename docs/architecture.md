# MANA platform architecture

## System shape

MANA is one deployable FastAPI service with two physically separated bounded contexts. They
share only safe technical facilities such as settings, request tracing, structured logging,
provider-neutral model access, and error conventions.

```text
Mobile payload -> app/mana_ai -> validation -> AI processing -> typed response

Browser -> Next.js same-origin rewrite -> FastAPI Telegram OTP/session API
                                      -> auth application ports
                                      -> SQLAlchemy + Telegram Bot API adapters

Admin/API/scheduler -> app/mana_operation_ai/application
                    -> domain contracts and state machines
                    -> repository / AdsPlatform / Notification ports
                    -> SQLAlchemy, Meta Graph, fake Meta, logging adapters
```

`app/mana_ai` cannot import `app.mana_operation_ai`. The AST test in
`tests/test_architecture_boundaries.py` also rejects operational repositories, database models,
Meta integrations, and action executors imported into the product context.

## MANA OPERATION AI layers

- `domain/`: Pydantic domain contracts, Decimal financial values, enums, state transitions, and
  provider-neutral advertising models. It has no FastAPI, SQLAlchemy, Meta, or OpenAI SDK imports.
- `application/`: registries, agent runner, analytics, policy, approvals, execution, reports,
  maintenance, Telegram OTP/session/user use cases, and typed ports. Use cases depend on protocols.
- `infrastructure/`: SQLAlchemy operation/auth repositories, Telegram Bot API delivery, Meta and
  fake-Meta adapters, and notification adapter.
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

1. The generic registry contains implementations, not names. Adding an agent means implementing
   `OperationalAgent` and registering it; central `if agent_name == ...` dispatch does not exist.
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

Alembic owns the operational tables covering agents, configuration versions, schedules, runs,
snapshots, analyses, findings, recommendations, proposals, approvals, decisions, executions,
verifications, reports, audit events, integration health, controls, and locks. UTC timestamps are
serialized with offsets in domain payloads. Money and financial thresholds serialize from Decimal.

Revision `8b7c2e4d901a` adds six durable authentication tables: users, HMAC-only OTP challenges,
HMAC-only sessions, authentication audit, rolling rate events, and a database guard used to
serialize cross-worker security mutations. The domain/application layers stay free of SQLAlchemy,
FastAPI, httpx, and Telegram payloads.

## Request and execution flow

Manual run endpoints return `202 accepted` and use a background task. Scheduled runs and manual
runs call the same runner. The runner checks status and kill switches, creates an idempotent queued
run, acquires an agent lock, and executes the registered implementation. Approval execution reads
provider state again, re-evaluates the active policy, checks the state hash and idempotency key,
writes only a typed action, reads again, and persists verification plus audit events.

## Extension points

- New operational agent: implement `OperationalAgent`, domain configuration, and adapters; register
  it in the composition root.
- New ads provider: implement `AdsPlatform` and register it in `AdsPlatformRegistry`.
- New notification channel: implement `NotificationPort`; the current `log` channel is safe and
  does not log report contents.
- Distributed workers: multiple standalone scheduler workers coordinate through persisted
  occurrence and object leases; a future queue consumer can replace polling without changing
  agents.
- New database: set `OPERATION_DATABASE_URL` to a SQLAlchemy async URL and run Alembic.
