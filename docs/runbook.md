# Operations runbook

## Local startup

```bash
cp .env.example .env
# replace OPENAI_API_KEY for legacy AI routes; keep fake_meta and dry-run for operation work
make install
make migrate
make run
# second terminal
make admin-dev
```

API: `http://localhost:8000`; admin: `http://localhost:5173`; local API docs:
`http://localhost:8000/docs`.

## Docker startup

Set non-placeholder `OPENAI_API_KEY`, `APP_API_KEY`, and separate operation role keys in `.env`,
then run:

```bash
docker compose up --build
```

Compose forces `APP_ENV=production`, runs Alembic in a one-shot migration service, keeps the API
scheduler disabled, and runs scheduling in a separate worker. API and worker force
dry-run/live-write-disabled. The admin panel is on port 3000. `.env` is injected only as container
environment and is excluded from images.

## Common commands

```bash
make migrate
make migration name=describe_change
make demo
make verify
make audit-verify
```

`make demo` executes the fake-Meta end-to-end lifecycle test: snapshot, analytics, proposals,
approval, fake write, verification, audit, and report.

## Health and incidents

- Container liveness: `GET /api/v1/health/live` (no auth).
- Operation integration: `GET /api/v1/admin/operation/integrations/{provider}/health`.
- Runs/audit: `/api/v1/admin/operation/runs` and `/audit-events` with correlation/run filters.
- Stop all action and new-run execution: `PUT /api/v1/admin/operation/kill-switch/global`.
- Stop one agent: `PUT /api/v1/admin/operation/kill-switch/agents/{agent_id}`.
- Pause scheduling by changing agent status or disabling its schedules.

If an action is stuck in `executing`, the scheduler reconciliation re-reads provider state hourly.
Operators can inspect expected/observed state and should not issue an untyped manual Meta request.
If a proposal is approved but blocked by a temporary kill switch, resolve the control and call
`POST /api/v1/admin/operation/action-proposals/{proposal_id}/execute`; all safeguards are rechecked.

## Backups and retention

Back up the PostgreSQL database and legacy marketing store before migrations. SQLite is suitable
for one process and local development only. Use managed PostgreSQL and the standalone worker for
production. The maintenance job deletes old technical snapshots and dependent analyses/findings
after `OPERATION_DATA_RETENTION_DAYS` (90 days by default), and removes expired locks. Audit, action,
configuration, recommendation, and report records are retained.

## Live Meta read verification

1. Use a Meta system-user token with least privilege.
2. Configure business or explicit ad-account IDs.
3. Verify `ads_read` and, when business asset discovery is used, appropriate
   `business_management` access; app review/business verification may be required.
4. Keep `OPERATION_DRY_RUN=true`, `META_LIVE_MODE=read_only`, and
   `META_REAL_WRITES_ENABLED=false`.
5. Run `META_LIVE_READONLY_VERIFY=1 make meta-live-readonly-verify`; inspect the sanitized evidence
   and portable report without printing payloads or identifiers.

The 2026-07-22 validation passed for account alias `2b6c4ddcc5`. Live writes are unsupported even if
the token has a write-capable scope.

## Key rotation

Rotate application/role keys and provider tokens in the secret manager, restart the API, verify
health, and revoke the old values. Never paste tokens into reports, raw ingestion, support tickets,
or the UI beyond the password input; the page keeps the submitted role key only in memory.
