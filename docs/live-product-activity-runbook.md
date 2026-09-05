# Live first-party product activity runbook

## Invariants

- The integration is read-only. The adapters implement no application or Firestore writes.
- Credentials come from deployment secrets; never commit the supplied handoff file or copy its
  credentials into documentation, logs, test fixtures, images, or `.env.example`.
- Use a dedicated Manakids service account restricted to the documented Admin API endpoints.
- Use a dedicated Google service account with only the Firestore read permissions needed for the
  configured project/database/collection.
- Mount the Google service-account JSON read-only outside the image and set its container path in
  `FIREBASE_SERVICE_ACCOUNT_FILE`.
- Keep the scheduler disabled for the first verification.

## Configuration

```dotenv
OPERATION_PRODUCT_ACTIVITY_PROVIDER=manakids_firebase
MANAKIDS_API_BASE_URL=https://api.manakids.uz
MANAKIDS_API_USERNAME=<secret-managed-service-account>
MANAKIDS_API_PASSWORD=<secret-managed-password>
FIREBASE_PROJECT_ID=bosstracker-dev
FIREBASE_DATABASE_ID=(default)
FIREBASE_SERVICE_ACCOUNT_FILE=/run/secrets/firebase-service-account.json
FIREBASE_ACTIVITY_COLLECTION=app_activity_events
```

Startup rejects live mode when either source is incomplete, the Admin API URL is not HTTPS, or the
service-account file is missing. Timeouts, retry budgets, backoff, and maximum Firestore documents
are independently configurable in `.env.example`.

`MANAKIDS_MAX_PAGES` bounds each Admin API activity scan. The verified bulk endpoints keep a fixed
10-child page size even when a larger `limit` is requested. Until the application exposes a
server-side active-child aggregate, production reports must treat a capped scan as partial and use
its recorded completeness rather than extrapolating it.

For Docker Compose, set `FIREBASE_SERVICE_ACCOUNT_HOST_FILE` to the host path and include the
read-only secret-mount overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.product-activity.yml up --build
```

## Controlled verification

Run hermetic gates first:

```bash
make verify
```

Then, in an environment where the secrets are installed:

```bash
PRODUCT_ACTIVITY_LIVE_VERIFY=1 make product-activity-live-verify
```

The opt-in test performs only authentication and bounded reads, checks both integration health
responses, collects at most one day of aggregates, and asserts that no raw user/session identifiers
are present in the returned domain facts. It does not write to the Admin API, Firebase, or the
Operation AI action system.

After it passes, inspect Retention & Loyalty in `/agents`, trigger one manual
`retention.engagement.analyze` run, verify completeness/limitations and the run audit, and only then
enable `retention-engagement-analysis` scheduling.

## Current external preflight status

On 2026-09-05, the corrected external service account authenticated successfully against the
documented login route. Bounded read-only checks verified the account, child-list, app-usage, and
camera/audio/screen endpoint envelopes. No credentials, access tokens, names, phone numbers, or raw
response rows were persisted. The account join filters require `YYYY-MM-DD` values, and the bulk
activity endpoints expose a fixed 10-child page size with nested activity data.

A mounted Firebase service-account file and a populated mobile `app_activity_events` collection
are still required before the combined live capability can be activated. This does not affect
fake-mode or hermetic test readiness.

## Incident response

- Disable the Retention schedule or its capability kill switch first.
- Preserve only run/correlation IDs, request IDs, checksums, aggregate counts, and sanitized error
  categories.
- Rotate a credential immediately if it appears in logs or an artifact.
- For `401`/`403`, validate service-account status and least-privilege permissions; do not broaden
  access until the exact missing read permission is identified.
- For Firestore invalid-document findings, fix mobile schema/version emission and retain the old
  reader until the new version has verified coverage.
- For collection-limit findings, reduce the lookback window or add a governed aggregation/export
  pipeline; do not silently treat a partial window as complete.
