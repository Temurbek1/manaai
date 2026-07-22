# MANA platform architecture

## System shape

MANA is one deployable FastAPI service with two physically separated bounded contexts. They
share only safe technical facilities such as settings, request tracing, structured logging,
provider-neutral model access, and error conventions.

```text
Mobile payload -> app/mana_ai -> validation -> AI processing -> typed response

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
  maintenance, and ports. Use cases depend on protocols.
- `infrastructure/`: SQLAlchemy repository, Meta and fake-Meta adapters, and notification adapter.
- `background/`: a persisted scheduler used by a standalone production worker; local in-process
  scheduling is optional and disabled by default.
- `api/`: versioned internal endpoints, Pydantic response models, RBAC, and HTTP error mapping.
- `admin-ui/`: strict React/TypeScript client generated from FastAPI OpenAPI.

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

Alembic owns 18 `operation_*` tables covering agents, configuration versions, schedules, runs,
snapshots, analyses, findings, recommendations, proposals, approvals, decisions, executions,
verifications, reports, audit events, integration health, controls, and locks. UTC timestamps are
serialized with offsets in domain payloads. Money and financial thresholds serialize from Decimal.

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
