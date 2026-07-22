# Testing and verification

## One command

`make verify` runs:

1. Ruff formatting check;
2. Ruff lint;
3. frontend ESLint;
4. strict mypy;
5. strict TypeScript compilation;
6. all backend tests;
7. frontend component tests;
8. frontend production build;
9. high-severity npm dependency audit.

`make audit-verify` adds mutation, PostgreSQL, clean migration/drift, dependency, generated-schema,
secret/TODO, focused safety, and real-browser fake-provider gates.

## Test coverage

- Existing product AI and legacy marketing endpoints remain covered.
- Import-boundary AST enforcement protects MANA AI.
- Domain tests cover Decimal KPI/unavailable semantics, configuration/thresholds, state
  transitions, typed recommendations including maintain/resume, budget policy, cron timezone, and
  fake-provider idempotency.
- Repository integration covers configuration activation/versioning, run idempotency, and lock
  expiry/ownership against SQLAlchemy SQLite.
- Meta tests cover pagination, 429 retry/backoff diagnostics, query-plan normalization, explicit
  unavailable metrics, token non-disclosure, and live-write-disabled behavior.
- API tests cover RBAC, configuration validation, dashboard/marketing views, global kill switch,
  self-approval, dry-run state preservation, stale proposals, provider-object concurrency locks,
  explicit retry, and nightly reports with approvals.
- E2E covers fake snapshot through approved execution, verification, complete audit, and report.
- Frontend tests cover server-verified login/RBAC, viewer-disabled controls, approvals and expiry,
  action states, kill switches, configuration/schedules, manual runs, loading/error/empty states,
  pagination/filtering, reports/timelines, redaction/XSS, responsive navigation, and keyboard use.
- Browser E2E starts a fresh database and traverses the real API plus fake provider from agent run
  through finding, separate-actor approval, execution, verification, audit, and report.

No test calls OpenAI or a live Meta endpoint. `httpx.MockTransport`, dependency overrides, and the
mutable fake Meta adapter are used. Live Meta verification is an opt-in read-only runbook step.

## Migrations

Verify migrations separately against a fresh temporary database:

```bash
operation_db=$(mktemp --suffix=.db)
OPERATION_DATABASE_URL="sqlite+aiosqlite:///$operation_db" \
  OPENAI_API_KEY=placeholder .venv/bin/alembic upgrade head
OPERATION_DATABASE_URL="sqlite+aiosqlite:///$operation_db" \
  OPENAI_API_KEY=placeholder .venv/bin/alembic check
```

Remove only that explicit temporary file after inspection. Never run destructive database commands
against an unresolved environment variable.
