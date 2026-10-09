# Live first-party product activity runbook

## Candidate release boundary — 2026-10-08

Cost optimization is local and not deployed. The updated runtime requires an
approved `OPERATION_DATA_PRODUCT_SCOPE`, an explicit
`OPERATION_DATA_BINDING_REVISION`, a matching engagement configuration `product`,
and `GA4_PRODUCT_STREAM_IDS` for live GA4. Default ownership remains `unverified`
and refuses collection before authentication. A revision change must represent an
approved source/configuration recovery, not an automatic way around a circuit.

Automatic Firestore historical/prefix readers are **disabled**, including when old
settings request them, because no reliable update/deletion contract is established.
Only the backend/GA4 bundle participates in shared cached acquisition. The raw
Firestore adapter classes are not proof of an approved incremental integration.
Historical canary instructions later in this file are incident evidence, not
authorization for a new read or production activation.

No live test, new schedule, export, function, backend change or deployment is
authorized by this runbook. Use the separately approved release procedure in
[cost-optimization-implementation.md](cost-optimization-implementation.md).

## Invariants

- Every connector is read-only; these adapters implement no Manakids, GA4, or Firestore writes.
- Credentials are deployment secrets. Never commit service-account JSON or copy credentials into
  docs, logs, tests, images, or `.env.example`.
- Use dedicated service accounts and mount JSON files read-only outside the image.
- Start with the scheduler disabled and `OPERATION_DRY_RUN=true`.
- A Chrome/Firebase console session is suitable for manual inspection, not backend production
  authentication.

## Recommended production configuration

```dotenv
OPERATION_PRODUCT_ACTIVITY_PROVIDER=manakids_ga4
MANAKIDS_API_BASE_URL=https://api.manakids.uz
MANAKIDS_API_USERNAME=<secret-managed-service-account>
MANAKIDS_API_PASSWORD=<secret-managed-password>

GA4_PROPERTY_ID=<numeric-property-id>
GA4_SERVICE_ACCOUNT_FILE=/run/secrets/ga4-service-account.json
GA4_PRODUCT_STREAM_IDS=<JSON-array-of-owner-approved-numeric-stream-IDs>
OPERATION_DATA_PRODUCT_SCOPE=<mana-or-360rec-confirmed-by-owner>
OPERATION_DATA_BINDING_REVISION=<approved-config-revision>

FIREBASE_OPERATIONAL_TELEMETRY_ENABLED=false
FIREBASE_PROJECT_ID=bosstracker-dev
FIREBASE_DATABASE_ID=(default)
FIREBASE_SERVICE_ACCOUNT_FILE=/run/secrets/firebase-service-account.json
```

Grant the GA4 service-account email viewer access to the required Analytics property and use only
the `analytics.readonly` scope. Grant the Firebase service account only read access to the required
Firestore database/collections (for example, the narrowest organization-approved equivalent of
Datastore Viewer). The application validates that required files exist and that live base URLs use
HTTPS before startup.

The legacy `manakids_firebase` provider's raw adapter can read the canonical
collection, but the candidate shared runtime marks it unavailable without a
verified incremental contract. Collection existence and `occurred_at` alone are
insufficient: late arrivals, old-document updates and deletions must be covered.

`OPERATION_PRODUCT_ACTIVITY_PROVIDER=manakids` is an honest partial-live mode for deployments that
have Manakids credentials but do not yet have GA4 server credentials. It returns real backend
aggregates and marks mobile analytics as unconfigured with zero completeness; it never substitutes
fake mobile data.

The operational Firestore adapter normally uses a read-only service account. A project whose
existing Firestore rules already permit these five reads may explicitly set
`FIREBASE_PUBLIC_READ_ENABLED=true` and omit `FIREBASE_SERVICE_ACCOUNT_FILE`. This flag does not
change Firebase rules or grant access. It only permits unauthenticated reads already authorized by
the project, records `public_rules` in health diagnostics, and adds the access mode to every
snapshot limitation. Treat it as a temporary deployment mode and audit the Firebase rules with a
project owner.

Timeouts, retry budgets, backoff, page/document ceilings, and GA4 dimension limits are independently
configurable in `.env.example`. `MANAKIDS_MAX_PAGES` bounds each fixed-size Admin API scan; a capped
scan is partial and its measured completeness is retained.

## Docker secret mounts

Set both host-only paths before applying the product-activity overlay:

```dotenv
FIREBASE_SERVICE_ACCOUNT_HOST_FILE=/secure/host/firebase-reader.json
GA4_SERVICE_ACCOUNT_HOST_FILE=/secure/host/ga4-reader.json
```

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.product-activity.yml \
  -f docker-compose.product-activity-ga4.yml \
  up --build
```

The two overlays mount the files under `/run/secrets`; neither file is copied into an image. The
GA4 overlay is unnecessary when the canonical `manakids_firebase` mode is used instead.

## Controlled verification

Run hermetic gates first:

```bash
make verify
```

Then run the opt-in bounded live smoke test in an environment with the deployment secrets and
provider mode configured:

```bash
PRODUCT_ACTIVITY_LIVE_VERIFY=1 make product-activity-live-verify
```

The test authenticates to the Admin API, checks the selected mobile source, optionally checks the
operational Firestore source, reads at most one day of aggregate activity, and asserts that PII,
raw user/session IDs, and coordinates are absent from returned facts. It performs no writes.

After it passes:

1. Start the API with the scheduler still disabled and inspect integration health in `/agents`.
2. Trigger one manual `retention.engagement.analyze` run.
3. Verify source request IDs, completeness, limitations, report payload, and audit stages.
4. Enable `retention-engagement-analysis` scheduling only after that evidence is accepted.

## Latest external preflight evidence — 2026-10-05

The preserved bounded check in
[ga4-key2-access-20261005.md](../output/ga4-key2-access-20261005.md) returned HTTP 200
for OAuth, Analytics Admin account summaries and one Data API aggregate report for
property `424940486`. Thus the previous API-disabled/credential-unavailable status is
historical, not the current blocker. This report was not recollected for this local
cost-optimization work and does not prove every adapter report is accessible now.

What remains unconfirmed is the **product and parent/child population composition**
of the streams and legacy backend aggregates. Successful authentication cannot
confirm that composition. Existing saved metadata/IDs are collected in
[the source confirmation sheet](source-ownership-confirmation.md); owners only need
to correct/confirm the semantic labels, not supply a new key or discover numeric IDs.
The MANA-only Parent API confirmation does not approve the other sources.

Until those bindings are approved, keep the candidate bundle unverified and refuse
collection before authentication. Firestore automatic scans remain disabled pending
a reliable change/deletion contract. Do not activate the old public-read or canary
recipes below merely because credentials or existing rules permit a read.

### Historical preflight — 2026-09-26

As of 2026-09-26, practical read-only checks confirmed the Manakids login and all documented
aggregate endpoints, GA4 property `424940486` with live events, and public REST reads for the five
selected Firestore operational collections. The authorized Google account is only a Firebase
Viewer and could not create a private key at that checkpoint. No existing
GA4/Firestore service-account JSON was found in the then-inspected files or browser
sources. This historical observation was superseded by the subsequently provided
read-only key and the 2026-10-05 successful GA4 report. It is **not authorization**
to activate public-rule Firestore reads or a new production integration.

Detailed Crashlytics analysis is also blocked on an approved BigQuery/export path and is reserved
for Technical Reliability. Do not label GA4 `app_exception` counts as crash root-cause analysis.

## Incident response

### Retention read safety controls

The 2026-09-28 remediation introduces explicit process settings:

```dotenv
OPERATION_SCHEDULER_MAX_ATTEMPTS=3
OPERATION_SCHEDULER_PERMANENT_FAILURE_THRESHOLD=3
FIREBASE_MAX_ACTIVITY_DOCUMENTS=5000
FIREBASE_OPERATIONAL_MAX_DOCUMENTS_PER_COLLECTION=5000
FIREBASE_MAX_DOCUMENT_READS_PER_RUN=25000
FIREBASE_MAX_PAGES_PER_RUN=30
FIREBASE_MAX_REQUESTS_PER_RUN=40
```

The last three limits are shared across canonical and operational Firestore sources, not multiplied
by the number of collections. If both sources are enabled, size their sampling limits to fit the
shared budget. Exceeding a limit raises a permanent controlled error before the next request.
Budget exhaustion is never silently presented as a successful complete analysis. The existing
per-collection sampling cap still reports truncation explicitly in data-quality notes.

Each HTTP attempt reserves its requested document limit (at least one), including retries,
timeouts and cancelled requests. Reservations are not refunded. This bounds document retrieval,
not the entire Google Cloud invoice: index reads, security-rule dependent reads, network and
storage have their own billing. See the official [Firestore billing explanation](https://firebase.google.com/docs/firestore/pricing)
and [listDocuments page-size contract](https://firebase.google.com/docs/firestore/reference/rest/v1/projects.databases.documents/list).

For an operational-only canary, keep the schedule disabled and use a one-document collection cap,
`FIREBASE_MAX_DOCUMENT_READS_PER_RUN=5`, `FIREBASE_MAX_PAGES_PER_RUN=5`,
`FIREBASE_MAX_REQUESTS_PER_RUN=5`, `FIREBASE_MAX_RETRIES=0`, `MANAKIDS_MAX_RETRIES=0`,
`MANAKIDS_MAX_PAGES=1`, and `OPERATION_SCHEDULER_MAX_ATTEMPTS=1`. Use one unique manual idempotency
key. Replaying that key must not collect again, even if its run failed. Do not turn this into an
automatic production smoke loop. A successful bounded sample is not proof of complete analytics.

Structured `Retention provider request` records count dispatches by provider/endpoint, retries,
status and duration. `Retention Firestore budget summary` reports the run ID, observed returned
documents separately from reserved upper bounds, pages, requests by endpoint, and stop reason.
Scheduler terminal logs/audit expose circuit state and consecutive permanent errors. No request
body, auth headers, page token, raw document or user identifier is logged. Compare these counters
with Billing/Monitoring when assessing cost; do not describe sampled or reconstructed counts as
actual billed reads.

Manakids refreshes on the first 401 **or** 403, shares refreshes for concurrent rejections of the
same token generation, then repeats the original request once. A second rejection is permanent.
Login failures do not start the Manakids endpoint batch. Mandatory-source errors cancel and drain
already started Firestore batches; already dispatched remote reads cannot be undone.

### Response procedure

- Disable the Retention schedule or its capability kill switch first.
- Preserve only run/correlation IDs, provider request IDs, checksums, aggregate counts, and
  sanitized error categories.
- Rotate a credential immediately if it appears in logs or an artifact.
- For `401`/`403`, identify the exact missing read permission; do not broaden access blindly.
- For a document/report ceiling, reduce the window or add a governed aggregation/export pipeline;
  never silently treat a partial result as complete.
