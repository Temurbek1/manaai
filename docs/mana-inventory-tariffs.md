# Shared inventory tariffs — local, 2026-10-25

The existing 09:00/15:00 MANA Parent List collection can now feed its selected
paid/end-time facts into the same Retention expiry cache used by targeted profile
reads. A discovered parent needs neither a prior message nor a queued child-source
target. Parent-Touch remains the sole speaker. No extra provider request, model
generation, quota, mobile endpoint, payment, trial grant or consent is introduced.

`MANA_COLLECTION_TARIFFS_ENABLED=false` remains the default. Enabling requires the
existing collector and full v17 expiry receiver. Production was not changed or
activated. This is another consumer of an already admitted bounded page, not a new
scan, retry, schedule, full-population claim or prerequisite backend webhook.

## Durable flow

1. A newly admitted page freezes its tariff-consumer bit before provider I/O.
   Historical and disabled claims never acquire that bit on migration/re-enable.
2. The existing single GET returns parent/child discovery and optional tariff
   metadata. Missing/malformed billing becomes unknown; it does not discard valid
   child links. Only parent ID, actual collection date, strict nullable paid flag
   and aware nullable end time enter the tariff projection. No name, phone,
   location, free-start assumption, payment history or consent is retained.
3. Known on-time page completion and its minimized batch commit together. Claims
   past their own lease, unknown reads and late/closed-window results cannot create
   a batch. Successful billing projection is independent of child-target queue
   capacity; a partial acquisition manifest is still a qualified partial manifest.
4. A separate SQL claim binds page/window/hash/facts before one local cache call.
   The receiver validates exact parents/dates and updates the whole bounded batch
   transactionally. A capacity refusal rolls back its facts and closes expiry;
   it neither deletes history nor enlarges a ceiling.
5. Retention's existing policy independently decides whether to publish one dated
   assistant message. Separate verified language/timezone/consent, quiet hours,
   opt-out, safety priority, 20 shared outreach/day and parent cooldown still apply.
   The later reply uses the existing reviewed chat and unchanged token limits.

Batch defaults: at most 10,000 retained page receipts, 100 facts per page, 180-second
source age, 30-second local claim. Capacity/integrity closes this consumer; source
authentication failure also durably closes expiry. Unacknowledged/lost local calls
remain unknown and are never redispatched, including across restart/new windows.
A committed local completion can be observed after its acknowledgement is lost.
An unknown local cache acknowledgement is distinct from an unknown HTTP source:
the source page is already known; any committed cache fact retains that provenance.

Deactivation preserves the v2 collector reader and core collection while omitting
tariff projection/dispatch. Re-enable resets no circuit, claim, age, history or
deduplication. Existing pending batches keep their original dates and can expire.
The original family/source/collector ceilings remain; this does not cover the
whole MANA fleet twice daily or add a model analysis for every discovered parent.

## Practical checks

`make chat-lab-inventory-tariffs` opens the local fictional chat. Use the 09:00
collection button: one assistant message appears with zero model tokens and no
child-source read. The 15:00 button refreshes equal facts without another message.
Ask `Mening tarifim qachongacha amal qiladi?`; the same chat uses the same date.
Both clocks and providers are fictional; this mode cannot select paid models or
real sources. Reload/restart never renews its fixture deadline or repeats a window.

The fake/MockTransport suite covers original claim capture, two-connection claims,
lost page/cache/completion acknowledgements, unknown/late/stale results, exact
page pairing, old/disabled claims, receiver capacity, auth closure, optional bad
billing, independent child-target capacity and reconstruction. A previously shared
default test path was fixed to isolated per-test storage; the negative diagnostic
is retained. The deliberately repeated lost-ack harness now expects the worker to
stop on persistently lost observation rather than claiming recovery succeeded.

One new **actual source-only** diagnostic used precisely login +unfiltered Parent
List GET `limit=1&offset=0`, both 200, no retries. Its one-row tariff projection had
known paid/end-time fields with exact parent/date pairing. Provider-reported count
was **220,460 parents**, not connected children, eligible recipients or verified
coverage. It wrote no family cache/contact settings/chat, called no model,
Firestore/GA4, push, grant or payment. Original artifacts are in
`output/inventory-tariff-live-20261025`; do not replay this party to amend evidence.

Additional tariff fan-out adds **zero HTTP/Firestore/model calls** to the original
collection. This is not a zero-cost claim for its existing API queries, database,
storage, other readers or later parent conversations. No new pricing or allowance
was assumed. The existing token and source budgets remain unchanged.

Final `make verify` **4460** exited **0**: **1325 backend cases**, one skip/two live
opt-ins excluded; **26 admin cases /11 suites**, **10 lab-controller cases**, mypy
**387 files**, formatting/lint/types/build/npm zero. These are fake engineering
checks; no new paid model party was run. The prior real-model v17 reply evidence
remains separately qualified in [expiry evidence](mana-retention-expiry.md).

Owned 390px Chromium verified the assistant-first 09:00 reminder, unchanged 15:00
facts and an Uzbek parent reply in the same three-message chat. Model counters
were 0/0 before the reply, then 150/150 simulated tokens. One semantic tariff
change and two applied page batches survived actual server restart with every
family/source/collector table fingerprint unchanged. Screenshots were inspected;
no page overflow. The first SQL-only screenshot audit used a nonexistent table
name and was corrected without repeating a source or model request.

Collection schema **2** adds only private policy/capture/batch tables; family stays
**17**, source **4**. Candidate `mana-ai-family:inventory-tariffs-v2-20261025-local`
is `sha256:f3228a4d7ef6d3ea81f4adee79bde53dcd6138875fb9ad09a53e550dae438952`;
critical application/cache/runtime/provider source hashes match the final host.
Networkless candidate checks preserve all original v1 tables,
unknown inventory, no historical fan-out, new unknown batch holds, existing family
history and 150 known/1850 unknown safety tokens. Actual previous `8791d2946969`
refuses collector v2 unchanged; this is not a working collector-execution rollback.
Its actual v17 closed family reader separately retained the post-fan-out three-message
history and every family-table fingerprint without opening the collector.
Use the compatible deactivated reader, never downgrade or restore an older database
over new receipts. A separately scoped release/rollback and full fleet/quality/
consent/channel acceptance remain required. The complete agents goal stays active.

API/TypeScript synchronization, marker scan and secret scan (1287 tracked/unignored
files at that stage) passed. Owned browser and port 8097 are closed. Original
negative harness/path diagnostics and both initial/final gate receipts remain;
no original paid party or real source check was repeated to repair them.
