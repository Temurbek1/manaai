# Completed-day app counters — qualified source port, 2026-10-25

Subsequent local integration: [dated native source/cache/chat workflow](mana-dated-source-workflow.md)
now implements the captured v18/v5 path. The source-only findings and original
negative/live diagnostics below remain historical evidence, not retroactive passes.

The documented bulk usage endpoint applies `username`, `start_date`, `end_date`
and `page`; the exact-child detail endpoint does not establish those filter semantics.
The new `ManakidsFamilyDayUsageSource` reads one explicit completed calendar day
for a freshly verified MANA family. At the original `cb54a9c` checkpoint this was a
source port without runtime/cache/native-tool wiring. The linked subsequent local
increment adds those connections; the collector/mobile API remain unchanged.
Do not present it as an already released daily report or another top-level agent.

## Actual contract findings

The original bounded date discovery made four HTTP attempts: login, exact Parent
List for designated test parent 4, and two first-page family usage GETs for October
24 and 23. Both pages contained five owned children. Counter labels matched their
requested dates, with respectively 10 and 20 returned counter rows. This is evidence
that the documented bulk filter is usable; it does not prove foreground screen-time
units, complete app history, precise intervals or a provider timezone. No raw app
names, child identities, parent phone or records were retained in diagnostics.

The first implemented-adapter party made three attempts, all HTTP 200, then returned
a controlled validation failure. Its original result saved the failure class but
not its code; do not claim a more precise proven cause or rewrite that receipt.
An independently admitted metadata-only query for a different day, October 22,
showed four empty child pages with **total_count=0, page_count=1**, and one partial
10-of-20 app page. All five children belonged to the fresh ownership set.

The empty-page regression failed before the fix (one failed/two passed). The shared
counter parser now accepts page counts 0 or 1 **only for zero count and zero rows**.
It retains exact count/page checks for nonempty pages and refuses an empty result
claiming multiple pages. A missing page has no measured zero screen-time conclusion.
This also corrects the existing detail adapter's handling of that benign convention;
it does not retry its previous failures, refund source costs or change stored facts.

A distinct postfix adapter party queried October 21 after that correction: exactly
login +one ownership GET +one family usage GET, all 200, five-of-five owned child
rows, ten counters, one partial app page, exact calendar labels and no serialized
phone/name. This is actual adapter acceptance for that day, not a replay/pass for
the failed October-24 party or full agent/model/channel acceptance.

Original immutable diagnostic directories:

- `output/child-usage-bulk-period-20261025`
- `output/family-day-usage-adapter-live-20261025` (negative)
- `output/family-day-usage-metadata-20261025`
- `output/family-day-usage-adapter-postfix-20261025`

These phases made **13 HTTP attempts total**, no retries. They made zero direct
Firestore/GA4 or model calls, messages, pushes, grants or payment mutations. This
does not price the backend's own database/network work or claim zero indirect cost.

## Scope, dates and minimization

`read_usage_lookup` reuses the existing exact-parent profile parser/authentication.
The ephemeral `ParentUsageLookup` retains connected child IDs and collection time;
its account username is excluded from serialization and repr. It never becomes
model data, provider credentials, arbitrary query access or a contact permission.
Ordinary `read` retains its original context contract even when no phone is present.

The source performs one fresh ownership lookup for the whole family, then one
fixed MANA usage GET; authentication is shared. There is no per-child reread,
pagination, redirect/fallback, listener, automatic retry or startup call. Returned
child IDs must be unique and inside the fresh connected-child set. Stale/future/
foreign lookup, malformed counters, ignored date labels, inconsistent pagination,
auth failure, timeout, duplicate JSON keys and oversized bodies fail closed.

Bounds: one of the preceding 31 completed query-calendar days (Asia/Tashkent),
one first page, at most ten returned children/ten apps per child/ten counters per
app, 256 KiB and a maximum 60-second whole-read timeout. Missing child rows remain
absent, not zero use. `complete_family` describes represented connected-child IDs;
individual app coverage and measurement quality are separate.

The returned `FamilyDayUsagePage` freezes the requested day, ownership acquisition
and response collection dates, exact per-child counters and app-page limits. Every
counter's naive calendar label must match the requested day. Provider timezone,
`observed_at` and verified measurement period remain unknown. The query calendar
is not a verified recipient/device/provider timezone. Counters can overlap or sum
beyond 24 hours; never turn them into total screen time or a complete ranking.

## Engineering evidence

Final `make verify` **67155** exited **0**: **1358 backend cases**, one skip/two live
opt-ins excluded, **26 admin cases /11 suites**, **10 lab-controller cases**, mypy
**391 files**, formatting/lint/types/build and zero npm findings. Automated providers
are fake/MockTransport-only. Source cases cover privacy, one shared auth/ownership
read, family/date mismatches, missing/partial data, empty-page variants, errors,
lookback bounds, oversized/ambiguous responses and unchecked adapter annotations.

Image `mana-ai-family:day-usage-port-20261025-local`,
`sha256:6a07ddfb4cb380549383d611f5376314c00328b01ccf24af2998543824c5b35d`,
passed a packaged MockTransport smoke with network disabled/read-only root: three
mock HTTP attempts, supported empty page, no serialized lookup or invented period.
Critical source hashes match. Existing closed family evidence preserves every old
table fingerprint, three messages and 150 known/1850 unknown safety tokens.
No schema migration is introduced: family/source/collection stay **17/4/2**.
These are narrow image/source checks, not a production rollout/rollback or browser
daily-report acceptance. No UI flow or native tool set was changed in this increment.

## Required integration, not completed by this port

Add a separately captured dated-source protocol and parent/day cache/receipt binding;
do not silently replace old v17 `app_usage` calls, scope digests or snapshots. Use
the existing shared read ceilings, six-hour cooldowns and unknown-result holds,
with one acquisition shared across permitted children/consumers. Fresh ownership
still gates cache use; missing rows do not erase another child's evidence.
Then wire qualified facts through Child-Safety and Parent-Touch, extend the local
chat scenario, and verify deduplication, real model budgets/quality, restart and
compatible release/rollback. Do not activate new bulk reads or a production source
as a side effect of this manual diagnostic. The full agents goal remains active.

The separate conversion investigation used three exact-test-account HTTP attempts:
profile username matched Account API, and Account registration preceded selected
tariff creation. The inspected account's top-level fields supplied country but no
language/timezone/consent settings. Country metadata was not substituted for personal
preferences or permissions; these records do not establish seven days of free use.
See `output/conversion-profile-account-20261025` for minimized types-only evidence.
Local/installed-repository checks did not locate authoritative mobile GPS ownership
code; the document-ID-to-child join remains unverified and is not guessed.
