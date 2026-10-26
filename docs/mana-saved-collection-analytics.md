# Shared collection -> administrative report — local, not released

The existing twice-daily family collector already saves a minimized terminal
publication. The new manual-only **`retention.family_collection.analyze`**
capability consumes that publication inside the existing Retention & Loyalty
owner, producing an ordinary saved operational report and evidence snapshot.
It creates no additional agent, chat, child assessment or external acquisition.

Previously this collector's publication was available to the family/lab runtime,
but the administrative capability registry had no consumer. This change reuses
its existing work rather than fetching the same Firestore/app data for a report.
The independent engagement capability and its sources are unchanged.

## Configuration and use

The capability is absent by default. An explicitly configured local/admin runtime
may enable it with:

```dotenv
OPERATION_FAMILY_COLLECTION_ENABLED=true
OPERATION_FAMILY_COLLECTION_DATABASE_PATH=/private/mana-family-collection.sqlite3
OPERATION_FAMILY_COLLECTION_BINDING=mana:YOUR_PROJECT_ID:(default):manakids-v1
```

The path must be absolute, with no symlink in its ancestry, and must identify the
dedicated collection database, never the parent-chat or operational database.
The binding must exactly match the collector's existing MANA policy. Do not
change that policy to make another product's file pass. A deployment would need
an explicitly scoped read-only mount; this checkpoint changes no production
container, permission, source, schedule, key or SSH configuration.

An authenticated operational **operator/admin** uses the existing API:

```http
POST /api/v1/admin/operation/agents/retention-agent/run
Content-Type: application/json

{
  "capability_key": "retention.family_collection.analyze",
  "job_type": "analysis",
  "idempotency_key": "my-saved-collection-report-1"
}
```

Use the existing operational authentication; the isolated family backend token
is not a substitute. HTTP 202 is acceptance, not completion. Observe the existing
run history and `/api/v1/admin/operation/reports`, optionally filtering by this
capability. The report is available through the normal report detail endpoint.
The same request key joins the same run after reconstruction; report viewing
does not reread even this local collection file.

The capability configuration is only `maximum_age_seconds` (default 86400,
range 60–604800). It admits a recent **saved publication**, never claims recent
sensor measurements. A stale/missing/invalid latest publication fails closed;
it cannot refresh a provider, select an older valid fallback or invent zeros.
There are no default schedules, and scheduled execution is refused. Enabling
the capability/startup/health/report views never opens the source file.

## Projection and dates

The read-only SQLite adapter accepts the dedicated application ID and collection
versions 1–4, checks the exact policy binding, then reads only the latest bounded
terminal publication. Its identity/status/dates must agree with the owning SQL
row. Typed validation refuses invalid counters, future/inconsistent dates,
unsupported sources and fabricated population completeness. Free-form source
reason/limitation text is discarded, including on validation errors: displayed
errors/loggable tracebacks contain one controlled error, not private inputs/paths.

The report includes parent inventory records seen, the reported inventory total,
page/target counts and per-source completed/cache-hit/unknown/failed/skipped/
unavailable/undated counts. It retains source observation, provider-check,
collection and publication dates separately. Its inspection time is not a new
observation or source refresh. The immutable source checksum excludes that local
inspection time. Snapshot/evidence collection time is the original publication,
and population completeness remains **unproven**, represented conservatively as
zero completeness plus explicit qualifications.

No parent/child/device IDs, GPS coordinates, phone numbers, chat messages, raw
provider responses or free-form source prose enter the report. Its window UUID
is collection provenance, not a family identifier or an execution/read grant.
Low battery records are telemetry quality/coverage, not proof of danger. Source
targets are not unique users or parent activity. Do not derive DAU, retention,
churn, paid conversion, routes or full-population child statistics from them.

## Acceptance and limits

All automated tests use the real collection/cache/operational SQL and HTTP flows
with fictional providers. No real provider/model/contact/grant is called.
Final `make verify` exited **0**: **1613 backend cases**, one skipped/two opt-in
live excluded, **26 admin cases/11 suites**, **15 chat-lab cases**, mypy **447
files**, lint/format/types/build and npm audit zero vulnerabilities. Fifteen new
cases exercise actual collection -> operation HTTP -> saved report, viewer denial,
reconstruction/exact replay without rereading the collection, unchanged source
cells, private-prose omission/error suppression, stale/foreign/missing/symlink/
future-version refusal, invalid counters/dates and invalid-latest no-fallback.
The tested source fixture uses actual collection v1; acceptance of every v2–v4
new-source combination is not established by those cases. An initial focused party
passed thirteen cases, the overlapping suite passed 23, and the first mypy check
found test kwargs typing errors, corrected before the full gate. Preserve those
earlier logs; they are not the final gate. Evidence:
`output/saved-collection-verify-20261026.log` and related focused/type logs.

Application **`a3c1a12`** is packaged from the external clean archive
`/mnt/ssd2/mana-saved-collection-source-a3c1a12` as
`mana-ai-operation:saved-collection-local-20261026`, ID
`sha256:77131d80f10a8269d55ab220deda6689e2d4cf2b7d1b23e32fd69c75e93921fd`.
All **280 application Python files** match that archive; no `.env` or private SQL
is included. The actual Python 3.12 production-configured API passes a networkless,
nonroot, read-only-root probe using synthetic keys and only a read-only fictional
collection-file mount. Anonymous report GET is 401, viewer run POST 403, operator
run POST 202 and viewer report GET 200. One report survives actual runtime
reconstruction/exact replay, with only **one source SQL read**, **zero external
requests**, no default schedule and all original cells in the **six collection
tables unchanged**. The operational schema is initialized only in an empty private
tmpfs fixture; no existing family/operational schema is migrated by this feature.
Evidence: `output/saved-collection-candidate-20261026/`, including source/image
hashes, probe, minimized report and log. The initial host fixture import lacked
its required synthetic inference key and refused before creating any fixture or
making a request; the subsequent explicitly configured local fixture succeeded.
That harness correction is not a model/source retry or production acceptance.
No browser/UI, v2–v4 source-combination, existing production operational-history
upgrade, release rollback or real-source/model acceptance is claimed here.

The unchanged quotas remain **2000 raw Parent-Touch tokens per parent/day** and
**2000 global Child-Safety/day**; this deterministic report consumes neither
budget and creates no contact authority. Sequential final OpenAPI/TypeScript
synchronization passed without a public schema/route change.

This is a first shared administrative consumer, not complete Admin Analysis,
Orchestrator, GA4 integration, a source refresh, native Goal-tool registration,
real-family source acceptance or completion of the original AI KOMANDA goal.
Current source coverage, commercial eligibility/offers, Referral/reward contracts,
owning actions, model/channel capacity and scoped production release remain open.
