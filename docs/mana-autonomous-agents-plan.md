# MANA autonomous single-chat agents — active objective, 2026-10-24

## Authority and full scope

The owner assigned the objective from
`/home/samanwirst/.codex/attachments/9823ea08-1a39-4b22-8b13-54a36a885e77/goal-objective.md`,
including the appended autonomous-data and chat-reading requirements. The product
scenario source is `/mnt/ssd2/Downloads/AI KOMANDA.pdf` (all 21 pages reviewed).
This is a new active implementation objective, not completion of the earlier
externally blocked conversion objective or blanket production-release approval.

New backend webhooks are **not** a prerequisite where existing sources contain
the needed facts. Agents may select typed, already authorized reads themselves
or receive an Orchestrator task, within the family/source/cost scope. No manual
confirmation is needed for each such admitted read. The owner permits agents to
read user chats. This never lets quoted chat text confer tool authority, expose
another family to a parent, manufacture consent or enlarge cloud IAM permissions.

Keep the existing Parent-Touch/Child-Safety/commercial implementation and lab,
currently based on `b81eec7`, in `/mnt/ssd2/mana-conversion-agent-20261021`.
Do not sweep the dirty `/mnt/ssd2/Projects/manaai` operational/old-chat work into
this increment. The existing production family release and all shared services,
keys, SSH settings and source schedules remain outside local changes.

## Requirement and acceptance inventory

| Requirement | Current evidence / remaining work |
| --- | --- |
| One canonical parent, one durable chat, Parent-Touch is the sole speaker | Existing family service/SQL and `mana-chat` three-operation contract; reverify with new specialists and sources, not just the earlier fake lab |
| Exact sequential question/answer binding; filtering/coalescing; urgent safety priority | Existing broker and reviewed-message workflow; add multi-specialist and autonomous-source E2E acceptance |
| Agent starts before first parent text; durable message before independent push | Existing local proactive lifecycle; real source-derived language/contact preferences and channel acceptance still required |
| Independent data access, no mandatory backend producer | New typed battery source/cache is an initial implementation, not runtime tools or complete source coverage; wire actual tools, credentials and observations |
| One shared collection, consumers reuse snapshots; changes create internal events | New dedicated SQLite snapshot/change journal is local; consumer claims, analysis dispatch and cross-context aggregate publication remain to implement |
| New child data/new parent text triggers Child-Safety without unchanged-context inference | Existing manual/new-message workflow; connect admitted source changes, preserve dedup/unknown holds and dated evidence |
| Behavioral changes, screen time, routes, reports and clarifications | Existing ten analysis contracts, not complete automatic feeds; map actual available sources and implement missing date/ownership-safe ingestion and reports |
| Timely paid conversion | Local commercial lifecycle/account/catalog adapters exist; replace missing-webhook dependency with source-derived observations without inventing free-start/consent/offer terms |
| Churn detection, retention, win-back | Implement authoritative account/activity observations, eligibility, communication and supported actions |
| Real eligible upsell; referral and loyalty using confirmed mechanisms only | Implement supported catalog/benefit contracts and owning policies; no invented discounts, rewards or billing API |
| Parent assistance and supported reminders | Existing chat; add durable reminders with dates/timezone, cancellation and one-shot delivery, no invented calls/orders |
| Four OPERATION owners, not more top-level administrative agents | Preserve canonical model: Growth (ads/SMM/conversion/upsell), Retention (loyalty/referral/win-back), Orchestrator (admin analysis/delegation), Technical last; full handlers/actions still need implementation/acceptance |
| MANA/360REC and parent/child populations remain separate | Every new binding/snapshot/tool must carry enforceable scope; GA4 aggregates are not a per-parent identity join or child telemetry |
| Shared bulk windows 09:00 and 15:00, plus bounded targeted reads | Implement durable occurrences in explicit Asia/Tashkent timezone; no hourly full scan, catch-up loop or Goal/UI-triggered bulk refresh |
| Clear costs and hard limits | Preserve 2000 raw chat tokens per parent/day and separate 2000 global safety tokens/day; explicit source/other budgets, no silent expansion or unknown refund; cost forecast before activation |
| Typed safe actions and verified outcomes | Preserve policy/fresh state/idempotency/audit/recovery; no payment/transaction creation; free-tariff tests only on designated test accounts; no repeat of parent 4's consumed grant |
| Real quality and end-to-end tests | Unit/HTTP/browser/lost-ack/restart/limit tests plus bounded real models/sources; simulations cannot establish real-family/model/business acceptance |
| Updated English integration instructions and practical web lab | Extend lab as capabilities become real; update integration guide for independent collection/controls and evidence limits |
| Compatible migrations, rollout and rollback with retained private history | Candidate-image and closed-reader checks for actual changes; never downgrade populated schema or restore old DB over new history; separately scoped production approval |

Completion requires the **whole** assigned event -> analysis -> decision ->
Parent-Touch -> message -> parent reply -> further action path with the required
real integrations. Passing one adapter, simulator, fake test suite or local
checkpoint cannot close the goal. Unsupported/missing facts remain explicit, not
zero, a fabricated offer, a smaller replacement objective or an excuse to stop
other implementable work.

## Initial source lane

`app/mana_ai/domain/family_sources.py` defines own-child battery facts, targets,
receipts, limits and change references. Application logic in
`application/family_sources.py` commits SQL admission before ownership/provider
I/O and returns exact old SQL receipts without any source replay. New cache
consumers still require fresh connected-child ownership. Family names, phone
numbers, credentials, raw document paths and arbitrary provider queries are not
part of saved source facts.

`app/services/family_source_store.py` uses a separate private schema-1 database,
not the chat or operational database. Policy/binding identity is immutable for
that ledger. Source claims, snapshots, heads and change events share short SQL
transactions; no network call holds a transaction. Pending/unknown child reads
survive restart and day changes, including across parent reassignment. A known
source authorization/query failure durably closes the source, not another source
or a complete batch. Late results cannot publish after a terminal failure.

Current explicit constructor ceilings are **100 new requests per rolling 24h**,
**200 conservatively admitted document units**, and a **six-hour per-child
provider cooldown/cache window**. Each new provider query reserves two units;
cached reads reserve zero but still count toward request admission and recheck
ownership. Failed/unknown admissions are not refunded. These are not actual
Google billing receipts, a dollar ceiling or proof of production throughput.
Changing the connection/binding/limits cannot silently reset an existing ledger.

`app/services/firestore_child_battery.py` implements one equality-filtered
`battery.childId` query, fixed three-field projection, limit two, 64 KiB response
and 30-second default wall bound. It takes an injected server token port; no token
is shown to the model or browser. It does not list collections, follow cursors,
subscribe, retry, redirect, mutate documents or use an arbitrary URL. Foreign
rows and inconsistent server metadata fail; multiple matching documents are
explicitly ambiguous, not an arbitrary latest observation. Naive/future device
dates stay unknown: server update/collection time never becomes sensor time.

The stored October 12 schema audit establishes the `childId`/`percent`/`created_at`
fields; it is not a fresh live test of this new exact-child query. Primary API
references checked October 24:
[runQuery](https://firebase.google.com/docs/firestore/reference/rest/v1/projects.databases.documents/runQuery),
[StructuredQuery](https://firebase.google.com/docs/firestore/reference/rest/v1/StructuredQuery),
[billing definitions](https://firebase.google.com/docs/firestore/pricing).
Exact project pricing/index configuration and the remaining bounded OAuth/
ownership attempts must be included before publishing a monetary estimate or
activating a real collector. Fewer requests alone do not establish lower billing.

## Next implementation sequence

1. Wire server credentials and the source registry to actual runtime tools;
   retain original-invocation pairing, fresh ownership and raw usage accounting.
2. Connect immutable change receipts to existing specialist admission and
   Parent-Touch delivery, with durable consumer claims and no model/source replay.
   Do not invent online status from a battery write or use undated data as current.
3. Extend actual source coverage and shared window collection; independently
   implement reminders and commercial capabilities while documenting unsupported
   provider functions. Do not wait for webhooks for available source facts.
4. Extend the lab and limited real acceptance, complete administrative owning
   capabilities in the required order, then prepare the separately scoped release.

No source lane is mounted in the current runtime yet. This checkpoint starts no
listener, refresh, model, push, grant, source write or production process.

## Initial implementation acceptance — 2026-10-24

Full `make verify` session **67753** finished with terminal exit **0**:
**1042 backend tests passed**, one skipped, two opt-in live tests excluded;
**26 admin tests** and **five lab controller tests** passed. Ruff formatting/lint,
ESLint (including its 34 compatibility checks), strict mypy **294 files**,
TypeScript, Next production build and dependency audit (**zero vulnerabilities**)
passed. Secret scan passed **487 tracked/unignored files**; diff check passed.

The new source suite has **28 fake-only cases**. Focused session **76779** passed
**33** including five architecture checks; these overlap the full suite, not an
additional independent quality party. They exercise exact replay and changed-only
events, two-connection single-flight, cancellation/unknown holds across restart/
midnight, revoked ownership even for cache hits, global rolling ceilings, durable
source circuit, request conflicts, unrelated DB/symlink/policy refusal, corrupted
cache, family-scoped snapshot paging and late-result fences. Actual HTTP adapter
tests use `httpx.MockTransport`, not Google: exact child filter, fields, limit,
missing/ambiguous rows, invalid/foreign data, timestamps, byte ceiling, statuses
and no redirect/auth/query retry.

Initial static diagnostics found formatting errors and one Decimal/int local
variable reuse; those were corrected before the final passing gate. A later
patch failed context verification and changed no files; it was reapplied against
the actual formatted source. No failing source test or lost paid attempt was
reclassified or replayed. No earlier negative model party/history was altered.

This proves local code/contract behavior, **not** a real exact-child query,
model-selected source tool, live credential wiring, consumer delivery, scheduled
collection, whole-population coverage, real model quality, candidate-image
rollback or production readiness. No dependency/configuration/endpoint/schema
change was made to the released application. The only new schema is the separate
opt-in source cache, not a migration of family or operational history.
