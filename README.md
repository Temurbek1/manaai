# ManaAI

Production-oriented FastAPI platform for the MANA family-safety product. The repository ships
**two separate deliverables** that share a codebase but are built, deployed, and handed over
independently.

Start with the one you need:

- **[README.mana-ai.md](README.mana-ai.md)** — MANA AI, the request/response API layer consumed by
  the MANA application.
- **[README.operation-ai.md](README.operation-ai.md)** — MANA OPERATION AI, the internal admin
  platform with agents, Meta Ads analysis, and the browser panel.

## The separation

This is the most important thing to understand before touching the code. The two products have
different runtimes, dependencies, images, audiences, and risk profiles. Do not configure one by
following the other's instructions.

| | **MANA AI** | **MANA OPERATION AI** |
| --- | --- | --- |
| Purpose | AI layer for the application: evidence in, typed analysis out | Internal panel: study the product and its environment, act through agents |
| Audience | The MANA application backend | Staff and administrators |
| ASGI factory | `app.product_ai_main:create_app` | `app.main:create_app` |
| Endpoints | 14 | 73 (includes all 14) |
| Database | **none** | PostgreSQL in production, SQLite locally |
| External services | OpenAI | OpenAI, Meta Marketing API, Telegram Bot API |
| Browser UI | none | Next.js admin in `admin-ui/` |
| Dependencies | `requirements.mana-ai.lock` | `pyproject.toml` `[operation]` |
| Image / Compose | `Dockerfile.mana-ai` / `docker-compose.mana-ai.yml` | `Dockerfile` / `docker-compose.yml` |
| Auth | `Authorization: Bearer` | Telegram OTP browser session + internal role keys |
| Can change external state? | Never — read-only by construction | Yes, through an approval-gated pipeline |

The boundary is enforced, not merely documented: `app/mana_ai` may not import repositories, ORM
models, Meta integrations, action executors, or `app.mana_operation_ai`, and may not import
FastAPI. HTTP transport for MANA AI lives in `app/api/routes/`. See
`tests/test_architecture_boundaries.py`.

## Technical characteristics

- **Python 3.12+**, FastAPI, Pydantic v2 typed contracts everywhere; no untyped route handlers.
- **Strict layering**: routes stay thin, MANA AI contracts live in `app/mana_ai/`, operational
  contracts in `app/mana_operation_ai/domain/`, compatibility logic in `app/services/`.
- **Operational domain code** must not import FastAPI, SQLAlchemy, Redis, Meta SDKs, or the OpenAI
  SDK. External providers implement typed application ports; provider payloads are translated at
  adapter boundaries.
- **Deterministic before semantic.** KPIs and safety checks are computed in code first; the model
  explains and extends them but cannot contradict them.
- **Model output is untrusted.** Findings citing unknown evidence are dropped, unsupported risk
  claims are downgraded, and a summary conflicting with the validated verdict is replaced. Every
  intervention marks the response `degraded` and records a reason.
- **Append-only raw storage** for Meta and export payloads, so original provider data is never lost.
- **Async I/O** for all provider integrations.
- **Configuration** is centralized in `app/core/config.py` and loaded through `get_settings()`; no
  hidden globals, no hardcoded secrets.
- **Trace headers** `X-Request-ID` and `X-Process-Time-Ms` on every response.
- **Swagger/OpenAPI** with tag descriptions, summaries, and request examples — disabled when
  `APP_ENV=production` on both tracks.

## Repository layout

```
app/
  product_ai_main.py        MANA AI factory (standalone, no database)
  main.py                   Full platform factory
  api/routes/               HTTP transport
  mana_ai/                  Product AI domain + application (no FastAPI, no persistence)
  mana_operation_ai/        Operational domain, application, infrastructure
  services/                 Compatibility logic, OpenAI and Meta clients
  core/                     Settings, logging, middleware, OpenAPI metadata
admin-ui/                   Next.js 16 admin panel
migrations/                 Alembic
scripts/                    Verification, audit, and smoke scripts
docs/                       Architecture, contracts, runbooks
tests/
```

## Quality gates

```bash
make lint          # ruff (+ eslint for the admin UI)
make typecheck     # mypy strict (+ tsc)
make test          # pytest, excludes live Meta, plus admin-ui jest
make verify        # everything above, plus admin build and npm audit
```

Tests never call the real OpenAI API and never call Meta write APIs. Live Meta checks are opt-in,
read-only, and marked `live_meta`.

Contribution rules, architecture constraints, and command reference: [AGENTS.md](AGENTS.md).
