# Coalesced child-source reviews — local, 2026-10-25

The [autonomous single-chat objective](mana-autonomous-agents-plan.md) now has a
shared source-change consumer for battery and app counters. It uses the existing
Child-Safety queue/model/raw-usage meter, then sends useful qualified guidance or
one information need through Parent-Touch. No second parent chat or independent
specialist speaker is introduced. Model-selected source reads and 09:00/15:00
collection continue using the same ownership-filtered source cache.

This is local work. `MANA_FAMILY_SOURCE_REVIEWS_ENABLED=false` remains the default;
production, source schedules, SSH, keys, main/audio, customer data and tariffs were
not changed. The feature requires the existing native observation/app/source-safety
configuration. It adds private family schema **13** and source-cache schema **4**;
no operational database migration or generic `/mana-ai/analyze` route is added.

## Source changes and shared acquisition

New v4 source changes freeze their admission and source identity at capture. A
three-second quiet interval coalesces queued own-child changes, provided no source
read for that child is still pending. The collector's calls normally finish within
that interval; slow/changing inputs can produce later distinct reviews, not a
claim that every possible acquisition is one atomic batch.

The host freezes at most two registered source snapshots and their exact hashes,
original collection/measurement dates and changed-source labels. Unchanged cached
sources can provide context when their provider check is within the configured
six-hour window. That check does not make an old sensor measurement current.
More than 100 pending events refuses the whole review rather than treating a
prefix as complete. Stale/disabled/overflow events stay recorded; the original
source change history is retained. New capture does not backfill old source events.

The source bundle has a factual digest for deduplication and an independent hash
binding its exact frozen payload/dates. Recollection, new UUIDs, equivalent full
snapshots or a process restart cannot create another paid analysis of unchanged
context. One family/source read still serves several allowed consumers. Limits
remain **100 source admissions /200 conservative Firestore units per rolling
24h**; cached reads still count as admissions and recheck fresh ownership.
App API reads reserve no Firestore units; backend resource costs remain unpriced.

The source-request ledger can bind a host-owned native Child-Safety job before
reading. This is attribution, not tool authority: the original SDK call, scope,
child alias, protocol and verified raw usage still authorize the read. Native
results do not produce a second background review. A native cache hit can consume
a still-queued event for the exact same snapshot. Already admitted independent
reviews are not cancelled or refunded to merge them into a later parent request;
that new parent intent is a distinct conversational context.

New v13 turn tags record admission provenance outside legacy JSON. Historical
captured native invocations retain their exact original protocol/prompt/pairing;
when they actually read after upgrade, the host records attribution without giving
them another tool or recapturing old events. Old queued analysis requests, unknown
receipts and native histories are not rewritten into source reviews.

## Metered review and sole-speaker delivery

A private cache claim precedes fresh profile ownership/age lookup. The prepared
intent freezes that lookup, and a separate dispatch claim precedes SQL admission
to the existing family queue. A lost admission acknowledgement observes the exact
local request ID; it does not issue another admission. Unknown preparation/admission
retains a hold. A preparing claim expires to explicit `unknown` after the configured
180-second lease, never to permission for another profile lookup. A late ownership
receipt cannot revive it. That lease must exceed the configured profile timeout
by more than ten seconds.

The worker rechecks fresh ownership before inference. A source review is one
bounded **tool-free** model call; it cannot obtain more data or write authority.
It receives only the frozen own-child snapshots and bounded conversation/managed
needs. Its strict response has `analysis=null`, qualified `followup_summary`,
`notify_parent` and at most one typed information need. It does not manufacture
fresh sensor findings or execute controls. Verified raw terminal usage is charged
before decision parsing. Invalid decisions retain known costs; lost receipts keep
unknown token reservations across restart and midnight. No retry/fallback or
budget increase is introduced.

Only Parent-Touch publishes the result, using the existing independent contact
context, recipient language, single-question queue and durable message/push outbox.
A review can be saved without sending an unsolicited message. Review notices are
ordinary assessment context, with `insufficient_data`, no fabricated observation
range, explicit partial-data notes and exact minimized source facts. That
presentation is a source overview, not proof of a fresh Family Digest sensor
measurement or a new executable capability.

A passive chat entry can be saved independently of push permission. Ordinary
source-review pushes/questions wait for the existing configured quiet hours in
the verified recipient timezone **before** claiming an external send. Consent,
expiry and outbox limits still apply; an expired queued notification is suppressed.
An actual urgent notice retains its existing priority. No real push gateway or
free-trial executor is present in the lab.

The budgets remain **2,000 raw tokens per parent/day for Parent-Touch** and
**2,000 raw tokens for the whole server/day for Child-Safety**. Coalescing reduces
work but does not establish that those limits can analyze 219,873 parents. The
fleet capacity gap from [collection](mana-family-collection.md) remains; no smaller
population has been substituted for the goal.

## Data semantics and language

App counters remain a partial first page with an unknown measurement period and
timezone. Overlapping counters are never added into daily screen time or a full
ranking; collection/provider-check time is not their measurement interval.
Battery connectivity stays unknown and an old reading is explicitly dated. App
names/provider text/chat are quoted inputs, never instructions or grants. MANA
parent GA4 behavior is not child activity; 360REC data is not mixed into this lane.
Only backend-verified own-child inventory is used for a family.

The internal review can use a presentation language; Parent-Touch independently
uses the recipient's verified language or current conversation. RU and Uzbek Latin
remain supported. Neither presentation language nor a source snapshot supplies
consent or ownership. Normal mobile integration still needs only message admission,
message status and the single durable history.

## Actual model diagnostic and cost correction

One independent synthetic party used the actual strict SDK/SQL review/delivery
path with a dated fictional battery and **ten of 24 fictional app counters**,
unknown period/timezone and an instruction-like app name. It made **four OpenAI
HTTP calls**: count/generate for Child-Safety and count/generate for Parent-Touch.
No live family/MANA/Firebase/GA4/push/grant request was made. It is a separate
explicit diagnostic, not a reset of any previous party or production quota.

Raw settled receipts:

| Role | Actual model | Input | Output | Total |
|---|---|---:|---:|---:|
| Child-Safety | `gpt-5.4-mini-2026-03-17` | 1,168 | 108 | 1,276 |
| Parent-Touch | `gpt-5.4-2026-03-05` | 1,377 | 95 | 1,472 |

Both holds are zero. The specialist preserved partial coverage, unknown period and
lack of proven urgency; the Russian reply retained those qualifications and a
safe charging suggestion. It did not follow the instruction-like app name or
claim 48 hours of daily screen time. The Russian phrase equivalent to “total screen
day” is awkward; this one case is not broad language/model-quality acceptance,
real-child analysis, conversion/retention improvement or all-parent throughput.
No paid test was repeated after reviewing its output or correcting cost arithmetic.

The original harness incorrectly priced both roles at mini rates, recording
`$0.00282225`. It is retained as negative evidence. An **offline correction** used
the actual receipt model names and the fetched official standard rates: mini
$0.75 input/$4.50 output and GPT-5.4 $2.50 input/$15 output per million tokens.
The corrected uncached generation estimate is **$0.0062295** ($0.001362 safety +
$0.0048675 speaker). This is not an invoice, counting-endpoint price or total
account bill; no cache discount, other services or future rate is assumed.
See [official pricing](https://developers.openai.com/api/docs/pricing) and
[the mini model contract](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
Private artifacts: `output/source-review-model-20261025/`, especially original
`result.json`, original harness text and additive `pricing-review.json`. Do not
replace their receipts with a later pass or rerun them automatically.

## Local usage and outstanding acceptance

`make chat-lab-source-reviews` runs the loopback-only simulation in its own marked
directory. Trigger the fictional app and battery sources within the coalescing
interval, then wait for the first Parent-Touch message. A later Uzbek app question
uses the existing shared cache. Refresh/reload/restart only observes persisted
work; no browser action autonomously retries a lost POST.

The explicitly paid `make chat-lab-source-reviews-live
CHAT_LAB_ENV_FILE=/path/to/server.env` still has fictional data and no real push
or tariff executor. It uses the configured models and durable 2,000+2,000 diagnostic
allowances, not unlimited generation. Never share mode directories or mount this
lab on a production ingress.

The complete goal remains unfinished: GA4/shared administrative aggregates,
remaining child sources, reminders, the other specialists and owning actions,
broader semantic/model/language/source/consent/channel acceptance, measured fleet
capacity and a separately approved release/rollback still remain. Engineering
checks below do not close those requirements.

## Completed engineering checks

- Final `make verify` **12329** exited **0**: **1,222 backend tests passed**, one
  skipped, two opt-in live tests excluded; **26 admin tests /11 suites**, **seven
  lab controller tests**, formatting/lint, mypy **362 files**, TypeScript, production
  UI build and npm audit (**zero vulnerabilities**) passed. Focused counts overlap.
- The ten dedicated source-review cases cover one combined review/notice, native
  read and exact-cache attribution, unchanged recollection, revoked ownership,
  raw invalid-decision billing, unknown model holds across restart/midnight, lost
  committed SQL admission, quiet push before claim and lost preparation expiry.
  The true production runtime factory was exercised with fake SDK/provider clients:
  it constructs the shared v13/v4 services/workers and shuts down with **zero
  external requests**. The initial test replaced a class with a lambda and failed
  an actual `isinstance`; the corrected subclass harness passed. That original
  harness error remains in `output/source-review-actual-runtime.log`.
- The earlier combined suite exposed another composite lab-state race: new history
  could be paired with an older safety budget/assessment read. The lab now uses a
  single SQL observer's `data_version` to retry only SQL projection reads across
  commits, at most five times, and closes it explicitly. No source/model request is
  repeated. The negative `output/source-review-combined-tests.log` is retained;
  only the subsequent focused/full gates are passes. Stable state is not a claim
  of one atomic transaction across the separate family/source databases.
- Actual copied **v12/v3 → v13/v4** initialization preserved every pre-existing
  table fingerprint, 150 known model tokens plus 1,850 unknown held tokens and an
  independent unknown source receipt reserving two units. Historical source events
  were not recaptured. Packaged current closed/reconstructed readers preserve
  these rows and the completed new source-review diagnostic history, with zero
  provider/model clients. This is not full old queued-native execution or release
  acceptance; that broader migration path still needs its own test before rollout.
- Final local image `mana-ai-family:source-reviews-v13-20261025-checkpoint` is
  `sha256:fbe6b567300e44419c3cebe18580a69dcaaedd52e916ce953b6e3f4b1fb62795`.
  Its networkless/read-only/private-tmpfs check passed
  (`output/source-review-checkpoint-image-compat.log`). Actual previous image
  `4f0f92c52c60` refuses family 13 and source 4 with copied file bytes unchanged
  (`output/source-review-old-image-refusal.log`). This proves refusal, **not a
  working old-image rollback**. Current-code closed history is a narrower check;
  never restore an old database or downgrade populated history to make rollback pass.
- Owned loopback Chromium tested two source buttons within the coalescing interval:
  one two-snapshot review, one assistant-first chat message and 150 simulated safety
  /150 speaker tokens. Re-reading app data from cache created no additional review.
  An explicit Uzbek parent question then used the same cache and returned a qualified
  Uzbek answer. Final fake totals were 450 safety /300 speaker tokens; four source
  admissions, two fictional provider reads, two cache hits, two conservative
  Firestore units and one source-review bundle. Server restart/reload preserved
  exact history, review ID, costs and SQL source counts without new reads. Desktop
  and 390px screenshots were inspected with no page overflow. Original-session
  polls received 401 after restart until fresh navigation; they never reissued work.
  Both owned browser and server are closed. Artifacts: `output/source-review-browser-*`.

No new real Firebase/GA4/MANA read or real contact/action occurred in this increment.
The sole new paid model party is the qualified synthetic case above; all automated
checks remain fake/MockTransport-only. The full goal remains active and production
activation/backup/compatible fallback and external acceptance remain separate work.
