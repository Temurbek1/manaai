# Conversion account fields — bounded live acceptance, 2026-10-22

Subsequent evidence: the [2026-10-23 reset-account grant test](mana-conversion-grant-live-checkpoint.md)
confirmed the new POST metadata and matching GET creation/expiry for one actual
non-paid grant. The earlier observations and verification below remain unchanged.

The owner requested another check after the backend update. One login and one
exact-parent read now pass the existing `ManakidsConversionAccountSource`.
This removes the previously observed missing-field blocker, not the entire
conversion goal's external integration boundary. Application code remains
**9b343d3**; no parser, private schema, runtime or configuration change is needed.

## Exact live scope

The completed diagnostic session **65953** exited **0**. It started at
**2026-10-22 15:34:29 UTC /20:34:29 Asia/Samarkand** and used the configured
`mana-ai` service account without printing its credentials or tokens:

```http
POST https://api.manakids.uz/api/v1/admin-panel-auth/login/
GET https://api.manakids.uz/api/v1/admin-panel-parent/parent-list/?parent_id=4&limit=1&offset=0
```

Both returned **200**. The GET contained one matching test parent. The minimized
result was:

| Field | Observed contract |
| --- | --- |
| `is_paid` | JSON boolean `true` |
| `created_at` | ISO datetime string with an explicit timezone |
| `agent_trial_used` | JSON boolean `false` |
| `payment_date` | ISO datetime string with an explicit timezone |
| `valid_until` | ISO datetime string with an explicit timezone |

The actual existing adapter returned a validated `ConversionAccountFacts`, not
`conversion_account_invalid`. The observed paid state excludes this account
from free-to-paid targeting; `agent_trial_used=false` does not override that veto.
No names, phones, child records, raw response, credentials or tokens are saved
in this checkpoint. The documentation preserves only the designated ID and
minimized contract facts, not a reusable fresh marketing snapshot.

This was an explicitly requested manual diagnostic, not a runtime admission:
it created no conversion event, SQL source claim, offer, grant, push or chat turn.
There were exactly **two HTTP requests**, no retries, redirects, pagination,
other-parent read, Firestore/GA4 access or model call. Source flags, schedules,
quotas, SSH, keys and production services were not changed. Upstream billing
cost is not measured by this HTTP diagnostic; no paid inference ran.

## Corrected interpretation

The owner had clarified that `is_paid`, `created_at` and `agent_trial_used` were
initially added to successful grant POST responses. Expecting that clarification
alone to change Parent List was incorrect. The later GET result above separately
confirms the fields are now readable. A grant POST remains a real mutation and
must never be used as a subscription-status or trial-history probe.
No successful live grant receipt was requested or verified by this check; the
GET result does not independently establish the new POST response shape.

The old missing-key receipts and qualified model/candidate evidence remain
unchanged. Do not relabel old reads as successes or repeat paid model parties to
compensate for source integration. No broader source acceptance is implied by
one designated paid account.

## Remaining work toward the unchanged full goal

1. Confirm whether `created_at` dates the parent or the selected tariff purchase,
   and establish the actual free-access start/end. Do not claim seven free days
   from an unclassified timestamp.
2. Confirm paid-entitlement precedence when records overlap and lifetime
   `agent_trial_used` semantics, including expired grants. A selected paid record
   is a veto; a selected non-paid record is not proof of no paid access elsewhere.
3. Connect authoritative, dated parent activity and language/contact preferences,
   full-parent initial coverage and an idempotent backend event producer with
   gap accounting. Child safety facts are never commercial targeting inputs.
4. Supply real owner-approved paid offer/checkout terms. A test 15% fixture is
   not a working discount. The agent creates no payments or transactions.
5. Complete separately scoped real-channel/candidate/release acceptance. Nothing
   here enables conversion, source refresh or customer contact in production.

The [backend handoff](mana-conversion-backend-events.en.md) now distinguishes
available account keys from these remaining requirements. The objective is not
complete, and no narrower fake-only milestone replaces it.

## Local regression gate

Full **`make verify` session 32859** terminated with exit **0**:

- **892 backend tests passed**, one skipped and two opt-in live tests excluded,
  in 43.03 seconds. Tests use fakes, not the live account above.
- **26 UI tests /11 suites**, production UI build, Ruff/format, ESLint and its
  34 compatibility checks, mypy **282 files** and TypeScript passed.
- Dependency audit found **zero vulnerabilities**. Secret scan passed for
  **462 tracked/unignored files**; `git diff --check` passed.

An explicit dummy inference key was used for the local gate. No actual model,
source, grant or push request was introduced by the tests. This increment changes
documentation only; it does not relabel the earlier packaged image or synthetic
cohorts as real end-to-end conversion acceptance.
