# Scheduled dated usage to the single parent chat — local checkpoint, 2026-10-25

The shared 09:00/15:00 Asia/Tashkent collector can now acquire one dated family
app-counter page, reuse it for the family's children and native chat tools, and
send changed facts through the existing Child-Safety review and Parent-Touch
communication lifecycle. A parent need not write first. Parent-Touch remains the
only speaker; the mobile application keeps its existing message/status/history API.

This is local, default-disabled work, not a production release or full-goal
acceptance. The preceding manual native workflow and its original failed model
parties remain documented in [the dated source checkpoint](mana-dated-source-workflow.md).

## Configuration and immutable capture

The new flags `MANA_FAMILY_DAY_REVIEWS_ENABLED` and
`MANA_COLLECTION_DAY_USAGE_ENABLED` default to false. They require the existing
dated-tool/source-review/shared-collector profile; reviews require
`MANA_FAMILY_DAY_USAGE_ENABLED`. Collection timeout validation includes the whole
60-second dated read plus the existing safety margin. No source is read at startup.

Private schemas are family **19**, source cache **6** and collection **3**. Only
new windows, inventory-page claims, source admissions and review jobs capture the
new scope. Old queued work, unknown claims and earlier native turns never upgrade.
The collection ledger freezes its exact source-cache binding. Turning a consumer
off stops new dispatch and fences late publication without discarding verified
model costs, history, unknown holds or original claims. Re-enabling resets nothing.

For a newly captured dated window, the query label is the calendar day preceding
its frozen scheduled occurrence in Asia/Tashkent. One family/day target replaces
new undated per-child app-counter collection in that window; battery targets
remain independently governed. No hourly scan, missed-window catch-up, transport
retry or second specialist-specific collection is introduced.

## Shared facts, reviews and communication

Fresh ownership is checked before acquisition and every selected-child cache use.
One bounded family/day page can serve siblings. Query date and normalized app
counters form each child's semantic fingerprint; another sibling's change or a
new collection timestamp alone does not reanalyse an unchanged child. An older
query cannot replace a newer review head. Native selection consumes only its
matching queued child/day/fingerprint, preventing duplicate background review.

Captured changed battery/app/day facts share the existing review queue and
coalescing policy. Dated reviews use safety context **4**, with frozen facts and
the original 2000-token global safety ledger. There is no second specialist
budget or model-created source/action authority. Empty or missing child rows
are unavailable evidence, not zero usage or a reason to generate an empty report.

Parent-Touch preserves the YYYY-MM-DD query label and distinguishes it from
sensor observation, collection and SQL-save dates. Counter periods/timezones and
partial app coverage stay qualified: these are not verified daily screen time,
a complete ranking, behavior causality or current danger. One durable assistant
message precedes an independently permitted neutral push. Existing recipient
language, purpose consent, quiet hours, priority, question binding and opt-out
rules still apply. A source switch is never contact consent.

## Limits and cost accounting

The original limits remain: **50 source targets/window**, **100 shared source
admissions/rolling 24 hours**, six-hour provider cooldown, bounded inventory pages,
and existing conservative Firestore document units. Dated targets compete within
these ceilings rather than adding another allowance. The manifest marks their
scope as `family`; selected-row availability does not prove every child's data
or whole-population coverage. Unknown family reads block new-nonce/sibling/window
redispatch and survive restart.

For two successful windows, planned dated acquisitions are at most
`2 * distinct_selected_families`, reduced by valid shared cache hits and further
limited by the shared source budget. Each miss includes the existing bounded
ownership/API path. A cache hit still checks ownership, so it is not zero HTTP.
The Manakids counter endpoint directly consumes **zero Firestore document units**
in this service; backend database/network costs remain unknown. Battery reads
retain their own conservative document-unit accounting. Inventory attempts and
model calls have separate existing ledgers; a source admission is not an HTTP count.

Model cost is the sum of terminal raw input/output receipts at the configured
model rates, with unknown submissions kept reserved. Parent-Touch remains
**2000 tokens/parent/day**, Child-Safety **2000 tokens/server/day**. This small
global pool does not establish capacity for the reported fleet. No dollar invoice
or complete-population cost is inferred from fictional source counters.

## Actual checks

- Full `OPENAI_API_KEY=fake-verification-key make verify`, original session
  **66213**, exited **0**: **1404 backend cases**, one skip/two excluded live
  opt-ins, **26 admin cases/11 suites**, **10 lab-controller cases**, mypy
  **403 files**, lint/format/types/build and zero npm vulnerabilities. API sync,
  quality-marker and secret scans passed. Tests use fake/MockTransport providers.
  Earlier fixture-path, type-narrowing and test-annotation failures remain in
  their original logs; they are not passing runs.
- The focused cases cover two windows/cache reuse/changed-only communication,
  empty data, unknown reads across windows/restart, mid-read flag changes,
  disabled queued reviews, late verified costs without publication, sibling
  fingerprints, old pending captures, immutable disabled windows and the shared
  target ceiling. The full gate includes them; counts are not additive.
- One distinct actual-model party used fictional battery/day facts and produced
  **one assistant-only first-contact message**, **913 safety/1219 speaker tokens**,
  zero holds, four OpenAI HTTP attempts/two generations, and no additional read,
  review, job or generation during SQL observation. Count preflights were
  **831/1115**. There was no live family/Firebase/GA4/push/grant/payment request.
  The answer preserves date/partial-data uncertainty but has awkward Russian
  name inflection and the internal word “фильтр”. These are presentation
  negatives, not polished/broad RU/UZ quality acceptance. Do not replay the party.
  Receipt: `output/dated-collection-model-20261025/result.json`.

## Packaged compatibility and browser

Image `mana-ai-family:dated-collection-v19-20261025-local`,
`sha256:8ed752964ac3d056cacfe8bcf218a444932cedf1d91004c3c1d9596149f7d700`,
matches all **24** changed application Python hashes and contains no `.env`.
Networkless/read-only-root/user-1000 probes use `APP_ENV=production` with unrelated
Telegram authentication explicitly disabled only in the isolated fixture. This
does not prove the complete production configuration/startup or an execution rollback.

Actual old v18/v5 fixtures upgrade without changing any original table fingerprint
or recapturing old source work; an old v2 collector's unknown inventory claim also
survives its v3 upgrade. The original family fixture retains **300 known/1700
unknown** safety tokens on its historical day. A new packaged collection/review/
first-contact loop followed by a lost model receipt retains **two messages and
150 known/1850 unknown** tokens. Current closed readers preserve settled history,
ledgers and unknown source/collection holds. Known unsubmitted admissions are
observed through their ordinary expiry before the final fingerprint comparison;
unknown holds are not released. The actual preceding `c92073bc996c` image refuses
new v19/v6/v3 databases with bytes unchanged: refusal is not a working rollback.
Never downgrade populated schemas or restore old databases over newer history.

Final logs are `output/dated-collection-image-compat-settled-20261025.log`,
`output/dated-collection-actual-old-readers-configured-20261025.log` and
`output/dated-collection-image-source-hashes-20261025.json`. Original negative
harnesses retain the wrong private attribute, historical-day mismatch,
pre-expiry fingerprint baseline and missing collection clock; only the corrected
final probes passed. They made no external request.

Run `make chat-lab-day-collection` for the fictional fixed-clock lab. It forbids
paid models/live sources. Owned Chromium at **390 px** exercised empty history,
the 09:00 first contact, a parent's Uzbek dated question using the shared cache,
and 15:00 unchanged collection. The existing independently permitted zero-model
Retention expiry reminder also ran. Final state: **four messages**, **300 simulated
speaker/450 simulated safety tokens**, two windows/two source changes/two safety
jobs. Afternoon collection added no inference/message. Actual server restart
retained every family/source/collection table fingerprint; reload added no work.
Screenshots were inspected with no page overflow/browser errors. The owned browser
and port 8097 server were closed. See
`output/dated-collection-browser-20261025/result.json`.

## Still open in the full objective

Real network timing may split a day review from later battery enrichment; the
fixed-clock fake coalescing result does not prove real-fleet optimal batching.
Global-budget admission before additional review ownership GETs can improve.
GPS identity/measurement semantics, referral contracts, proactive commercial
eligibility, broader language quality, complete administrative owners/actions,
capacity and a separately approved production release/rollback remain open.
This increment changed no production service, source schedule, main/audio API,
SSH/key, cloud data, customer tariff or real contact.
