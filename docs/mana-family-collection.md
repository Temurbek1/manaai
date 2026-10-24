# Shared family collection at 09:00 / 15:00 — local, 2026-10-25

This increment implements the next part of the [autonomous agents objective](mana-autonomous-agents-plan.md):
existing source facts can be acquired without waiting for a new application webhook
or for a parent to open a chat. A single durable collector discovers canonical MANA
parent/connected-child links, uses the existing shared source cache, records changes
and publishes a minimized, dated acquisition manifest. The existing enabled battery
consumer can send those changes through Child-Safety and the sole speaker,
Parent-Touch. Collection alone grants no inference, contact, payment or trial action.

This is local source/runtime/lab work, not a deployment or activation. The default
`MANA_FAMILY_COLLECTION_ENABLED=false` remains. Production, main/audio, operational
workers, source schedules, SSH, keys, customer data and tariffs were not changed.
Family history remains v12 and shared source cache v3; the collector owns a separate
private schema-1 SQLite ledger, not an operational or chat database migration.

## Runtime and schedule

`family_source_runtime` builds a typed `FamilyCollectionService` only under explicit
source/collection configuration. `parent_chat_runtime` owns its independent polling
worker and closes it before the shared HTTP client. Construction performs no HTTP.
A collector failure stops that worker without marking the parent-chat worker down.
The mobile chat still has its three recommended operations; no collector control
or provider credentials are exposed to a phone or model.

The named windows are **09:00 and 15:00, Asia/Tashkent (UTC+05:00)**, separated by
six and eighteen hours. A first activation after 09:00 starts at 15:00. A missed
window records `skipped`; it is never backfilled. The default start grace is five
minutes and the whole window is bounded to thirty minutes. Polls, history reads,
page reloads and restarts do not authorize a provider request.

Each window has a deterministic ID, durable page/source claims committed before
I/O, finite ceilings and an immutable terminal manifest. Population pagination
advances only with the successful page/target SQL transaction. Unsubmitted targets
carry into the next allowed window; completed/unknown exact requests never reissue.
Sources remain the registered battery and, if independently enabled, app-counter
adapters. A fresh ownership-filtered Parent API read precedes every new target,
including cache hits. Inventory membership is discovery, not continuing ownership.
Parents without any chat history are discoverable; a missing verified contact
context/consent still does not become permission to communicate.

A page reserves two conservative inventory HTTP attempts for login plus GET. The
adapter uses fixed `limit`/`offset`, at most 100 parents, at most 20 children per
parent and 256 KiB per page; provider `next` links are never followed. Names, phones
and arbitrary provider prose are not retained in collection records. Source reads
reuse the existing family cache/100-admission rolling-day meter and six-hour
provider cooldown. App counters reserve no Firestore document units, which is not
zero backend/database/network cost. JWT `exp` is only a bounded cache-expiry hint;
the backend still verifies authorization. A failed GET is not retried with a fresh
login. See [RFC 7519, section 4.1.4](https://www.rfc-editor.org/rfc/rfc7519#section-4.1.4).

Unknown inventory results close further inventory reads across restart/windows.
Known source authentication errors close that source lane. Unknown source results
retain their original target hold; one SQL-only observation may reconcile an exact
receipt. Neither a new day nor a different UUID retries that target. Already
queued independent targets can continue within the original budgets. Late results
never rewrite an already published manifest into a historical success.

## What the manifest proves

The private acquisition summary records pages/parents/targets, backlog, start
offset, provider-reported parent count and separate per-source completed/failed/
unknown/cache/available counts. It distinguishes oldest cached snapshot collection,
latest actual provider check, observation dates and manifest publication. A pending
cache entry is not an available verified observation. Refused/failed reads cannot
produce a `completed` acquisition result. Changed pagination and partial coverage
remain explicit; `population_complete` is always false because offset pagination
is not a point-in-time population snapshot.

Low-charge counts describe records, not confirmed current danger or all children.
App-counter pages retain their original unknown period/partial inventory and are
not summed into screen time. MANA parent GA4 behavior is separate from child data
and 360REC. This collector does not yet provide GA4 acquisition, a shared
administrative aggregate bridge, general app-change safety analysis or analysis
coalescing across specialists. Existing on-demand native app-counter chat reads
remain available separately; an app source event is not misparsed as a battery event.

## Actual bounded provider check

A one-shot manual invocation used the actual new inventory adapter with
`limit=1&offset=0`: **one login plus one Parent List GET**, no retries. It returned
one family, seven connected child links on that page and a provider count of
**219,873 parents**. This proves the page contract and discovery wiring, not all
connected-child counts, complete coverage, billing, throughput or consent. No
child, Firestore, model, push or grant request was made. Only minimized counts and
attempt metadata were saved in `output/collection-inventory-live-20261025/`.
Do not automatically replay the diagnostic or extrapolate seven children to the
entire population.

At the default page size 25, that reported parent count requires **8,795 inventory
pages per traversal, 17,590 per two traversals**. The default collector permits
100 pages/window, 400 conservative inventory HTTP attempts/rolling 24h, 50 source
targets/window and the unchanged shared 100 source admissions/rolling 24h. It cannot
cover that fleet twice daily. Backlog/partial reports are truthful limits, not a
substitute acceptance target. No ceiling was raised or population scope silently
narrowed to make a demonstration pass. Production capacity and approved rate limits
still require a separately measured/authorized configuration.

## Offline cost calculation

The pure calculator needs explicit parent/link counts and an explicit project rate;
it reads no `.env`, credentials or provider and cannot activate a scheduler:

```bash
PYTHONPATH=. .venv/bin/python scripts/mana_family_collection_forecast.py \
  --parents 50000 --connected-links 50000 --include-app-usage \
  --firestore-usd-per-100000-reads 0.06
```

**These are illustrative inputs, not this project's verified price or child count.**
At the supplied $0.06 /100,000 read units, two exact battery reads per child/day,
conservatively reserving two document units each, cost the following before any
free allowance:

| Scenario | Firestore units/day | Day | 30 days | 365 days |
|---|---:|---:|---:|---:|
| Illustrative 50,000 child links, full required battery collection | 200,000 | $0.12 | $3.60 | $43.80 |
| Existing maximum 200 reserved units/rolling 24h | 200 | $0.00012 | $0.00360 | $0.04380 |

The second row is an arithmetic ceiling for this lane, **not full fleet service**.
App/API resource charges, OAuth, transfer, storage/index costs outside the fixed
query contract, other apps/readers and inference/contact charges are unpriced here.
No shared free allowance or total-account invoice is assumed. Targeted requests
share these ceilings; failed/unknown reads are not refunded. The calculator exposes
required versus configured capacity and explicitly leaves throughput/full coverage
unverified. Parent-Touch remains 2,000 raw tokens/parent/day and Child-Safety remains
2,000 raw tokens for the entire server/day; this collection does not imply a paid
model analysis for every discovered family.

## Reproducible local scenario

`make chat-lab-collection` starts a loopback-only simulation, isolated from all old
lab directories. Its explicit 09:00 and 15:00 buttons advance a fixed fictional
October-25 clock; real models/sources cannot be selected in this mode. The first
collection produces an assistant-first chat via actual SQL/cache/safety/Parent-Touch
logic. The second observes unchanged source fingerprints without another analysis
or message. Buttons repeated after reload/restart observe the saved result only.
The mode marker prevents using fictional time to reset a real-model quota.

Automated tests use fakes/MockTransport exclusively. This is protocol/engineering
evidence, not real model quality, customer delivery, business benefit or production
readiness. The original failed diagnostics remain negative evidence rather than
being overwritten. Final gate, image and browser results are recorded below after
completion.

## Completed local checks and remaining acceptance

- Focused collection/inventory/token/cost/lab/runtime checks passed. The larger
  recovery/runtime selection passed **43 cases**; counts overlap the full gate.
  Tests cover both windows, missed slots, two-connection claims, carried backlog,
  fresh/revoked ownership, shared request capacity, unknown inventory/source holds,
  lost committed page/source acknowledgements, immutable manifests and restart.
- Final `make verify` **20809** exited **0**: **1,211 backend tests passed**, one
  skipped, two opt-in live tests excluded; **26 admin tests /11 suites**, **seven
  lab controller tests**, formatting/lint, mypy **348 files**, TypeScript, production
  UI build and npm audit (**zero vulnerabilities**) passed. Subsequent helper-only
  additions passed a separate full Ruff/format/mypy scan; they are not new product
  changes or live tests.
- The first full gate **77389** exited 2: 1,210 passed and one existing lab
  conversion assertion failed. Its composite state read captured empty history
  before the worker committed, then read a newer `published` proposal. The lab
  now reads publication state before its referenced history. The failure log is
  retained as `output/collection-verify-final.log`; only the subsequent complete
  `output/collection-verify-postfix.log` is a passing full gate. No tariff or push
  was sent, and no source/model diagnostic was retried to fix this race.
- The new `scripts/mana_family_collection_smoke.py` passed on the host and packaged
  image, networkless/read-only with private tmpfs. Two complete fictional windows
  survive reconstruction; exact button replays perform zero reads and preserve
  every table fingerprint. Final image `mana-ai-family:collection-v1-20261025-final`
  is `sha256:4f0f92c52c604a00be2936218693069a519e522fc8da9561da9beba2005038d7`.
- The image independently reconstructed the previous fictional family v12/source
  v3 fixture with **150 known model tokens plus 1,850 unknown held tokens**, an
  unknown source claim, and the added schema-1 unknown inventory claim. No clients
  were constructed; all table fingerprints and next-day model holds remained.
  Actual previous image `c2bc5654cb9d` still reads that family/source fixture with
  execution closed and collector untouched. This is narrow reader compatibility,
  not an exercised production fallback or permission to downgrade populated SQL.
  An initial fixture mount used the image's different user and was denied by the
  private filesystem; the owned-UID networkless rerun passed without loosening
  fixture permissions. Both original logs remain.
- Owned Chromium on loopback 8097 passed the first-contact scenario: one assistant
  message, zero parent messages, 150 simulated safety tokens. The 15:00 window
  completed with no duplicate message/analysis. A manually submitted Uzbek app
  question used the same cache and returned a qualified Uzbek answer. Total SQL
  source admissions were five: four fictional provider reads across two sources/
  two windows plus one app cache hit, four conservative Firestore units. Final
  budgets were 450 simulated safety /300 speaker tokens. After an owned server
  restart, history, both window IDs and costs remained; repeating the morning
  button did not change those source counts. Desktop and 390px screenshots were
  inspected, with no page overflow. Browser/server are closed. Artifacts:
  `output/collection-browser-*`; these contain fictional data only.

This increment makes autonomous acquisition and battery first contact materially
more complete; it does not finish the whole objective. General source-change
analysis/coalescing, remaining telemetry and GA4/administrative bridging, assistant
reminders, the remaining owning specialists/actions and broader real model/source/
consent/channel acceptance remain. Fleet capacity and actual project billing need
measurement, not extrapolation from the one-parent page. No newly paid inference
or real customer action occurred. A clean separately approved release and its
production rollback/verification remain required before activation.
