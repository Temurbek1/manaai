# MANA AI — product API layer

Read-only request/response AI API consumed by the MANA application. This document is the complete
handoff for a developer who receives only this layer.

**This is not the admin panel.** The admin platform is a separate deliverable with its own
database, agents, and UI — see [README.operation-ai.md](README.operation-ai.md). Nothing in this
document requires it.

## What this layer is

The application sends minimized evidence, this API returns a typed analysis. That is the whole
contract.

- **Stateless.** No database, no migrations, no scheduler, no worker, no browser UI.
- **Read-only by construction.** It never reads or mutates application data and never executes an
  action. It only *proposes* actions; the application decides.
- **11 independent capabilities**, each its own endpoint with its own typed request and response.
  There is deliberately no generic `/analyze` endpoint with a capability discriminator.
- **One external dependency:** OpenAI.

The import boundary is enforced by tests: `app/mana_ai` may not import repositories, ORM models,
Meta integrations, or the operation platform, and may not import FastAPI.

### Endpoints

14 total. `GET /api/v1/mana-ai/capabilities` returns the exact method and path of every capability
— use it as the machine-readable index rather than hardcoding paths.

| Method | Path |
| --- | --- |
| GET | `/api/v1/health/live` |
| GET | `/api/v1/health/ready` |
| GET | `/api/v1/mana-ai/capabilities` |
| POST | `/api/v1/mana-ai/safety-monitor` |
| POST | `/api/v1/mana-ai/family-digest` |
| POST | `/api/v1/mana-ai/adaptive-screen-time` |
| POST | `/api/v1/mana-ai/location-intelligence` |
| POST | `/api/v1/mana-ai/smart-content-filter` |
| POST | `/api/v1/mana-ai/scam-privacy-shield` |
| POST | `/api/v1/mana-ai/ai-gaming-safety` |
| POST | `/api/v1/mana-ai/parent-copilot` |
| POST | `/api/v1/mana-ai/child-safety-assistant` |
| POST | `/api/v1/mana-ai/family-agreement` |
| POST | `/api/v1/mana-ai/behaviour-anomaly` |

The per-endpoint payload contract — request envelope, evidence rules, and every capability's
fields — lives in [docs/mana-ai-api.md](docs/mana-ai-api.md). This README covers everything else.

## Local setup

Requires Python 3.12+. Nothing else — no Node, no Docker, no database.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
printf 'APP_ENV=local\nOPENAI_API_KEY=sk-your-real-key\n' > .env
uvicorn app.product_ai_main:create_app --factory --reload --port 8000
```

Install the base dependency set only. Do **not** add `[operation]` — that pulls SQLAlchemy,
Alembic, and the Meta layer, none of which this API uses.

Verify:

```bash
curl http://localhost:8000/api/v1/health/ready
curl http://localhost:8000/api/v1/mana-ai/capabilities
```

Swagger UI is at `/docs`, ReDoc at `/redoc`, schema at `/openapi.json`. Every capability endpoint
ships a worked request example in the schema, so Swagger doubles as the fastest way to see a valid
payload. **All three are disabled when `APP_ENV=production`** — to browse them or generate an SDK,
run the same factory in a trusted staging environment with `APP_ENV=staging`.

## Configuration

Only these variables affect this layer. Everything else in `.env.example` belongs to the admin
platform and is ignored here.

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | yes | — | The only hard requirement locally |
| `APP_ENV` | no | `local` | `production` disables docs and enforces auth |
| `APP_API_KEY` | in production | — | The bearer token; **must be ≥32 characters** in production |
| `OPENAI_MODEL` | no | `gpt-5.4-nano` | |
| `OPENAI_MAX_OUTPUT_TOKENS` | no | `2048` | Sufficient for all 11 capabilities |
| `OPENAI_TIMEOUT_SECONDS` | no | `30` | |
| `OPENAI_REASONING_EFFORT` | no | `none` | |
| `OPENAI_VERBOSITY` | no | `low` | |
| `MANA_AI_MAX_REQUEST_BODY_BYTES` | no | `1048576` | Bodies above this get `413` |
| `CORS_ORIGINS` | no | `[]` | JSON array; `*` is rejected in production |
| `MANA_TELEGRAM_AUTH_ENABLED` | **in production** | `true` | Set to `false` — see below |
| `API_RATE_LIMIT_REQUESTS` | no | `60` | Authenticated requests allowed per window, per client IP |
| `API_RATE_LIMIT_WINDOW_SECONDS` | no | `60` | Length of that window |
| `AUTH_FAILURE_LIMIT` | no | `10` | Failed auth attempts before a client IP is throttled |
| `AUTH_FAILURE_WINDOW_SECONDS` | no | `60` | Window for the failure counter |

In production the factory refuses to start if `APP_API_KEY` is missing or shorter than 32
characters, or if `OPENAI_API_KEY` is unset. That is intentional — fail at boot, not at request
time.

**Set `MANA_TELEGRAM_AUTH_ENABLED=false` in production.** It defaults to `true`, and the shared
settings validator then demands `MANA_OTP_HMAC_SECRET`, `MANA_TELEGRAM_BOT_TOKEN`, and
`MANA_TELEGRAM_BOT_USERNAME` whenever `APP_ENV` is `staging` or `production`. Those belong to the
admin platform's browser login, which this API does not have — omit the flag and startup fails with
a confusing complaint about an OTP secret. `docker-compose.mana-ai.yml` already sets it for you.

## Authentication

Bearer token. Send `APP_API_KEY` on every `/mana-ai/*` call:

```
Authorization: Bearer <APP_API_KEY>
```

A rejected request returns `401` with `WWW-Authenticate: Bearer`. The retired `X-API-Key` header is
no longer accepted anywhere in this layer.

Authentication is enforced whenever `APP_ENV=production` **or** `APP_API_KEY` is configured.

`/api/v1/health/live` and `/api/v1/health/ready` stay open so orchestrators can probe them.

`APP_API_KEY` is a server-to-server credential between the application backend and this API.
**Never ship it in a mobile or browser bundle.**

### Local development

Leave `APP_API_KEY` unset in `APP_ENV=local` and authentication is off entirely — `curl` the
endpoints with no headers. Rate limiting is off in that mode too, so nothing gets in your way.

Set `APP_API_KEY` locally and the API behaves exactly like production, which is the fastest way to
test your client's auth handling. Swagger UI then shows an **Authorize** button: paste the token
once and every "Try it out" call carries it.

### Rate limiting

Two independent limits, both returning `429` with a `Retry-After` header you should honor:

| Limit | Counts | Default |
| --- | --- | --- |
| `AUTH_FAILURE_LIMIT` / `AUTH_FAILURE_WINDOW_SECONDS` | failed auth attempts per client IP | 10 per 60s |
| `API_RATE_LIMIT_REQUESTS` / `API_RATE_LIMIT_WINDOW_SECONDS` | successful authenticated requests per client IP | 60 per 60s |

The first blocks token guessing; the second bounds what a leaked or looping client can spend
against the OpenAI budget. Rejected requests are not charged against the budget, so a blocked
caller cannot extend its own penalty by retrying.

Both limits are **per process and per client IP**. Behind several replicas each replica enforces
its own budget, and the total is proportional to the replica count. Neither is a hard cap on
provider spend — set a budget limit on the OpenAI account for that.

## Reading a response

Check `status` before you trust the content. HTTP 200 does not mean the model ran.

| Field | Meaning |
| --- | --- |
| `status` | `completed` — full analysis. `degraded` — something was unavailable or a model claim was rejected; the response is still valid but reduced. |
| `verdict` | `no_risk_detected`, `observe`, `warn`, `alert`, `block`, `insufficient_data` |
| `data_quality_notes` | Why a result is degraded, in plain language. Log these. |
| `findings` | Evidence-backed findings; each cites `evidence_id` values you supplied |
| `proposed_actions` | Suggestions only. This API never executes anything. |
| `read_only` / `privacy` | Assertions that no application data was read or mutated |

**Degradation is normal, not an error.** If OpenAI is unreachable the API still returns HTTP 200
with `status: "degraded"`, `verdict: "insufficient_data"`, and a note saying semantic analysis was
unavailable — rather than inventing a conclusion. Safety-critical deterministic checks still run:
a resource with `reputation: "malicious"` is still blocked with a critical finding even when the
model is completely down.

The service treats model output as untrusted. Findings citing evidence you did not send are
dropped, risk claims without a supporting finding are downgraded, and a summary that contradicts
the validated verdict is replaced. Every such intervention sets `status: "degraded"` and appends a
note — so a degraded response is often the system protecting you from a bad model answer.

`verdict` and `status` are independent: a `degraded` response can still carry a confident `block`.

## Errors

| Code | Cause |
| --- | --- |
| `401` | Missing or invalid bearer token |
| `413` | Body exceeds `MANA_AI_MAX_REQUEST_BODY_BYTES` |
| `422` | Request fails the capability schema |
| `429` | Too many failed auth attempts; honor `Retry-After` |
| `502` | Upstream OpenAI failure that could not be degraded |
| `503` | `OPENAI_API_KEY` not configured |

Retry `429` per `Retry-After`, and `502`/`503` with backoff. Never retry `401`, `413`, or `422` —
they are deterministic. Reuse the same `request_id` when retrying the same logical analysis.

Every response carries `X-Request-ID` and `X-Process-Time-Ms`. Send your own `X-Request-ID` and it
is echoed back; omit it and one is generated. Use it to correlate logs across systems.

## Production deployment

Standalone on a Linux VPS with Docker. No PostgreSQL, SQLite, migrations, scheduler, worker, or
admin UI.

1. Install Docker and the Compose plugin (standard vendor instructions for your distribution).

2. Place the code on the server:

```bash
sudo mkdir -p /opt/manaai-api
sudo chown "$USER":"$USER" /opt/manaai-api
git clone <your-repository-url> /opt/manaai-api
cd /opt/manaai-api
```

3. Write a production `.env` containing only what this layer needs:

```env
APP_ENV=production
APP_API_KEY=replace_with_high_entropy_key_at_least_32_chars
OPENAI_API_KEY=replace_with_real_secret
OPENAI_MODEL=gpt-5.4-nano
OPENAI_REASONING_EFFORT=none
OPENAI_VERBOSITY=low
OPENAI_MAX_OUTPUT_TOKENS=2048
MANA_AI_MAX_REQUEST_BODY_BYTES=1048576
CORS_ORIGINS=[]
MANA_TELEGRAM_AUTH_ENABLED=false
```

4. Build and start:

```bash
docker compose -f docker-compose.mana-ai.yml config --quiet
docker compose -f docker-compose.mana-ai.yml up -d --build
docker compose -f docker-compose.mana-ai.yml logs -f mana-ai-api
```

5. Verify:

```bash
curl http://127.0.0.1:8000/api/v1/health/live       # {"status":"ok"}

read -rsp "APP_API_KEY: " APP_API_KEY && echo
curl -H "Authorization: Bearer $APP_API_KEY" http://127.0.0.1:8000/api/v1/mana-ai/capabilities
unset APP_API_KEY
```

The image builds from `requirements.mana-ai.lock`, which deliberately excludes SQLAlchemy, Alembic,
and the Meta layer. Regenerate that lock from a clean Python 3.12 environment whenever
`pyproject.toml` dependencies change.

Compose publishes the port on `127.0.0.1` only. To reach it from another host use a private
network or VPN, or a TLS reverse proxy with a network allowlist.

### Nginx reverse proxy

```nginx
server {
    listen 80;
    server_name api.example.com;
    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Keep `client_max_body_size` aligned with `MANA_AI_MAX_REQUEST_BODY_BYTES`, then add TLS via Certbot
or another ACME client.

## Privacy posture

- Requests are sent to OpenAI with `store=False`, so provider-side retention is disabled.
- The subject identifier is hashed into a `safety_identifier` before it leaves the process; the raw
  identifier is never sent.
- Send minimized evidence and set `data_minimized: true`. The system prompt forbids reproducing
  full notification text, URLs with query strings, coordinates, or other private content.
- Model input is treated as untrusted data: the prompt explicitly forbids following instructions
  embedded in notification text, URLs, or any other supplied field.
- Logs redact configured secrets.

## Checks

```bash
ruff check .
mypy .
pytest -q -m "not live_meta"
```

Tests never call the real OpenAI API — they use fakes and dependency overrides. Keep it that way.
