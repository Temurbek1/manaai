# MANA Parent API — read-only connection

## Scope and status

Implemented `retention.parents.analyze` inside Retention & Loyalty, not a new agent.
The owner explicitly confirmed on 2026-09-30 that this endpoint belongs **only to MANA**.
This confirmation does not establish the product scope of older engagement/Firebase reports.

The supplied `parent-api.md` duplicates `/api/v1` in its URL. A bounded live check confirmed:

- `POST https://api.manakids.uz/api/v1/admin-panel-auth/login/`: 200.
- `GET /api/v1/api/v1/admin-panel-parent/parent-list/?limit=1&offset=0`: 404.
- `GET /api/v1/admin-panel-parent/parent-list/?limit=1&offset=0`: 200.

The actual response has `count`, `next`, `previous`, `results`, plus the documented parent
fields and optional `status`/`children_count`. The implementation intentionally does not
interpret undocumented `status` values. The source document contains a credential and must
not be committed. Runtime credentials are environment variables, not source code.

## What agents can use

Saved evidence contains MANA-only aggregate counters:

- total parents from the API's `count`, number actually sampled and whether more rows exist;
- profile-field presence counts (name, phone, known age, region, district), not their values;
- parents with a current tariff, no current tariff, or inconsistent/unknown tariff fields;
- current tariffs expiring within 7 / 30 days, presence of a valid purchase-record timestamp;
- parents with children / connected children and observed parent-child relationship counts.

The current tariff can be **free**: the upstream query does not filter `is_paid`.
`payment_date` alone is not payment proof. No revenue, paid-customer rate, refunds,
purchase history, automatic renewals or churn are inferred. A missing current tariff is not
cancellation intent. Age zero is unknown. Ambiguous/timezone-free timestamps are not assigned
a timezone or treated as verified expiry dates. Child connections are relationships to this
parent, not app usage, online status or distinct children across all parents.

Only `count` describes the full API population. All other counters describe the first bounded
page, **not a representative sample** and never an extrapolated population total. Names,
phone numbers, location names, exact ages, IDs, avatars and child records are discarded at
the adapter boundary. No raw profile is stored in reports/chat or sent to the model.

## Configuration

```dotenv
MANAKIDS_API_BASE_URL=https://api.manakids.uz
MANAKIDS_API_USERNAME=<read-only service account>
MANAKIDS_API_PASSWORD=<secret>
MANAKIDS_PARENT_SOURCE_ENABLED=true
MANAKIDS_PARENT_SAMPLE_LIMIT=10
MANAKIDS_PARENT_MIN_INTERVAL_SECONDS=21600
```

Enabled separately from `OPERATION_PRODUCT_ACTIVITY_PROVIDER`; enabling this source does not
activate Firebase, GA4 or the old engagement collector. Repository default is disabled.
The local ignored `.env` is configured. **This increment has not been deployed to production.**
Existing production processes, source limits, credentials and schedules were not modified.

## Manual workflow and safety

In a MANA topic of the Retention chat, ask for a fresh parent summary. The model offers a
single inline confirmation card; it cannot call the source itself. The server requires operator
access, checks topic ownership/product/agent, existing kill switches and run admission.
The request uses the existing chat endpoint:

```json
{"request_id":"<unique UUID>","confirmed":true,"kind":"mana_parents"}
```

`POST /api/v1/admin/operation/chat/topics/{topic_id}/analysis` dispatches
`retention.parents.analyze`. Existing professional run/report endpoints work too. No default
schedule is created; the handler rejects scheduled triggers even if a schedule is injected.

- One GET page, fixed endpoint, offset zero, default 10 / maximum 100 parents; no traversal
  of `next`, no phone filters and no bulk export. Decoded response size capped at 1 MiB.
- Zero transport retries. A rejected 401 token permits only one login refresh/read retry;
  403 is terminal without a refresh. Redirects are not followed.
- Shared database admission lease allows one source attempt per six hours (configurable only
  upward, up to 24 hours). Failures consume the interval too. New UUIDs, other administrators
  and process restarts do not bypass it. Idempotency and capability locks remain in force.
- No Firestore, OpenAI, messaging or mutation calls occur in the summary collector.
- Chat/report GETs only read saved evidence. A parent summary is excluded from 360REC chat
  context **server-side**, not merely through prompt wording. Legacy reports remain unverified.
- Failed admission/read yields a controlled saved failure; no automatic rerun.

This follows the existing application guardrail boundary, informed by
[OpenAI guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals).
No unrestricted model tool or new action family was added.

## Verification

Automatic tests use HTTP mocks / fake summaries, not real providers. They cover bounded
pagination, malformed data, byte limits, gzip decoding, duplicate records, PII minimization,
401/403/retry behavior, disabled configuration, manual-only runs, RBAC, persistence,
idempotency, cooldown after failures/restart and MANA/360REC isolation.
Browser E2E uses fake Telegram and fake sources; it checks the parent confirmation, saved
summary after reload, mobile layout and accessibility.

Local checkpoint on 2026-09-30: `make verify` passed (344 backend tests, 2 skipped,
2 opt-in tests deselected; 40 UI tests; lint, type checks, production build and npm audit).
The browser E2E, generated OpenAPI synchronization and repository secret scan passed too.
These are local results, not evidence of a production deployment.

Explicit live smoke (never put this diagnostic command in a scheduler):

```sh
MANA_PARENT_LIVE_SMOKE=1 PYTHONPATH=. .venv/bin/python scripts/parent_api_readonly_smoke.py
```

This independent diagnostic makes one login and a one-row GET in the normal success case,
prints only minimized aggregates and does not write a database. It is not the application
runner and therefore does not acquire its six-hour lease. The 2026-09-30 live smoke passed;
the saved local evidence is `output/parent-api-20260930/live-summary.json`. No paid model
calls, Firebase reads, full parent scans or upstream mutations were made.
