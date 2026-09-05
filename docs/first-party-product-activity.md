# First-party product activity data

## Scope

`retention.engagement.analyze` is the first implemented Retention & Loyalty capability. It combines
two application-owned, read-only sources:

- the Manakids Admin API for backend facts;
- Firebase Firestore for mobile product events emitted by the Manakids application.

Advertising platforms, Meta data, raw child content, precise location, and provider-specific
marketing data are outside this capability. The Operation AI database stores only aggregate facts,
checksums, request IDs, findings, and reports. It does not store names, phone numbers, raw child or
session IDs, GPS, message text, or raw search queries.

The repository defaults to deterministic fake sources. Live reads are enabled only by explicitly
setting `OPERATION_PRODUCT_ACTIVITY_PROVIDER=manakids_firebase` and providing both source
credentials through deployment secrets.

## Backend authority

The Manakids adapter uses the application Admin API documented by the product team:

| Endpoint | Aggregate retained by Operation AI |
| --- | --- |
| `GET /api/v1/admin-panel-common/account/` with `role=PARENT` or `role=CHILD` and join-date bounds | Parent and child registrations in the window |
| `GET /api/v1/admin-panel-child/child-list/` | Current child inventory count |
| `GET /api/v1/admin-panel-child/app-usage-statistics/` | Children with non-empty nested app-usage statistics in the bounded scan |
| `GET /api/v1/admin-panel-child/camera-audio-usage-logs/` | Children with non-empty camera/audio/screen-share logs in the bounded scan |

Authentication uses `POST /api/v1/admin-panel-auth/login/`. The access token is kept in process
memory, refreshed once after a `401`, never persisted, and never included in errors or health
diagnostics. Read requests have bounded timeouts, retries, exponential backoff, and a configurable
page ceiling. Upstream response rows are discarded after the adapter checks only whether the
documented nested activity collection is empty.

The bulk activity endpoints return every child with a fixed page size of 10. Their outer
`total_count` is the child population, not an active-child count. The adapter therefore scans at
most `MANAKIDS_MAX_PAGES`, counts only rows with non-empty nested activity, records scanned/population
coverage as completeness, and never extrapolates a partial sample into a global total. A low
coverage result produces a data-incomplete finding instead of a low-engagement conclusion. An
exact global active-child count will require a server-side aggregate endpoint or export.

This source currently supports registration-completed and coarse feature/app-usage measurements.
It does not prove app opens/closes, screens, clicks, searches, navigation, form completion, upload
events, precise screen time, or action sequences.

## Mobile event contract

The mobile application must write one Firestore document per event to the configured
`app_activity_events` collection. The server queries it read-only by `occurred_at`.

Required fields:

| Field | Firestore type | Rule |
| --- | --- | --- |
| `schema_version` | string | Exactly `app-activity-v1` |
| `event_type` | string | One of the supported values below |
| `occurred_at` | timestamp | UTC event time; used for the bounded query |
| `subject_id` | string | Stable application-internal subject ID; never persisted by Operation AI |
| `session_id` | string | Mobile session ID; never persisted by Operation AI |

Optional fields use a controlled lowercase taxonomy (`a-z`, digits, `_`, `-`, `.`, maximum 64
characters) so arbitrary user text cannot become an analytics dimension:

- `duration_ms`: non-negative integer, required for useful `screen_time` events;
- `sequence_number`: monotonic non-negative integer within a session; used to break equal-time
  event ties for aggregate action transitions;
- `screen`, `previous_screen`, `feature`, `button`, `form`, `file_type`: bounded product taxonomy
  values;
- `query_length`, `filter_count`, `sort_used`: search metadata without the raw search text.

Supported `event_type` values:

```text
app_open
app_close
screen_view
button_click
search
navigation
registration_started
registration_completed
form_completed
file_uploaded
feature_used
screen_time
```

Do not send raw search text, form contents, filenames, notification/message contents, phone
numbers, email addresses, names, or GPS in this collection. Unknown schemas, unsupported event
types, missing identifiers/timestamps, out-of-window timestamps, and negative durations are
excluded and reduce completeness. Reaching `FIREBASE_MAX_ACTIVITY_DOCUMENTS` marks the result as
potentially partial.

Example mobile document:

```json
{
  "schema_version": "app-activity-v1",
  "event_type": "screen_time",
  "occurred_at": "2026-09-05T09:15:00Z",
  "subject_id": "application-internal-id",
  "session_id": "installation-session-id",
  "screen": "dashboard",
  "duration_ms": 42000
}
```

The adapter uses raw identifiers only in memory to calculate distinct subject/session counts and
aggregate event-type transitions, then discards them. It persists event counts, bounded screen/
button/feature/form/file/search dimensions, per-screen time, and aggregate action-sequence counts.
It never persists an individual timeline. Existing Firestore collections such as `battery`,
`calls`, `children_location`, `internet`, `monitoring`, and WebRTC signalling are not substitutes
for this mobile product-event contract.

## Runtime output

The capability runs every six hours by default and persists:

- backend registration and inventory aggregates;
- observed backend-active child count, conservatively calculated as the larger of the two scanned
  backend activity populations and capped by inventory, together with scan coverage limitations;
- mobile active-subject/session counts, event counts, safe taxonomy dimensions, aggregate event
  transitions, and total/per-screen time;
- evidence checksums, source request IDs, completeness, limitations, deterministic metrics,
  findings, report, and full run-stage audit.

Backend and Firebase subjects are deliberately reported separately until an approved,
privacy-preserving cross-source identity mapping exists. Their populations are not summed.
Classification/reporting is implemented; customer messaging, discounts, subscription mutation,
win-back, loyalty, and referral actions are not implemented yet.
