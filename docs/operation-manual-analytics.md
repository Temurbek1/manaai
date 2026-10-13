# Manual MANA analytics for agents

Local checkpoint, 2026-10-13. Not deployed or activated. Two read-only capabilities
extend the existing Retention owner; they do not create new agents, schedules,
customer actions, full Orchestrator handlers or Technical handlers.

## Administrative flow

A MANA Goal discovers saved evidence first. When an enabled source is needed, the
native tool proposes one bounded read for separate approval. Retention executes it
through the existing policy/run/cost lifecycle. The completed receipt includes the
saved report ID, which the model must load before citing facts. Validated minimized
reports can inform all four MANA rooms without another source call. Technical
remains discussion-only. MANA evidence is never admitted to 360REC topics/Goals.

Opening a page, starting/reconnecting a progress stream, source discovery, health,
registry polling and process startup do not collect data. Both handlers have no
default schedules and reject scheduled triggers. The owner prohibited automatic
refresh after the incident; do not enable a listener, scan or background refresh.

## Source contracts

| Capability | External collection | Population |
| --- | --- | --- |
| `retention.parent_activity.analyze` | Five sequential GA4 HTTP attempts: four report batches and one funnel request; no paging/retries | Approved MANA parent-app analytics identities, not backend accounts or children |
| `retention.child_telemetry.analyze` | Two Firestore `listDocuments` requests, fixed field masks and ID order, ≤100 documents each; no continuation/retries | Owner-confirmed MANA `battery` and `children_location` prefix samples, not population statistics |

GA4 uses the last completed property-timezone day and returns:

- 1/7/30-day active users, sessions, engaged sessions and engagement seconds;
- allowlisted events with explicit inventory coverage/sampling/threshold status;
- two mature first-session cohorts, requiring all exact-day D0–D30 observations
  and a stable denominator before calculating D1/D7/D30 return rates;
- closed `notification_receive → notification_open → button_click` engagement,
  with at most 24 hours between steps, not payment conversion or causal lift;
- six 30-day reports: screens; parent devices/OS/app/language; approximate
  geography; first-user acquisition; weekday/hour; notification-opening minutes.

Each dimension report retains at most ten groups with at most 80 characters per
label. Longer labels are withheld with explicit partial coverage, never silently
shortened; this keeps the complete generated report inside the saved-text reader's
32000-character limit. Users overlap between groups;
distinct-user counts must not be summed. Truncation, missing labels, high-cardinality
data loss, sampling and thresholds remain explicit. Email/URL/long-identifier/GPS-
looking labels are withheld; this filter is not a general DLP guarantee. Custom
user dimensions, raw timelines, payment identifiers and identity joins are excluded.
Acquisition is app attribution, not collection from external advertising services.

Child reports contain valid/invalid field counts, low stored battery observations,
server update ages, unknown/future client timestamps, accuracy and mock counts.
Precise-location quality requires recent known-time, non-mock observations. Raw
coordinates, document names, unused fields and page tokens are discarded. Server
write freshness is not proof of sensor measurement time or current device state.

## Configuration and admission

`OPERATION_PARENT_ANALYTICS_ENABLED` and `OPERATION_CHILD_TELEMETRY_ENABLED` default
to false. Each needs a non-`unverified` binding revision and a private credential
file. No working `.env`, source data, IAM permissions or SSH settings were changed.

Parent configuration: `GA4_PROPERTY_ID`, `GA4_PARENT_STREAM_ID`,
`GA4_PARENT_PROPERTY_TIMEZONE`, `GA4_SERVICE_ACCOUNT_FILE`. The confirmed audit
binding is property `424940486`, Android parent stream `8216695933`, `Etc/GMT-5`;
IDs are operator configuration, never hardcoded runtime defaults. Other streams,
including the currently empty iOS stream, are not silently merged.

Child configuration: `FIREBASE_PROJECT_ID`, `FIREBASE_DATABASE_ID`,
`FIREBASE_SERVICE_ACCOUNT_FILE`, `FIREBASE_CHILD_SAMPLE_LIMIT` (default/max 100),
`FIREBASE_CHILD_PRECISE_ACCURACY_METERS` (default 100). The owner confirmed only
these two collections as MANA; other collections are not implicitly classified.

The adapters do not depend on the old Manakids Admin login or activate its collector.
OAuth scopes are `analytics.readonly` and `datastore`. Source requests use the
existing SQL ledger, fixed HTTPS hosts, no redirects/retries/compression, a 1 MiB
response ceiling (or a lower configured ceiling); OAuth has a separate 64 KiB limit.
Unknown charges remain reserved, and there is no automatic retry of a lost read.

The shared SQL gate enforces single-flight and a six-hour minimum interval across
users, agents, topics and restarts for the same product/source/binding. Query-shape
changes do not reset it. Cached facts retain observation dates; stale fallbacks
are labelled stale. Each Goal consumes its one-use approval before source I/O.

## Persistence and rollback

Shared evidence requires the exact validated contract, population and MANA scope
proof; unrelated Retention reports are not shared. Snapshot references include
checksum, period, observation age, completeness and minimized-aggregate privacy.

New native source requests use private Goal checkpoint v9, including after grant
consumption. Analysis scope, paging, continuation, memory and recovery invariants
remain validated. The supported `2ea7b9a` application sees a closed projection with
no read grant and retains private state. The deployed `9020b06` native reader cannot
read v9 and is NOT a safe v9 rollback target without a verified compatibility bridge.
Follow the existing worker-stop/pause protocol; never downgrade a populated schema.

## Costs and acceptance

The [saved cost calculation](../output/pdf/mana-data-availability-20261012/cost-forecast.md)
prices 200 reads plus a 2.125 MiB network reserve at ~$0.000369 per child cycle.
Four hypothetical cycles/day cost ~$0.05 per 30-day month and ~$0.54/year. This is
a small sample, not a complete database analysis or the whole Cloud bill. GA4
Standard reporting has no per-request monetary fee; quotas and model costs remain
separate. This calculation neither activates a schedule nor establishes invoices.

Hermetic checks cover adapter parsing/metering, SQL cache restart, changed query
shape, product/role isolation, native approval/result loading, failed/lost HTTP,
retained holds, disabled construction and actual legacy-image rollback. No real
model/source requests are part of these tests. Fakes are not production acceptance.

Before activation: production backup and compatible rollback images, authenticated
browser checks for these exact new source flows, read-only credential mounts,
budget review and separately scoped live acceptance remain required. The full
Codex/Claude objective also retains other context, quality, source coverage and
owning-domain action obligations. This checkpoint does not close that objective.
