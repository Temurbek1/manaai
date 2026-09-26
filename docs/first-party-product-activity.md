# First-party product activity data

## Scope and current sources

`retention.engagement.analyze` is the first implemented Retention & Loyalty capability. It can
combine three application-owned, read-only sources:

- Manakids Admin API backend aggregates;
- Google Analytics 4 aggregate mobile analytics (the recommended live mobile source);
- optional aggregate operational state from existing Firebase Firestore collections.

The repository defaults to deterministic fake sources. The recommended live combination is
`OPERATION_PRODUCT_ACTIVITY_PROVIDER=manakids_ga4` plus
`FIREBASE_OPERATIONAL_TELEMETRY_ENABLED=true`. The older
`OPERATION_PRODUCT_ACTIVITY_PROVIDER=manakids_firebase` mode remains available for a future
canonical `app_activity_events` collection, but that collection was not present in the audited
Firebase project on 2026-09-25. The explicit `manakids` mode connects only real backend aggregates
and marks mobile analytics unavailable instead of mixing fake values into a live run.

Advertising platforms, Meta data, raw child content, and provider-specific marketing data are
outside this capability. Operation AI stores only aggregate facts, checksums, provider request
IDs, findings, and reports. It does not store names, phone numbers, child/device/session IDs,
precise coordinates, message text, filenames, or raw search queries.

## Verified availability

The Firebase project and linked Analytics property were inspected through the authorized Firebase
console session. This table distinguishes data that exists now from data that would require new
instrumentation or export configuration.

| Source | Already observable and connected by this implementation | Important limit |
| --- | --- | --- |
| Manakids Admin API | Registration completion by role/date, child inventory, presence of app-usage statistics, presence of camera/audio/screen-share usage | Bulk activity endpoints use a fixed ten-child page; capped scans report measured coverage and never extrapolate |
| GA4 Data API | Active users for 1/7/30 days, sessions, engaged sessions, new users, engagement duration, screen views, app version, OS/version, device brand/model, language, country/region/city, and supported event counts | Aggregate reports do not expose an individual action sequence or raw user/session identifiers |
| GA4 events observed | `screen_view`, `button_click`, `session_start`, `first_open`, `user_engagement`, `app_exception`, `notification_receive`, `notification_dismiss`, `notification_open`, `notification_foreground`, `app_update`, `os_update`, `app_clear_data`, `app_remove` | An absent event is returned as zero, not inferred from another signal |
| Firestore operational collections | Device counts with battery state, silent-mode count, device counts with a current location, moving-device count, internet records, monitoring enabled/disabled, and screen-command counts | These are current operational records, not analytics sessions or ordered user timelines |

The selected operational collections currently allow public REST reads. Production may use those
existing rules only with the explicit `FIREBASE_PUBLIC_READ_ENABLED=true` opt-in; the run records
that mode as a limitation. This is not a substitute for fixing overly broad Firebase rules and
provisioning a least-privilege service identity.

The operational Firestore reader currently covers `battery`, `children_location`, `internet`,
`monitoring`, and `screen-commands`. It reads child IDs and coordinates only long enough to dedupe
and aggregate in memory, then discards them. It deliberately does not ingest raw documents from
`calls`, `recordCollection`, `stream`, `webrtc`, `webrtc-audio`, `webrtc-screen`, or
`webrtc-settings` into the Retention data plane.

Crashlytics contains useful crash/error/device/action-before-crash evidence, but detailed
Crashlytics analysis is not connected here: it belongs to the future Technical Reliability agent
and requires a governed BigQuery export or another approved server-side export. The GA4
`app_exception` event supplies only an aggregate exception count. Firebase Performance Monitoring,
Firebase A/B Testing, and Firebase Authentication were not configured during the audit. Their
metrics must not be represented as available.

## Backend authority

The Manakids adapter uses these application endpoints:

| Endpoint | Aggregate retained by Operation AI |
| --- | --- |
| `GET /api/v1/admin-panel-common/account/` with `role=PARENT` or `role=CHILD` and join-date bounds | Parent and child registrations in the window |
| `GET /api/v1/admin-panel-child/child-list/` | Current child inventory count |
| `GET /api/v1/admin-panel-child/app-usage-statistics/` | Children with non-empty nested app-usage statistics in the bounded scan |
| `GET /api/v1/admin-panel-child/camera-audio-usage-logs/` | Children with non-empty camera/audio/screen-share logs in the bounded scan |

Authentication uses `POST /api/v1/admin-panel-auth/login/`. The token stays in process memory, is
refreshed once after a `401`, and is never included in errors or health diagnostics. Requests use
bounded timeouts, retries, exponential backoff, and a configurable page ceiling. A partial scan
reduces completeness and creates a data-quality finding instead of a false engagement conclusion.

## GA4 aggregate contract

The GA4 adapter uses `properties.runReport` with an `analytics.readonly` OAuth scope. It issues
bounded aggregate queries and maps only known event names into `ActivityEventType`. Unknown event
names are ignored. Free-form dimension values are normalized into a bounded taxonomy; raw values
and analytics identifiers are not persisted.

The adapter supplies:

- DAU/WAU/MAU-style active-user windows (1, 7, and 30 days);
- sessions, engaged sessions, new users, and aggregate engagement seconds;
- known event counts, screen-view counts, and device/app/locale/geography distributions;
- explicit limitations when a configured top-N dimension limit truncates a report.

GA4 Data API aggregation cannot reconstruct per-user action sequences. That requires a separately
approved GA4 BigQuery export with retention, access, and minimization controls.

## Optional canonical Firestore event contract

If the mobile team later emits `app_activity_events`, the existing
`manakids_firebase` adapter supports one document per event with:

- `schema_version=app-activity-v1`;
- `event_type`, `occurred_at`, `subject_id`, and `session_id`;
- optional bounded `screen`, `previous_screen`, `feature`, `button`, `form`, and `file_type`;
- optional `duration_ms`, `sequence_number`, `query_length`, `filter_count`, and `sort_used`.

Raw search text, form contents, filenames, notification/message contents, contact data, and GPS
must never be emitted to this collection. The adapter uses subject/session identifiers only in
memory for distinct counts and aggregate transitions, then discards them.

## Runtime output

The capability runs every six hours by default and persists:

- backend registration, inventory, and bounded usage aggregates;
- aggregate mobile users, sessions, engagement, events, and safe dimensions;
- optional aggregate operational device state;
- evidence checksums, provider request IDs, completeness, limitations, deterministic metrics,
  findings, report, and full run-stage audit.

Backend and mobile populations remain separate until an approved privacy-preserving identity map
exists. Customer messaging, discounts, subscription mutation, win-back, loyalty, and referral
actions are not implemented yet.
