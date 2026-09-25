# Live first-party product activity runbook

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

FIREBASE_OPERATIONAL_TELEMETRY_ENABLED=true
FIREBASE_PROJECT_ID=bosstracker-dev
FIREBASE_DATABASE_ID=(default)
FIREBASE_SERVICE_ACCOUNT_FILE=/run/secrets/firebase-service-account.json
```

Grant the GA4 service-account email viewer access to the required Analytics property and use only
the `analytics.readonly` scope. Grant the Firebase service account only read access to the required
Firestore database/collections (for example, the narrowest organization-approved equivalent of
Datastore Viewer). The application validates that required files exist and that live base URLs use
HTTPS before startup.

The alternative `manakids_firebase` provider reads the canonical collection configured by
`FIREBASE_ACTIVITY_COLLECTION`. Do not enable it until `app_activity_events` exists and the mobile
event contract in `first-party-product-activity.md` is being emitted reliably.

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

## Current external preflight status

As of 2026-09-25, the authorized console audit confirmed live GA4 events and the listed Firestore
operational collections. The Manakids Admin API had also previously passed bounded read-only
envelope checks. The local project `.env` does not currently contain the Manakids credentials,
numeric GA4 property ID, or mounted GA4/Firestore service-account paths, so the live smoke test and
production activation remain externally blocked until deployment secrets are provisioned.

Detailed Crashlytics analysis is also blocked on an approved BigQuery/export path and is reserved
for Technical Reliability. Do not label GA4 `app_exception` counts as crash root-cause analysis.

## Incident response

- Disable the Retention schedule or its capability kill switch first.
- Preserve only run/correlation IDs, provider request IDs, checksums, aggregate counts, and
  sanitized error categories.
- Rotate a credential immediately if it appears in logs or an artifact.
- For `401`/`403`, identify the exact missing read permission; do not broaden access blindly.
- For a document/report ceiling, reduce the window or add a governed aggregation/export pipeline;
  never silently treat a partial result as complete.
