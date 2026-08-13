# MANA OPERATION AI — internal admin platform

Internal platform where staff study the product and its environment — including Meta Ads — and act
on it through agents under an approval-gated safety pipeline.

**This is not the product API.** The application-facing AI layer is a separate deliverable that
runs without any of this — see [README.mana-ai.md](README.mana-ai.md).

## What this platform is

- **FastAPI backend** (`app.main:create_app`) exposing 73 endpoints, including the 14 of the
  product API layer.
- **Next.js 16 / React 19 admin UI** in `admin-ui/`, served on port 3000, proxying same-origin
  `/api` to FastAPI. Business logic stays in FastAPI.
- **PostgreSQL** in production (SQLite locally), managed by Alembic.
- **Agent runtime**: generic registry, state machines, versioned configurations and schedules, a
  persisted scheduler in a separate worker, and a full audit trail.
- **Meta Marketing API** integration through a provider-neutral ads port, with a complete fake
  adapter for development.

### Endpoint groups

| Prefix | Purpose |
| --- | --- |
| `/api/v1/health/*` | Liveness and readiness |
| `/api/v1/mana-ai/*` | The product API layer (see its own README) |
| `/api/v1/ai/*` | Legacy chat/summarize gateway |
| `/api/v1/marketing/*` | Raw storage, graph, deterministic patterns, Meta sync, KPI + AI reports |
| `/api/v1/admin/operation/*` | Dashboard, agents, runs, findings, recommendations, proposals, approvals, executions, reports, schedules, kill switches, audit |
| `/api/v1/auth/*` | Telegram OTP login, session, logout |
| `/api/v1/admin/users` | Admin-only management of permitted Telegram users |

## Local setup

Requires Python 3.12+, Node.js 24, and a virtualenv created before `make install`.

`.env.example` is a **production/Docker template** — it points the database at the Compose host
`postgres`, so copying it verbatim will not work on a developer machine. Write a small local `.env`
instead:

```bash
python -m venv .venv
source .venv/bin/activate
make install                 # [operation,dev] + npm ci in admin-ui

cat > .env <<'ENV'
APP_ENV=local
OPENAI_API_KEY=sk-your-real-key
# Omit OPERATION_DATABASE_URL locally: SQLite is then derived from MARKETING_DATABASE_PATH.
MARKETING_DATABASE_PATH=data/manaai.db
OPERATION_ADS_PROVIDER=fake_meta
OPERATION_DRY_RUN=true
ENV

make migrate
make run                     # http://localhost:8000
make admin-dev               # second terminal, http://localhost:3000
```

Local defaults are deliberately safe: `fake_meta` exercises the entire agent lifecycle with no Meta
credentials and no external calls. Add real Meta or Telegram values only when you need those
integrations.

`make demo` runs that lifecycle end to end — collect, findings, recommendations, proposals,
approval — and is the fastest confirmation that the platform works.

### Logging in locally

The admin UI requires a Telegram OTP session. Two options without a real bot:

**Drive the API directly.** Set an internal role key such as `OPERATION_ADMIN_API_KEY` and send it
as `X-API-Key`. Note that `/api/v1/admin/users` is deliberately session-only and rejects role keys.

**Exercise the real OTP flow offline.** Set `MANA_AUTH_TEST_MODE=true` and
`MANA_AUTH_TEST_OTP_SINK_PATH=/tmp/otp.log`; codes are written to that file instead of being sent
to Telegram. Both require `APP_ENV=local`. Add your own Telegram ID to
`MANA_BOOTSTRAP_ADMIN_TELEGRAM_IDS`.

## Production deployment

```bash
cp .env.example .env
# fill every replace_with_* value first
docker compose up --build
```

Compose runs PostgreSQL 17, a one-shot Alembic migration service, the API with its scheduler
disabled, a worker that owns scheduling, and the admin UI. It forces `APP_ENV=production` and
`OPERATION_DRY_RUN=true` on API and worker, and `META_REAL_WRITES_ENABLED=false` everywhere.

### Fill these before the first start

The application refuses to boot without them, by design.

| Variable | Rule enforced at startup |
| --- | --- |
| `OPENAI_API_KEY` | required |
| `APP_API_KEY` | bearer token for `/ai`, `/marketing`, and `/mana-ai` in production |
| `MANA_TELEGRAM_BOT_TOKEN` / `MANA_TELEGRAM_BOT_USERNAME` | required when Telegram auth is enabled |
| `MANA_OTP_HMAC_SECRET` | ≥32 characters, ≥8 distinct characters, not a `change-me`/`replace_with_*` placeholder |
| `MANA_TRUSTED_ORIGINS` | JSON array; must contain the exact public admin origin |
| `CORS_ORIGINS` | JSON array; `*` is rejected in production |
| `POSTGRES_PASSWORD` **and** `OPERATION_DATABASE_URL` | the same password lives in both — change both, or the containers will not connect |

Two cross-field ceilings are enforced at startup and are easy to trip: `META_MAX_RETRIES` must not
exceed `META_LIVE_MAX_TOTAL_RETRIES`, and `META_MAX_PAGES` must not exceed `META_LIVE_MAX_PAGES`.

### TLS is mandatory, and Compose does not provide it

Session cookies carry the `Secure` flag whenever `APP_ENV` is `staging` or `production`, and
Compose forces `production`. A browser therefore **discards the session cookie over plain HTTP**,
so `http://localhost:3000` cannot complete a login even while every container reports healthy.

Terminate TLS in a reverse proxy in front of the admin service and put that public HTTPS origin in
`MANA_TRUSTED_ORIGINS`.

### Harden before exposing

- **Replace `MANA_BOOTSTRAP_ADMIN_TELEGRAM_IDS`.** It grants admin idempotently on every API start,
  and the shipped value contains the maintainers' own Telegram IDs. Set your own or you will grant
  production admin to accounts you do not control.
- **Compose publishes the API on `0.0.0.0:8000`.** That surface accepts the internal
  `OPERATION_*_API_KEY` role keys, which must never be distributed to people. Firewall it or bind
  it to loopback the way `docker-compose.mana-ai.yml` does.
- **`env_file: .env` is applied to the `postgres` service too**, so provider secrets reach the
  database container. Narrow this if your threat model requires it.
- **The `worker` service has no healthcheck**, so a wedged scheduler is not automatically visible.
- Keep `OPERATION_ALLOW_INSECURE_DEV_HEADERS=false` outside tests.

### Admin UI build note

`FASTAPI_BASE_URL` is consumed at **both** build time (baked in through `next.config.ts`) and run
time. Changing the API destination requires rebuilding the admin image, not just editing the
environment.

## Safety model

This platform can change a live ad account, so the controls matter.

- **Dry run by default.** `OPERATION_DRY_RUN=true` makes approved proposals settle as `dry_run`; a
  subsequent execute call returns `423`. That is correct behaviour, not a failure.
- **No self-approval.** The actor that produced a proposal cannot approve it — expect `403
  Self-approval is disabled`. Use a second actor.
- **Bulk decisions must be homogeneous.** Mixed action types return `409`.
- **Live Meta is read-only.** `META_LIVE_MODE=read_only` and `META_REAL_WRITES_ENABLED=false`;
  startup rejects `true`. `POST /api/v1/marketing/meta/insights/jobs` therefore returns `403`
  against live Meta, because Meta's async report creation is a POST.
- **Kill switches** exist globally and per agent.
- **Execution limits** are capped per day, globally and per agent.

Live Meta validation is separately opt-in and GET-only:

```bash
META_LIVE_READONLY_VERIFY=1 make meta-live-readonly-verify
```

## Operational notes

- **`OPENAI_MAX_OUTPUT_TOKENS=2048` is too small for `POST /api/v1/marketing/analyze`.** The
  structured report is truncated and the endpoint returns `502`. Use `16000` as in `.env.example`
  when marketing reports are in scope; the 11 MANA AI capabilities fit within 2048.
- Swagger, ReDoc, and `/openapi.json` are disabled when `APP_ENV=production`.
- `alembic.ini` hardcodes a SQLite URL, but `migrations/env.py` overrides it at runtime from
  `Settings`. Do not read `alembic.ini` to determine the real target database.

## Checks

```bash
make lint          # ruff + admin-ui eslint
make typecheck     # mypy strict + tsc
make test          # pytest (excludes live Meta) + admin-ui jest
make verify        # format, lint, typecheck, tests, admin build, npm audit
make demo          # fake-Meta agent lifecycle
```

Deeper suites: `make auth-verify`, `make admin-verify`, `make audit-verify`. There is currently no
CI configuration in the repository, so these run locally.

## Further reading

`docs/architecture.md`, `docs/operation-ai-platform.md`, `docs/marketing-agent.md`,
`docs/action-safety.md`, `docs/runbook.md`, `docs/deployment-topology.md`,
`docs/telegram-otp-auth.md`, `docs/admin-panel.md`.
