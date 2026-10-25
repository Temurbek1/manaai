# Client Upsell — local price-enquiry checkpoint, 2026-10-25

Upsell now has an executable first scenario in the existing single parent chat:
an explicit parent price/duration request -> Parent-Touch's typed enquiry -> one
bounded shared catalog read or cache hit -> exact dated quote in the same history.
Only Parent-Touch speaks. The owning Upsell service selects catalog facts with
code; the model interprets the parent's request, never creates a payment,
transaction, trial grant, discount, renewal or checkout link.

This is **price/duration selection**, not a completed proactive Basic-to-Premium
upgrade agent. The source proves tariff ID, currency, total price and whole-day
term. It does not prove features, the parent's current entitlement, recipient
eligibility, renewal conditions or checkout. Unknown feature requests stay in
ordinary conversation with that limitation. Child safety/profile facts are not
commercial targeting signals. Referral rewards and other unsupported actions
remain unfinished; this increment does not complete the full agents goal.

## Configuration and API

`MANA_CLIENT_UPSELL_ENABLED=false` stays the default. Its current runtime requires
the existing native source/review/reminder/Retention profile; independent enablement
on older family profiles is not implemented. `MANA_CLIENT_UPSELL_POLICY` freezes
six-hour minimum catalog cooldown, at most four source admissions per rolling day,
100 global/three per-parent pending enquiries and a 180-second claim. Changing
policy/source identity cannot silently reset existing history or limits.

No new mobile endpoint is needed. Use the existing message admission/status and
single history routes. An admitted model choice yields a short host-owned
acknowledgement, then the worker appends one assistant-only result. Polling history,
replaying the original request, reconnecting or restarting never regenerates it.
The mobile UI should keep observing history after the original message completes;
the catalog quote has its own later `turn_id` in that same chat.

For example, “Покажи самый дешёвый тариф на 90 дней в UZS” produces the matching
tariff's total term price. Price ordering and currency/term/budget filters use exact
integer minor units; the model cannot insert a catalog option or price. An explicit
lowest-per-day comparison uses exact rational ordering, not floating point.
The bounded page contains at most 25 plans; at most three are displayed for a list.
An empty match means none in the checked page, never none anywhere in the service.

The request and optional total-budget interpretation are still model judgments.
An exact latest-message quote and strict typed output constrain them; they do not
prove semantic interpretation for every language or adversarial phrasing.
Only new eligible turns capture this contract. An old queued v15 turn never gains
Upsell merely because the database/runtime is upgraded.

## Sources, limits and ordering

The real source is the existing MANA adapter: one JWT login and one bounded
`GET /api/v1/tariffs/?limit=25&offset=0`, no pagination, retry or payment POST.
A global durable SQL claim precedes either HTTP attempt and reserves two attempts.
Its immutable minimized receipt and hash, plus shared latest snapshot, survive
restart. A valid snapshot may be reused for six hours by multiple enquiries/parents;
no family profile/history is shared through that public-price cache. No catalog
HTTP is performed at factory/startup, ordinary GET or without an admitted enquiry.

An unknown/expired source attempt blocks new reads across restart/day changes.
A lost local commit acknowledgement observes the original SQL receipt instead of
rereading the provider. There is no automatic unknown reset/recovery endpoint.
The four-source-admission ceiling is at most eight reserved catalog HTTP attempts
per rolling day, independent of parent count; it is not a Firestore read allowance.

A fresh exact-parent ownership-filtered profile is required before catalog access.
New unbound parent text cancels older pending enquiries, including in-flight results;
the already known shared catalog receipt is retained. Urgent notices, specialist
questions and active/unknown parent work retain existing priority. Ready results
wait in SQL only, within the original claim/profile window; expiry never triggers
another source read. Recipient language is frozen at original turn admission.
This is a parent-requested answer, not unsolicited marketing consent or a push.

Parent-Touch keeps its existing **2000 raw tokens per parent/day** and Child-Safety
its separate **2000 global/day**. Upsell adds no LLM budget: interpretation occurs
in the same speaker call and exact quote rendering needs no extra model call.
Known/unknown holds and raw-usage-before-schema-validation rules remain unchanged.
Longer histories may still hit the existing 2000-token allowance; this is not
unlimited commercial conversation capacity.

## Practical lab and actual evidence

Run `make chat-lab-upsell` and type `Подбери тариф на 3 месяца`, then
`3 oylik tarif tanlang`. The fictional source is explicitly a simulation; the second
enquiry reuses its shared catalog. The other existing safety/reminder/Retention
scenarios remain in this one chat. `chat-lab-upsell-live` is a separate explicit
paid-model mode with fictional profiles/catalog only, no real push/grant gateway.
Do not reset its quotas or use synthetic time with a real model.

The actual paid/catalog diagnostic is separately declared in
`output/client-upsell-model-catalog-postfix-20261025`: fictional parent/child
profiles and real clock, real GPT-5.4 / GPT-5.4-mini, real MANA catalog through its
SQL admission. It completed parent message -> safety review -> speaker enquiry ->
real catalog -> exact quote, **1565 speaker /837 safety tokens**, zero holds,
four OpenAI HTTP attempts/two generations and two catalog HTTP attempts. It selected
real tariff **8**, **162,000 UZS /90 days**, with a bounded-page/eligibility caveat.
Original message replay and another worker pass caused no generation/read/message.
There were three history messages and zero pushes or trial grants.

The uncached generation estimate is **$0.00597275**, not an invoice or proof of
input-count endpoint billing. The preceding failed diagnostic is retained unchanged:
it spent **828 safety tokens**, made no speaker generation/catalog read and failed
at speaker input count. Static inspection found a nullable budget omitted from the
strict schema's required fields. Required-nullable output and the body-empty rule
were corrected; recursive SDK-schema and raw-usage regressions now cover them.
That negative party's generation estimate is **$0.00092850**. The postfix is a new
explicit diagnostic, not a replay or relabeling of its failed request.

One RU price enquiry is narrow evidence, not broad model/UZ quality, real family
acceptance, proactive upgrade eligibility, paid conversion lift or deployment.
Automatic tests use fakes/SDK MockTransport only. Additional final gates/browser
and compatibility evidence are recorded below when complete.

Private family schema **16** adds only Upsell capture/intent/policy/cache/read/audit
tables; source cache stays **4**. Use current closed readers for retained history.
Older v15 code refuses v16 and cannot be called a working rollback. Never downgrade
populated history or restore an old database over new messages. Production and all
existing source schedules, Firebase data, tariffs, SSH, keys and main/audio remain
unchanged. This is a local feature checkpoint, not a released production feature.

## Final local checkpoint

`OPENAI_API_KEY=unit-test-placeholder make verify`, session **63401**, exited **0**:
**1270 backend cases**, one skip/two live opt-ins excluded; **26 admin cases /11
suites**, **10 lab-controller cases**, mypy **378 files**, format/lint/typecheck,
UI build and zero npm findings. Eleven Upsell lifecycle/selection cases, six
strict SDK/schema cases and the v16 lazy-runtime combination are included, not
additional real-model studies. API synchronization, quality-marker and secret
scan (**1103 files**) passed. Early gate failures were test annotations and the
missing explicit dummy key, corrected before that full run; no live test key
was supplied to automated tests.

Owned Chromium at 390px covered RU selection -> UZ selection from the same cached
catalog -> reload -> server restart -> unchanged history. Six displayed messages,
four SQL turns, two published intents, one catalog read and **300 simulated speaker
/300 safety tokens** persisted. The screenshot was inspected; no horizontal page
overflow or application error appeared. The restart navigation briefly reached
Chrome's unavailable-server page before startup, then recovered by observation;
it sent no replacement message. The browser and owned port 8097 are closed.

Image `mana-ai-family:upsell-v16-20261025-local` / `658b61059504` passed the networkless
read-only-root candidate probe: v13 -> v16 upgrade retains every original table
fingerprint and **150 known /1850 unknown safety tokens**, with zero historical
outreach/enquiry capture. Current closed v16 retains the actual-model party's
three messages and every table fingerprint. Its critical source hashes match
host files. Actual previous v15 image `5bd40d810980` refuses v16 with unchanged
bytes; this is **not** a working production rollback. Initial container probes
had a missing import path and then fixture permissions, before database access;
correcting the isolated harness user/path produced these passes. No fixture or
source history was loosened, reset or rewritten to make a test pass.

The full original goal stays active. Next is referral/loyalty against supported
real mechanisms, plus the still incomplete proactive upgrade, broader retention,
GPS/behavior coverage, fleet budget/capacity, quality and phased release work.
