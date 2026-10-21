# Conversion account verification — local v10 checkpoint

This follows [the strict source adapter](mana-conversion-account-source-checkpoint.md).
The original goal remains track every MANA free account, select timely approved
offers and measure actual paid conversion through the sole speaker Parent-Touch.
This increment connects account verification to backend event admission locally;
it is not a source population producer, contact release or completed goal.

## Explicit activation and cost bounds

`MANA_CONVERSION_ACCOUNT_SOURCE_ENABLED=false` by default. Enabling it requires
the existing Conversion/commercial/review-first runtimes and approved offer catalog.
It adds no source scheduler, listener, scan or default production configuration.
Only an eligible explicit `POST /api/v1/mana-ai/conversion-agent/events` may claim
one account verification. Known SQL events replay before any new read.

`MANA_CONVERSION_ACCOUNT_READ_LIMITS` defaults to `cooldown_seconds=21600` per
parent and `daily_limit=100` globally over rolling 24 hours. SQL commits claims
before network dispatch; failures count too. Restart/midnight cannot reset them.
One claim permits at most one login plus one filtered Parent List GET. Ineligible,
opted-out, converted, contact-cooldown or no-available-offer candidates do not
spend source reads. No model call is needed for verification or offer templates.

These are request ceilings, not a statement that upstream infrastructure is free.
No direct Firebase/GA4 read or paid inference was performed in this increment.

## Durable contract

Private SQLite v10 adds `conversion_account_reads`, binding canonical parent ID,
event UUID/revision, exact snapshot digest, dates and minimized typed observation.
The claim commits before the provider request. One parent's pending/unknown read
blocks further candidate reads even with another nonce, higher revision or day.
GET never repairs, requeues, cancels or dispatches it.

A verified observation and final proposal admission have separate SQL commits.
If the acknowledgement is lost between them, exact POST replay finalizes only SQL
from the existing receipt. It never repeats the provider call. A newer paid event
fences the older finalization; its verified source receipt remains retained.
Known refusal may be superseded only by a fresh higher-revision event after read
limits; unknown/pending outcomes have no automatic rearm/reconciliation endpoint.
Cancellation retains an unknown claim; a process lost before settlement retains
pending. Raw upstream error prose is not persisted.

Before publication, frozen offer availability, trial dispatch and an unclaimed
commercial push, the captured proof must still match the exact snapshot and be
fresh. Paid/unknown status, conflicting trial history/expiry or a pending/unknown
read veto contact. Already externally claimed sends cannot be undone by this gate;
push queueing remains distinct from delivery. Existing safety priority, explicit
permissions, offers, contact caps and Parent-Touch/Child-Safety budgets remain.

The extra backend-only SQL observer is:

```http
GET /api/v1/mana-ai/conversion-agent/source-observations/<event_id>?parent_id=123
Authorization: Bearer <ISOLATED_MANA_PARENT_CHAT_BACKEND_TOKEN>
```

It returns `pending`, `verified`, `refused` or `unknown`, dates and minimized facts
only. The trusted backend token and `Cache-Control: no-store` remain mandatory;
another family's ID cannot retrieve the receipt. Disabled conversion observers
still return controlled 503s; stored SQL/history are retained.

## What these fields do not prove

The full backend event still supplies authoritative subscription precedence,
actual free-start/end dates, dated parent activity, language/timezone and marketing
consent. Parent List is a veto/check, not a replacement for that producer.
`created_at` is retained but never mapped to free start; its meaning is unconfirmed.
`is_paid=false` on a selected record does not prove no other paid entitlement.
`agent_trial_used` lifetime semantics and paid precedence still need source-owner
confirmation. A payment timestamp, free-day grant or model text is not an actual
paid-conversion receipt. The agent creates no payments/transactions/discounts.

A second manual bounded post-announcement login + exact-parent `4` GET returned
200 but still omitted `is_paid`, `created_at` and `agent_trial_used`. The actual
adapter correctly refused it as `conversion_account_invalid`. Only field types
and HTTP statuses were retained. No retry, other parent, write or raw values were
used. This is fresh negative contract evidence, not live-source acceptance.

## Compatibility and verification scope

New v10 retains v9 history without upgrading old events into source approval.
Old saved event receipts replay without fetching; their unverified queued offers
cannot acquire new source permission. Current same-code closed-v10 retains the
source ledger, chat history and the 2000-token unknown chat hold. Old v9 readers
refuse v10; never downgrade tables or restore an old database over new history.

Focused current-provider/SQL/HTTP/runtime tests are fictional, including actual
HTTP adapter through authenticated ASGI -> SQL -> Parent-Touch first publication,
exact replay, global race/cooldown, process-loss checkpoint reconstruction,
cancellation/unknown retention, paid-event fencing, stale source veto for trial/
push/context, legacy v9 replay and closed-v10 fingerprint/hold preservation.
They do not establish real all-parent coverage, real sales-quality improvement,
designated-device push delivery, packaged-candidate/rollback or production acceptance.
The earlier `efc9645` candidate does not contain v10.

Final **`make verify` session 7192** terminated with exit **0**:

- **883 backend tests passed**, one skipped, two opt-in live excluded, 38.16s.
- **26 UI tests /11 suites**, production build passed.
- Ruff/format, ESLint and 34 lint compatibility checks, mypy **280 files**,
  TypeScript and npm audit (**zero vulnerabilities**) passed.
- Product schema is **42 paths /46 operations**; generated OpenAPI/TypeScript
  synchronization passed. The only added path is the saved source observer.
- Secret scan: **456 tracked/unignored files**; diff check passed.

The earlier full-gate sessions 30074 and 73533 failed only on the old exact
documentation path/count assertions. The intended observer was added to the
strict allowlist and both counts; the comparison was not relaxed. The focused
docs/source suite then passed 32 cases before the final full gate. Focused counts
overlap the full suite and are not additional coverage. Tests use no real models,
pushes, grants or source reads. Production is unchanged.

The subsequent [actual hermetic candidate checkpoint](mana-conversion-account-candidate-checkpoint.md)
verifies packaged v10 and prior v9 modes, unchanged source/legacy fingerprints
and current same-image closure/reconstruction. It is not an old-image rollback,
real source/model/contact acceptance or production activation.
