# Conversion account source — local contract checkpoint

The owner reported that the Parent List response now includes `is_paid`,
`created_at` and `agent_trial_used`. The full conversion goal remains unfinished.
This increment prepares a typed source boundary; it does not activate a producer,
connect every parent or deploy a conversion/contact feature.

## Actual source evidence

After the announcement, one bounded login and one filtered production GET for the
previously designated test parent `4` returned HTTP 200:

```http
GET https://api.manakids.uz/api/v1/admin-panel-parent/parent-list/?parent_id=4&limit=1&offset=0
```

The response still omitted all three announced keys, and
`has_active_paid_tariff`. Its existing `payment_date` and `valid_until` were
timezone-aware ISO dates. Only field names/types and parse facts were retained;
no names, phone numbers, raw values, credentials or tokens are recorded here.
No retry, scan, Firebase/GA4 read, grant, push or model call occurred. There was
no additional live call while implementing or testing this adapter.

The supplied `parent-api.md` still documents the old response. Whether this is an
undeployed change or another filtered-response serializer is not established.
The owner was asked whether the change is deployed and whether `created_at`
belongs to the parent profile or the selected tariff record.

## Implemented boundary

- `ConversionAccountSource` is a separate application port, not the child-profile
  ownership port, an operational integration or an LLM tool.
- `ManakidsConversionAccountSource` makes one login and one exact-parent GET per
  explicit invocation. There is no fallback, pagination, retry, redirect, token
  refresh loop, worker registration, default source or automatic invocation.
- HTTPS origin, credentials, wall timeout and canonical positive signed-64-bit
  profile ID are validated. Login is limited to 16 KiB; the account response to
  64 KiB. Duplicate JSON keys, ambiguous booleans, malformed/unaware dates, a
  future record date, another parent or incomplete/multiple rows are refused.
- Failed authentication and a 401/403 read impose the local 60-second login
  cooldown. They never cause the current read to be repeated. Cancellation
  propagates; HTTP, timeout, parse and contract errors return controlled codes,
  not raw provider messages.
- `ConversionAccountFacts` preserves only canonical parent ID, collection time,
  strict nullable paid/trial flags and the three explicit nullable dates.
  Names, phones, child profiles, raw payloads and display tariff names are omitted.
  Missing new keys fail closed; explicit null remains unknown, not false.

## Not yet granted or established

This adapter is **not wired into runtime or conversion event admission**. Before
that step, add durable exact-event dispatch claims and observations so concurrent
requests, lost reads and replay cannot reread a provider or hide an unknown read.
Do not simply insert a network call before the existing idempotent SQL ingest.
No schema migration or new HTTP endpoint is included in this increment.

The response is a selected tariff record. `is_paid=true` is a useful paid-record
fact; `false` alone does not prove that another paid entitlement is absent. Paid
precedence must be confirmed by the owning backend. `created_at` remains an
unclassified date, not automatically `free_started_at`. `payment_date` is not a
verified transaction or an attribution receipt. Lifetime semantics of
`agent_trial_used`, including expired grants, still need source confirmation.

Full tracking also needs population coverage/gap accounting, dated parent
activity, recipient language/timezone and explicit commercial permissions.
The existing full account event contract remains authoritative for those facts.
Real approved checkout/offers, including any actual 15% discount, remain external
inputs; the agent cannot invent them or create payments/transactions.

## Verification

Focused adapter and architecture tests: **80 passed**. All provider responses
are fictional `httpx.MockTransport` fixtures. The new tests cover minimization,
paid/free/unknown values, missing keys, ownership, pagination, auth cooldown,
redirect refusal, JSON/body bounds, malformed dates, timeout and cancellation.
Ruff and mypy (**278 files**) passed before the full gate.

The original full-gate session **50206** stopped at collection because this
isolated checkout has no developer `.env` and the required OpenAI key was absent.
It is not a passing test run. No real key was copied or API called to fix it.
The subsequent explicit-dummy-key **`make verify` session 92804** terminated
with exit **0**:

- Backend: **856 passed, one skipped, two opt-in live excluded**, 39.35 seconds.
- UI: **26 tests /11 suites**; production build passed.
- Ruff/format, ESLint and its 34 compatibility checks, mypy **278 files**,
  TypeScript and npm audit (**zero vulnerabilities**) passed.
- The new adapter's **75 cases** and focused architecture cases are included in
  the totals, not additional tests. No test uses a real provider.
- Secret scan: **453 tracked/unignored files**; `git diff --check` passed.

Production remains unchanged. The previous `efc9645` packaged candidate does not
contain this new adapter; its earlier smoke results are not relabelled as new
candidate or live-source acceptance. The unrelated dirty operational root is
unchanged, and no credentials, private data or `.venv` symlink belong in the commit.
