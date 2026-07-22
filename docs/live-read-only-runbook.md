# Live Meta read-only runbook

## Invariants

`META_LIVE_MODE=read_only`, `META_REAL_WRITES_ENABLED=false`, and `OPERATION_DRY_RUN=true` are
mandatory. Startup rejects write enablement. The Meta adapter has no write implementation, the
executor rejects live proposals before provider dispatch, and the UI exposes acknowledgement only.

The opt-in verification flag authorizes only the bounded GET workflow. It does not authorize POST,
DELETE, budget/status changes, async report creation, notifications, or changes in Ads Manager.

## Preflight

1. Install the token through a secret manager or ignored `.env`; never print it.
2. Configure `OPERATION_ADS_PROVIDER=meta`, Graph API version, app/business identifiers, and either
   discovery or the single intended account.
3. Confirm the request/page/retry/time/account budgets in `.env.example`.
4. Keep the scheduler off for the first run.
5. Run normal hermetic gates: `make audit-verify`.

## Controlled verification

```bash
META_LIVE_READONLY_VERIFY=1 make meta-live-readonly-verify
```

Without `META_LIVE_READONLY_VERIFY=1`, the live section is skipped. With it, the target first runs
the hermetic audit, then the separately marked live test, one bounded live collection/calibration/
nightly-report flow, and the canonical portable-report builder.

Expected result:

- integration health `healthy` and exactly one hashed account alias;
- only sanitized GET operations in logs;
- a completed period ending yesterday in the account time zone;
- compatibility results classified independently from metric values;
- structured and human-readable report persisted;
- live proposals advisory/forbidden, with zero executions;
- sanitized evidence and verified portable HTML generated.

SIGINT or SIGTERM marks the active request budget cancelled; no later page/request reservation is
allowed. A transport request already in flight may finish before process shutdown.

## Nightly operation

Enable the standalone scheduler worker only after the controlled result is reviewed. Use a nightly
schedule after the account-local reporting day is complete. The run remains read-only and uses the
same hard budgets. Alert on unhealthy integration state, authentication/permission errors, rate
limits, stale data, failed reports, or any `write_forbidden` audit event.

## Incident response

- Kill scheduling first; do not attempt a manual provider mutation through the service.
- Preserve sanitized run/correlation IDs and hashed account alias.
- For auth/permission failures, rotate or re-scope the token and repeat preflight.
- For provider/rate failures, keep last-known evidence visible and follow `docs/meta-rate-limits.md`.
- If a raw account ID or token appears in output, treat it as an exposure, revoke/rotate, remove the
  artifact from distribution, and rerun secret/privacy scans.

## Retention

`OPERATION_DATA_RETENTION_DAYS` defaults to 90 and controls daily removal of normalized provider
snapshots plus their dependent analyses/findings. Audit, action, configuration, recommendation, and
report records are retained for operational accountability. Sanitized exported evidence/report files
are deployment artifacts and must follow the same 90-day review/removal policy unless a documented
legal or audit hold applies. Raw provider identifiers needed for joins remain server-side only.
