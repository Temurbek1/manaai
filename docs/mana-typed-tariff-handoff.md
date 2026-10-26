# One typed manager decision for tariff enquiries — local, 2026-10-27

Parent-Touch can extract a price/duration enquiry in its original native handoff.
The existing owning tariff workflow validates the terms, asks for missing currency,
reads its bounded catalogue and renders the dated result. It no longer needs a
second model generation just to extract the same enquiry. Parent-Touch remains the
only speaker. Account-status help still delegates through the previous two-call
path; this is not a general replacement of specialist review.

## Captured contract

`MANA_PARENT_TOUCH_TARIFF_HANDOFF_ENABLED=false` by default. Enabling it requires
the existing inline-result/currency/manager profile. Only newly admitted governed
manager turns capture the new schema. Old v32 queued work keeps its exact empty
native arguments and two-call protocol; initialization never backfills admissions.

The new strict native `request_tariff_help` has one required nullable `enquiry`
property. A non-null value contains the exact parent quote, objective, nullable
currency, duration bounds and nullable maximum price in minor units. Account help
uses `enquiry=null`. Child-Safety and reminder calls keep empty arguments. A native
call precedes accompanying prose; provider prose cannot supply a public answer or
host execution receipt. This follows the [official function-calling contract](https://developers.openai.com/api/docs/guides/function-calling#strict-mode).

Verified raw terminal usage is accounted before validating native arguments. One
atomic SQL settlement validates the original call/parent/turn, stores the typed
decision and fingerprint, then enters the existing currency-question or inline
result lifecycle. The runtime placeholder is never published. Invalid/late output
retains verified costs; lost receipts or failed atomic publication keep unknown
holds. Current ownership, Safety priority, consent, five-minute deadline, source
claims/cooldowns and explicit tariff cancellation remain authoritative.

A bound currency answer adds no model generation and preserves the original
terms. Neither language nor location guesses a currency. The current flag fences
new inference, currency resolution and pending source/publication. It never
refunds verified usage, clears an unknown result or replays a request.

Family v33 adds only `manager_tariff_admissions` and `manager_tariff_decisions`.
The originating manager call, admission marker, minimized decision hash and owning
intent must agree before source dispatch. No raw provider reasoning or execution
receipt is stored there. Source/collection schemas, quotas and schedules do not
change: 2000 raw Parent-Touch tokens per parent/day and 2000 Child-Safety tokens
globally/day. No tariff grant, checkout, payment, push or referral reward is added.

Use the current closed v33 reader to preserve history/holds with execution off.
An earlier image refusing v33 is not functional execution rollback. Never downgrade
populated tables or restore an older database over new history.

## Actual model diagnostic

Two new independent synthetic RU/Uzbek cases used the unchanged GPT-5.4 speaker:
**two generations/four HTTP attempts**, including two input-token preflights.
Russian extracted exactly 365 days, 700000 UZS and the lowest-total objective;
Uzbek extracted exactly 180 days/350000 with unknown currency, asked in Uzbek,
then accepted its bound UZS answer without inference. The host returned fictional
dated 599000/299000 UZS quotes. Both outputs and extracted terms were manually
reviewed. Quota usage was **1138/1115 raw parent tokens**, zero Safety tokens and
zero remaining holds. Exact replay made no HTTP request.

Known uncached generation estimate: **$0.007395**, not an invoice, using the
[official standard GPT-5.4 rates](https://developers.openai.com/api/docs/pricing)
of $2.50 input/$15 output per million tokens. No real Firebase, GA4, catalogue,
family, contact, grant/payment or production request occurred. Artifacts remain
private under `output/tariff-handoff-model-20261027/`; never repeat that party.
The tasks differ from the prior v32 party, so these totals do not establish a
causal percentage saving, general quality or production-budget capacity. Removing
one generation is established for these price enquiries, not all chat requests.

## Integration lab and remaining acceptance

Run `make chat-lab-tariff-handoff CHAT_LAB_PORT=8110`. This is the combined,
model-free workspace with a separate marked directory
`data/chat-lab/tariff-handoff-simulation`. The default `make chat-lab` remains
unchanged so existing v32 lab history is not silently upgraded. No new mobile
request/response endpoint is required; use the existing message status/history.

The focused suite covers typed/native parsing, missing currency, old v32 pending
work, account fallback, raw metering, near-day remainder, disable and changed-pair
fences, concurrency, atomic loss, closed readers, restart and midnight. Preserve
the initial settlement-hook regression, test import/type failures and their logs.
Final `make verify` exited **0**: **1690 backend tests**, one skipped/two opt-in
live tests excluded, **26 admin tests/11 suites**, **15 lab checks**, mypy **459
files**, formatting/lint/type checks, production UI build and zero npm
vulnerabilities (`output/tariff-handoff-verify-accepted-20261027.log`). These counts
overlap the focused tests. The earlier full attempt stopped on two test-helper
mypy errors. The next attempt lacked the required dummy inference key during
collection; it made no model request and is not a passing gate. Both original
logs remain. The accepted run explicitly supplied a non-issued test key, with
fake providers; no credential/configuration validation was weakened.

Browser and packaged compatibility evidence is recorded below only once actually
complete.

This remains local and default disabled. Referral is deferred pending its real
API. Wider business/source/model quality, other unfinished AI KOMANDA scenarios
and a separately scoped production release keep the full goal open.
