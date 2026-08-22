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

## Product direction: four action-capable agents

The source product document is intentionally interpreted as four durable operational domains, not
as a separate agent for every report row, integration, or scheduled task:

| Agent | Owns | Capabilities inside it |
| --- | --- | --- |
| **Operations Orchestrator** | Administrative goals and cross-domain outcomes | Admin analytics, forecasting, planning, delegation, correlation, outcome evaluation, executive reporting |
| **Growth & Conversion** | Acquisition and paid conversion | Advertising, SMM, funnel analysis, conversion, upsell, offers, experiments |
| **Retention & Loyalty** | Retention and customer lifetime value | Churn risk, lifecycle zones, win-back, subscription offers, loyalty, referral |
| **Technical Reliability** | Application reliability and technical response | Crashes, latency, errors, release regressions, reviews, support correlation, incidents |

Advertising, SMM, Upsell, Referral, Admin Analysis, and similar names are capabilities, not
additional top-level agents. Agents must be able to act through typed executors; analysis is only
the first half of the product. Every external/internal mutation follows evidence -> recommendation
-> typed intent -> policy -> approval -> fresh-state check -> idempotent execution -> verification
-> outcome measurement -> audit.

**Current versus target:** only `marketing-agent` is implemented today. Its end-to-end write path
is executable against `fake_meta`; live Meta is deliberately read-only. The working implementation
will become `growth.advertising` during a compatibility-preserving migration, not be discarded or
duplicated. See [the canonical agent model](docs/operation-agent-model.md) for boundaries, action
governance, migration rules, and delivery order.

### Endpoint groups

| Prefix | Purpose |
| --- | --- |
| `/api/v1/health/*` | Liveness and readiness |
| `/api/v1/mana-ai/*` | The product API layer (see its own README) |
| `/api/v1/ai/*` | Legacy chat/summarize gateway |
| `/api/v1/marketing/*` | Raw storage, graph, deterministic patterns, Meta sync, KPI + AI reports |
| `/api/v1/admin/operation/*` | Agents, runs, findings, approvals, executions, kill switches, audit |
| `/api/v1/auth/*` | Telegram OTP login, session, logout |
| `/api/v1/admin/users` | Admin-only management of permitted Telegram users |

Every endpoint below is also documented in Swagger at `/docs` (disabled under
`APP_ENV=production`).

### Authentication and sessions

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/auth/telegram/request-code` | Sends a six-digit code to the Telegram ID. Always returns a generic 202 so the endpoint cannot be used to discover which IDs are permitted. Rate limited per user, per IP, and globally. |
| POST | `/auth/telegram/verify-code` | Exchanges a valid code for an HttpOnly session cookie plus a CSRF cookie. One-time use; wrong codes count against the attempt limit. |
| GET | `/auth/session` | Current session, user, role, permissions, and provider mode. Returns `authenticated: false` rather than 401 when there is no session. |
| POST | `/auth/logout` | Revokes the session server-side and clears the cookies. |

### Admin users — admin role, session only

These reject internal role keys by design; a browser session is required.

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/admin/users` | Lists permitted Telegram users with role and status. |
| POST | `/admin/users` | Grants access to a Telegram ID with a role. |
| PATCH | `/admin/users/{user_id}` | Changes role, display name, or status. Disabling requires a reason. |
| GET | `/admin/users/{user_id}/audit` | Authentication audit trail for one user. |
| POST | `/admin/users/{user_id}/sessions/revoke` | Force-signs the user out of every active session. |

### Agents and runs

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/admin/operation/dashboard` | Per-agent status, health, next run, pending approvals, recent incidents, global kill-switch state. |
| GET | `/admin/operation/session` | Resolves the acting identity and the provider mode in effect. |
| GET | `/admin/operation/marketing/overview` | Marketing Agent view: integration health, token scopes, account context. |
| GET | `/admin/operation/agents` | Registered agents. |
| GET | `/admin/operation/agents/{agent_id}` | One agent with its definition and current state. |
| POST | `/admin/operation/agents/{agent_id}/register` | Registers an agent implementation loaded by the application. |
| POST | `/admin/operation/agents/{agent_id}/status` | Sets status explicitly. |
| POST | `/admin/operation/agents/{agent_id}/enable` · `/disable` · `/pause` · `/resume` | Status shortcuts. Paused keeps schedules; disabled stops them. |
| POST | `/admin/operation/agents/{agent_id}/run` | Triggers a job. Returns **202 accepted** with a `correlation_id` — not a run id. Find the run by polling `/runs`. Pass `idempotency_key` to make retries safe. |
| GET | `/admin/operation/runs` | Paginated run history with status and stage. |
| GET | `/admin/operation/runs/{run_id}` | One run plus its timeline, snapshots, findings, recommendations, and proposals. |

### Configuration and schedules

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/admin/operation/agents/{agent_id}/configuration-schema` | JSON Schema for that agent's configuration — use it to build a form. |
| GET | `/admin/operation/agents/{agent_id}/configurations` | Configuration version history. |
| POST | `/admin/operation/agents/{agent_id}/configurations` | Creates a new immutable version. Runs record the version they used. |
| GET | `/admin/operation/schedules` | Schedules with cron expression, timezone, and lease state. |
| PUT | `/admin/operation/schedules/{schedule_id}` | Replaces cron, timezone, and enabled flag. |

### Analysis output

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/admin/operation/findings` | Deterministic findings produced by runs. |
| GET | `/admin/operation/recommendations` | Recommendations derived from findings. |
| GET | `/admin/operation/reports` | Stored agent reports. |
| GET | `/admin/operation/reports/{report_id}` | One report. |
| GET | `/admin/operation/audit-events` | Append-only audit trail of who did what. |
| GET | `/admin/operation/integrations/{provider}/health` | Live provider check: reachability, token validity and scopes, latency. |

### The action pipeline

Where the safety controls live. Read [Safety model](#safety-model) before using these.

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/admin/operation/action-proposals` | Proposed changes with parameters, evidence, reasoning, risks, and policy decision. |
| GET | `/admin/operation/approvals` | Proposals awaiting a decision. |
| POST | `/admin/operation/approvals/{proposal_id}/decision` | Approve or reject one proposal. **403** if the actor produced it — self-approval is disabled. Requires a reason and a correlation id. |
| POST | `/admin/operation/approvals/bulk-decision` | Same decision across up to 50 proposals. **409** unless they all share one action type — and bulk *approval* is further limited to `decrease_budget`, since lowering spend is the only change safe to wave through in bulk. Bulk rejection works for any type. |
| POST | `/admin/operation/action-proposals/{proposal_id}/execute` | Re-checks every safeguard, then executes and verifies. Safe to repeat: the stored execution for the idempotency key is returned instead of writing twice. **423** when a safeguard blocks it — including a proposal that settled as `dry_run` rather than `approved`, which is what happens whenever `OPERATION_DRY_RUN=true`. |
| GET | `/admin/operation/executions` | Execution attempts with before-state, requested change, and provider response. |

### Kill switches

| Method | Path | What it does |
| --- | --- | --- |
| PUT | `/admin/operation/kill-switch/global` | Stops all agent activity platform-wide. |
| PUT | `/admin/operation/kill-switch/agents/{agent_id}` | Stops one agent. |

### Marketing

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/marketing/config` | Non-secret view of Meta and OpenAI configuration status. |
| POST | `/marketing/raw` | Appends raw marketing records. Append-only: originals are never overwritten. |
| GET | `/marketing/raw` | Reads stored raw records. |
| POST | `/marketing/raw/search` | Filters raw records by account, entity type, provider id, date, or payload fields. |
| POST | `/marketing/meta/discover` | Collects app, business, and ad-account metadata from the live Meta Graph API. Read-only. |
| POST | `/marketing/meta/sync` | Pulls structure and insights for an explicit `date_start`/`date_stop` range and appends them to raw storage. Read-only against live Meta. |
| POST | `/marketing/graph` | Builds the entity graph across app, business, pixel, audience, campaign, ad set, ad, creative, and insight. |
| POST | `/marketing/patterns` | Deterministic pattern search over stored insights — spend concentration, outliers, frequency fatigue, unmapped conversion signals. No model call. |
| POST | `/marketing/analyze` | KPIs computed in code, then a structured AI report. Needs `OPENAI_MAX_OUTPUT_TOKENS` around 16000; at 2048 the report truncates into a 502. |
| GET | `/marketing/reports` · `/marketing/reports/{report_id}` | Stored AI reports. |
| GET | `/marketing/reports/{report_id}/evidence` | A report bundled with the raw records it was derived from. |
| POST | `/marketing/meta/insights/jobs` | Async insights job. **403 against live Meta** — creation is a POST and live mode is read-only. Works with fixtures. |
| GET | `/marketing/meta/insights/jobs/{report_run_id}` | Async job status. |
| POST | `/marketing/meta/insights/jobs/{report_run_id}/ingest` | Loads finished job results into raw storage. |

### Legacy AI gateway

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/ai/chat` | One-shot chat against the configured model. |
| POST | `/ai/summarize` | Summarizes supplied text. |

Both are thin passthroughs with no deterministic fallback: if OpenAI is unavailable they return
**502** rather than degrading. That is intentional — there is no meaningful partial answer to
"summarize this".

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
- **Agent collection requires a completed reporting period.** When an agent run collects through
  the live Meta adapter, a `date_stop` of today or later is rejected — partial days would produce
  misleading KPIs. The rule applies to agent runs, not to the `/marketing/meta/sync` route.
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

`docs/operation-agent-model.md`, `docs/architecture.md`, `docs/operation-ai-platform.md`,
`docs/marketing-agent.md`, `docs/action-safety.md`, `docs/runbook.md`,
`docs/deployment-topology.md`, `docs/telegram-otp-auth.md`, `docs/admin-panel.md`.
