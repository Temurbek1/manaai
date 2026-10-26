# Owned-child GPS source — local checkpoint, 2026-10-26

Child-Safety can now select one exact child's last-point metadata through the
existing native source tool. The shared collector can acquire the same source in
its existing **09:00 and 15:00 Asia/Tashkent** occurrences. Changes enter the
existing coalesced specialist queue; Parent-Touch alone publishes to the existing
chat, including a permitted first contact before the parent writes.

This is local, default disabled by **`MANA_FAMILY_LOCATION_ENABLED=false`**. It
requires the current governed native family/manager profile, not Conversion or
trial activation. It does not enable the collector, contacts, paid models or any
production setting by itself. Source and collection budgets have not increased.

## Exact source and privacy

The owner-supplied mobile source establishes
`bosstracker-dev/(default)/children_location/{numeric_child_id}`; read
[the original binding and stale-point evidence](mana-mobile-location-binding.md).
The adapter uses one fixed-mask document GET as defined by the
[official Firestore document API](https://firebase.google.com/docs/firestore/reference/rest/v1/projects.databases.documents/get).
Fresh MANA profile ownership and a connected child relationship are mandatory
before I/O, including a new cache hit. Exact replay observes SQL without a new
profile lookup, token exchange or source request. Models choose only an admitted
child alias and `kind=location, calendar_day=null`, never IDs, paths or credentials.

The parser verifies the exact returned document name, finite coordinate ranges,
aware server update, measurement date and strict optional mock/sample/movement
flags. It rejects duplicate JSON fields, malformed/foreign results, compression
and responses over 64 KiB. A 404 is an absent record; access/query failures close
only this source, while unknown attempts keep their durable hold and never retry.

Coordinates are discarded inside the adapter. Private SQL retains only a point
fingerprint, dates and minimized quality flags; model projections also omit the
point fingerprint. There is no address, reverse geocoding, route history, verified
accuracy/distance, geofence event or current-presence claim. Reported mock/sample
flags are source metadata, not an attestation of sensor authenticity. Collection
or a server write cannot turn an old measurement into the child's current location.

## Capture, cache, collection and compatibility

- **Family v23** captures GPS eligibility only on new native parent-message turns.
  Old/disabled turns never gain the tool. New compact prompt v2 is separately bound
  in the captured native policy and optional private scope field. Earlier unversioned
  GPS captures retain their exact original prompt/minimum-output contract; no
  historical input, objective, receipt or quota is rewritten. Stop fences account
  verified usage before refusing a late decision. Insufficient final-response room
  refuses inference rather than publishing truncated JSON or increasing a budget.
- **Source cache v7** shares the existing request/document meter, six-hour provider
  cooldown, ownership checks, change journal and coalesced review ownership. GPS
  has its own cache/circuit. Recollection of an identical fingerprint creates no
  new source event. Fingerprints include measurement/quality and source-version
  dates; this is version deduplication, not proven semantic movement detection.
- **Collection v4** captures GPS only on new existing occurrences. Old windows
  retain their original manifest; enabling does not recapture them. A disabled
  GPS provider produces a qualified skipped/partial result without aborting other
  sources. There is no new timer, hourly scan, listener, pagination or catch-up loop.
- Current closed v23 and deactivated source v7 retain history, holds and ledgers.
  Actual old family22/source6/collection3 images refuse the new files with rows and
  versions unchanged. Refusal is **not working execution rollback**. Never downgrade
  a populated ledger or restore stale databases over new history.

## Practical evidence

The final `make verify` exited **0**: **1501 backend tests**, **26 admin tests / 11
suites**, **11 chat-lab tests**, mypy **424 files**, formatting/lint/typecheck,
production UI build and npm audit (zero vulnerabilities). One skip and two excluded
opt-in live cases are not passes. Sequential schema synchronization also passed;
the application retains its existing routes and three recommended chat operations.
Logs: `output/location-verify-final-confirmed-20261026.log` and
`output/location-schema-audit-final-20261026.log`.

The current networkless image is
`mana-ai-family:location-v23-verified-20261026-local`, ID
`sha256:ed5f794f2664aac4fca767b689d298cefa1436a0812803f3019089c6df67292e`.
All **23** changed/new application files match host hashes; no `.env` is included.
Actual previous-image fixtures migrate **family22 -> 23, source6 -> 7,
collection3 -> 4**, retaining every original cell, the **1850-token parent hold**,
**two-unit unknown source reserve**, old queued scope and old inventory claim.
No historical GPS admission/window is created. Current closed readers also
preserve the original failed GPS model party. Read
`output/location-image-upgrade-20261026.log` and the previous-reader refusal log.

The protected, already existing production-v6 copy also upgrades **directly to
v23** through this exact image's production HTTP/runtime factory, locally with
networking disabled and synthetic keys. All original cells in **16 tables**, the
two original messages and exact old replay survive. Liveness/history/directory/
replay return 200, missing auth 401, with **zero external requests or historical
captures**. The current closed reader retains all fingerprints. No new server
access/copy was required; private SQL remains outside Git/images with restricted
permissions. This is a small real-history migration check, not fleet/load or
production release acceptance. Receipt:
`output/location-production-copy-verified-http-20261026.log`.

`make chat-lab-location` runs the declared fictional GPS family with a running
clock and a separate 30-day tariff fixture, avoiding an unrelated initial expiry
notice. During the named Chromium check, a new source observation produced the
first assistant-only message; the parent's reply then used the cache. Three
messages, two safety jobs, one snapshot/event and one cache hit were recorded,
with **450 simulated parent / 450 simulated safety tokens**. Reload/server restart
preserved every family/source cell; no new inference/read/contact/grant occurred.
The 390px screenshot was visually inspected, without horizontal overflow or
console errors. Known busy SQL observation waits for the next read-only tick,
never repeating a POST. Evidence: `output/location-browser-postfix-20261026`.
Retain the earlier frozen-clock/unrelated-expiry browser failure and its SQL.

One new live adapter party, after the prior six-hour interval, verified test-parent
4 ownership and made **one projected Firestore GET**: **four HTTP attempts** total,
completed typed receipt, no precise coordinates retained. The record still has
measurement date **2026-10-14**, not current presence. Exact replay and restart
issued no HTTP. No real model, contact, grant or production mutation occurred.
Receipt: `output/location-adapter-live-20261026/result.json`.

## Model quality and cost limits

The original Russian synthetic real-model party read its fake GPS source but ran
out of the **2000-token** safety allowance before a valid final answer. Preserve
its failed state, receipts and append-only cost audit: **401 parent / 2000 safety
tokens**, corrected uncached generation estimate **$0.0029625**. The initial
estimate omitted the private manager receipt; it is not the complete cost.

A distinct Uzbek objective using the newly captured compact prompt v2 completed:
**1473 parent / 1983 safety tokens**, zero holds, two chat messages, one fake GPS
read and eight OpenAI HTTP attempts. It preserved October 14 and explicitly stated
that current location/address/movement cannot be established. The Russian fixture
child name remained unchanged in the Uzbek answer. Generation-only uncached
estimate is **$0.0078535**, not an invoice. Read
`output/location-model-compact-uz-20261026`. No real child data, Firebase, contact,
grant or production mutation belongs to either model party. Prompt changes follow
[official OpenAI guidance on explicit roles, instructions and evaluations](https://developers.openai.com/api/docs/guides/prompt-engineering);
models, raw accounting and permissions were not changed.

This one pass nearly exhausts the global daily safety pool. It is **not fleet
capacity, optimal-cost or broad language/model-quality acceptance**. Preserve
**2000 raw Parent-Touch tokens/parent/day** and **2000 total safety tokens/day**;
unknown holds remain reserved. GPS shares the existing default **100 logical
requests / 200 conservative document units per rolling day**, with two reserved
units per uncached GPS admission. Two complete windows would add at most **2C
document GETs/day** for C children before cache reuse, manual reads and existing
shared ceilings; no full-population coverage beyond those ceilings is promised.
Actual cloud billing/region/credits are not established by these counters.

The complete objective remains active: route/geofence/history semantics, wider
source and model acceptance, whole-fleet capacity, commercial/referral actions,
the full four OPERATION owners and a separately approved production rollout remain
unfinished. This last-point source is not full location intelligence or completion
of all agents. Production remains the separately released family `f8d095e`.
