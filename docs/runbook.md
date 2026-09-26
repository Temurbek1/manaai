# Operations runbook

This runbook covers day-to-day operation of the **MANA OPERATION AI** admin platform. For
first-time setup use [../README.operation-ai.md](../README.operation-ai.md); the standalone product
API has its own guide in [../README.mana-ai.md](../README.mana-ai.md).

## Local startup

Create the virtualenv before `make install`, and write a local `.env` rather than copying
`.env.example` — that template targets Docker and points the database at the Compose host
`postgres`, which does not resolve on a developer machine.

```bash
python -m venv .venv && source .venv/bin/activate
make install

cat > .env <<'ENV'
APP_ENV=local
OPENAI_API_KEY=sk-your-real-key
MARKETING_DATABASE_PATH=data/manaai.db
OPERATION_ADS_PROVIDER=fake_meta
OPERATION_PRODUCT_ACTIVITY_PROVIDER=fake
OPERATION_DRY_RUN=true
ENV

make migrate
make run
# second terminal
make admin-dev
```

API: `http://localhost:8000`; Next.js admin: `http://localhost:3000`; local API docs:
`http://localhost:8000/docs`. The docs endpoints exist only while `APP_ENV` is not `production`.

Logging into the admin UI needs a Telegram OTP session; see the local login options in
[../README.operation-ai.md](../README.operation-ai.md).

## Docker startup

Set non-placeholder `OPENAI_API_KEY`, compatibility/service keys, database credentials,
`MANA_TELEGRAM_BOT_TOKEN`, `MANA_TELEGRAM_BOT_USERNAME`, a strong `MANA_OTP_HMAC_SECRET`, and the
public HTTPS admin origin in `MANA_TRUSTED_ORIGINS`, then run:

```bash
docker compose up --build
```

Compose forces `APP_ENV=production`, runs Alembic in a one-shot migration service, keeps the API
scheduler disabled, and runs scheduling in a separate worker. API and worker force
dry-run/live-write-disabled. The admin panel is on port 3000. `.env` is injected only as container
environment and is excluded from images. The admin container serves Next.js standalone output,
rewrites same-origin `/api` requests to `http://api:8000`, and reports health at `/healthz`.

## Common commands

```bash
make migrate
make migration name=describe_change
make demo
make verify
make auth-verify
make admin-verify
make audit-verify
```

`make demo` executes the fake-Meta end-to-end lifecycle test: snapshot, analytics, proposals,
approval, fake write, verification, audit, and report.

## Health and incidents

- Container liveness: `GET /api/v1/health/live` (no auth).
- Operation integration: `GET /api/v1/admin/operation/integrations/{provider}/health`.
- Runs/audit: `/api/v1/admin/operation/runs` and `/audit-events` with correlation/run filters.
- Authentication audit/user control: `/users`; disable a user or revoke all sessions immediately.
- Stop all action and new-run execution: `PUT /api/v1/admin/operation/kill-switch/global`.
- Stop one agent: `PUT /api/v1/admin/operation/kill-switch/agents/{agent_id}`.
- Pause scheduling by changing agent status or disabling its schedules.

If an action is stuck in `executing`, the scheduler reconciliation re-reads provider state hourly.
Operators can inspect expected/observed state and should not issue an untyped manual Meta request.
If a proposal is approved but blocked by a temporary kill switch, resolve the control and call
`POST /api/v1/admin/operation/action-proposals/{proposal_id}/execute`; all safeguards are rechecked.

## Backups and retention

Back up the PostgreSQL database and legacy marketing store before migrations. The repository ships
`scripts/backup_production.sh` plus a daily systemd service/timer in `deploy/systemd/`. The script
creates a consistent PostgreSQL custom-format dump, uses SQLite's online backup API, validates the
PostgreSQL archive, records checksums, and keeps 14 daily backup directories by default. Copy those
archives to an encrypted off-host store; local-disk backups alone do not cover host loss. SQLite is
suitable for one process and local development only. Use managed PostgreSQL and the standalone
worker for production. The maintenance job deletes old technical snapshots and dependent
analyses/findings after `OPERATION_DATA_RETENTION_DAYS` (90 days by default), and removes expired
locks. Audit, action, configuration, recommendation, and report records are retained.

## Live Meta read verification

1. Use a Meta system-user token with least privilege.
2. Configure business or explicit ad-account IDs.
3. Verify `ads_read` and, when business asset discovery is used, appropriate
   `business_management` access; app review/business verification may be required.
4. Keep `OPERATION_DRY_RUN=true`, `META_LIVE_MODE=read_only`, and
   `META_REAL_WRITES_ENABLED=false`.
5. Run `META_LIVE_READONLY_VERIFY=1 make meta-live-readonly-verify`; inspect the sanitized evidence
   and portable report without printing payloads or identifiers. The command also opens the real
   Next.js Marketing page and verifies its read-only banner, safe account alias, missing execute
   control, and desktop/mobile overflow without issuing an action mutation. The repository-owned
   portable-report generator validates the canonical artifact, embeds no external resources, and
   browser-checks source interaction plus desktop/mobile layout.

The 2026-07-22 validation passed for account alias `2b6c4ddcc5`. Live writes are unsupported even if
the token has a write-capable scope.

## Live first-party product activity

Retention engagement uses application-owned data only: backend aggregates from the Manakids Admin
API and mobile product events from Firestore. It does not mix Meta or other marketing-provider data
into this source boundary. Install both least-privilege credentials through the deployment secret
manager, keep scheduling off, and follow
[the live product activity runbook](live-product-activity-runbook.md). The repository never embeds
the credentials supplied in handoff documents.

## Key rotation

Rotate application/role keys, provider tokens, and the Telegram bot token in the secret manager;
restart the API, verify health, and revoke old values. Bot-token rotation does not revoke sessions.
Rotating `MANA_OTP_HMAC_SECRET` intentionally invalidates all outstanding OTP challenges and
sessions and should be treated as an emergency global logout. Never paste tokens, OTP, session, or
CSRF values into reports, raw ingestion, logs, screenshots, or support tickets.

For delivery incidents, confirm the user pressed Start, active status/Telegram ID are correct, and
cooldown/lockout elapsed. Use only sanitized auth audit categories. The opt-in end-to-end real-bot
check requires an explicitly owned test ID:

```bash
MANA_TELEGRAM_AUTH_SMOKE=1 \
MANA_TELEGRAM_AUTH_SMOKE_USER_ID=<explicit-id> \
make telegram-auth-smoke
```

Do not run it for another person and do not persist the entered code.
