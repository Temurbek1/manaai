# Shared source refresh policy — owner direction, 2026-10-18

## Decision and present authority

The owner clarified the target behavior:

> источники бесконечны могут быть у тебя, а читаться массово они должны дважды в день (в 9 утра и в 3 обеда)

There is no fixed business limit on the number of registered, governed sources.
Bulk collection should start twice daily, at **09:00 and 15:00**. Use
**Asia/Tashkent, UTC+5** as the explicit proposed application timezone, consistent
with the owner's Uzbekistan deployment; a different timezone requires an explicit
configuration/decision, never the host machine's local timezone. The equivalent
cron expression is `0 9,15 * * *`, interpreted in that named timezone, not UTC.

The question explicitly concerned future product behavior, **not** permission to
read data or deploy now. No scheduler, source flag, credential, collection, current
Goal, database or production service is changed by this document. Existing manual
handlers still reject scheduled triggers. The one-new-external-read-per-Goal
implementation remains in force until a separately verified replacement exists.

## Target: one shared collection, many analytical consumers

Collection belongs to the shared data plane, not each chat, Goal or agent. One
bounded, product/source/binding-specific collection produces validated minimized
facts, exact provenance and a publication manifest. All four authorized MANA
agents can retrieve the same SQL evidence without repeating the provider read.
An ordinary conversation, model tool selection, Goal creation, UI reload, source
catalog browse or worker restart is never a bulk-refresh trigger.

The number of connectors is not a reason to add agents or expose arbitrary URLs,
SQL, shell, provider payloads or credentials. Each connector still needs a typed
adapter, confirmed application/population binding, ownership, privacy contract,
bounded collection plan, independent cost gate and explicit activation. Catalogs
and evidence are paged within technical/context/budget bounds; "unlimited sources"
does not mean infinite work in one model call or bypassing admission ceilings.
The existing four-evidence limit is a current implementation bound, not a claim
that an arbitrary-source analysis already works. Extending it requires an explicit
new immutable native profile, actual paging/review/rollback acceptance and no
automatic upgrade of old Goals, continuations, approvals or saved receipts.

Bulk **collection** must not automatically run an LLM analysis for every agent,
topic, user or connector. Analysis/review remains separately budgeted, task-driven
work. Publication success is not a customer contact, permission, completed Goal or
measured business improvement.

## Durable windows and failure boundaries

1. Compute two named daily windows in the configured timezone. A SQL occurrence
   key binds product, source connection, binding revision and scheduled UTC time.
   Claim/consume it before provider I/O, across processes and restarts. Do not
   catch up missed historical windows as a scan or derive a new occurrence from
   retries, query changes, chat count or a different worker ID.
2. Each connector retains its own source-wide single-flight, six-hour minimum,
   timeout, request/document/byte and daily/monthly money ceilings. The 09:00 to
   15:00 interval is six hours; late morning admission can therefore make an exact
   15:00 read ineligible. Any bounded pre-I/O deferral must respect the original
   window/deadline and source gate; otherwise record a skipped window. Never reset
   the gate or issue a provider request just to meet the clock.
3. An admitted connector reads its bounded approved plan once. Pagination is
   allowed only where a separately specified connector contract proves its range,
   finite budget and recovery behavior. It is not a generic Firestore scan grant.
   Late replies reconcile verified costs, not discarded or superseded decisions.
4. A permanent authorization/configuration error closes that source/credential
   gate until deliberate recovery. A lost/unknown read keeps its durable hold and
   blocks redispatch; neither the next time slot nor restart releases it. Do not
   repeat successful expensive sources because another source returned 401/403.
   Never retry a complete batch as an authentication fallback.
5. Validate each source independently and publish exact per-source status:
   completed, unchanged, partial, unavailable, skipped or unknown. Preserve the
   previous good snapshot where appropriate, with its original age/status. One
   missing source is not zero and cannot silently turn a partial publication into
   complete coverage. Agents must load and cite actual saved evidence, not only a
   publication manifest or source-name preview.

## Read less, without fabricating unchanged data

- Prefer server-side aggregates or verified change feeds with stable ordering,
  server update watermarks, late-arrival overlap and explicit deletion/tombstone
  handling. Commit the watermark only with a complete validated SQL publication.
  A partial or unknown request cannot advance it.
- Stable IDs, count equality or local hashes alone do not prove that remote
  records are unchanged. Hashing after downloading all documents saves neither
  those billed reads nor their network transfer.
- Existing `battery`/`children_location` adapters are bounded prefix samples, not
  verified full-population incremental sync. Preserve their sample/coverage labels
  and ceilings. Do not turn the twice-daily decision into full scans. A complete
  evolving child-state mirror needs a separately established change/deletion or
  backend-aggregate contract.
- GA4 parent analytics has its own event/reporting periods and late processing;
  source collection time is not user observation time. Reuse stable qualified
  aggregates where their connector contract permits it, and explicitly bound any
  late-data refresh. Do not assume the same date range is permanently immutable.
- Keep MANA/360REC and parent behavior/child telemetry separate. Confirmed MANA
  data is not a database feed for request-driven 360REC; tariff data still does not
  establish paid orders, and user geography does not establish regional sales.

## Freshness and the pending between-window choice

09:00 → 15:00 is **6 hours**; 15:00 → next-day 09:00 is **18 hours**. Therefore
two daily updates are not the same as "every six hours" and cannot retain an
unqualified always-current claim through the evening/night.

Every publication must retain observation period, collection start/end, save time,
next expected refresh and source limitations separately. A missing 09:00 refresh
does not make yesterday's data fresh again. Existing saved report `fresh_until`
values cannot be rewritten or retroactively extended to force Goal completion.
Any new window-aware validity policy must be captured only on new compatible
reports/tasks and reviewed against the exact original `current` objective.

The owner is being asked how a Goal should behave between these windows: use
saved data and wait for the next window when insufficient, or additionally offer
a separately confirmed targeted read. This remains **unresolved**. Do not infer
an on-demand exception, a new recurring authorization or silently replace a
current-data objective with a historical one. Useful dated partial analysis and
an explicit missing-data status are preferable to invented current conclusions.

## Cost proof required before activation

Prepare an offline connector inventory and an explicit bounded plan before live
activation: attempts, documents/index entries, bytes, query ranges, quota units,
unchanged-data checks, per-source failure holds and global ceilings. Use current
verified provider tariffs only in a separately dated cost estimate; do not infer
cost from connector count or the existing small child sample.

For one completed collection cost `C_i` per enabled connector, the baseline
collection-only bound is `2 × sum(C_i)` per day, `60 × sum(C_i)` per 30-day month,
and `730 × sum(C_i)` per 365-day year. This excludes initial backfill, permitted
targeted reads (not yet decided), storage/network/hosting and separately metered
LLM analysis. Use conservative admission reserves and preserve unknown costs;
these formulas are not an invoice or a promise of zero cost.

Release acceptance must exercise two-worker/restart occurrence deduplication,
clock/timezone/cooldown boundaries, failed authentication without batch replay,
partial/unknown publications, unchanged/delta/deletion handling, same-source reuse
across agents, cost exhaustion, native history/rollback and an authenticated browser
on the exact candidate. Activation needs its own reviewed source/cost/release scope;
no existing independent scheduler, main/audio, parent chat, SSH or key is changed here.
