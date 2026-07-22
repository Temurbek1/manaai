# Meta live read-only validation

Validated on 2026-07-22 against Graph/Marketing API `v25.0`. The selected account is referenced
only by the stable hash alias `2b6c4ddcc5`; raw account and business identifiers are excluded from
logs, evidence exports, and the admin UI.

## Result

The credential was valid and exactly one accessible ad account was discovered. The account context
was USD and `Asia/Karachi`. Meta returned no campaigns, ad sets, ads, creatives, custom audiences,
or insight rows for the completed period 2026-07-15 through 2026-07-21. Empty responses are recorded
as `empty`, never converted into a supported zero-valued performance metric.

All 13 compatibility checks completed without authentication, permission, rate-limit, or invalid
combination errors. They covered structure reads plus account, campaign, ad-set, and ad Insights,
including publisher/placement, region, age/gender, and advertiser-time-zone hourly breakdowns. Every
check was explicitly empty because the account has no delivery data in the period.

The nightly run persisted one `insufficient_data` finding and two advisory recommendations
(`observe` and `propose_test`). It created no proposals and no executions. The initial documented
validation persisted configuration version 7; immutable verification reruns culminated in version
13 during the Next.js migration with the same zero proposals/executions result. Because there were
no base rows, all 15 account calibration overrides are unavailable and inherit lower-layer defaults.

## Request evidence

The nightly collection made 15 successful GET requests, fetched 15 pages, received one account
discovery row, rejected no duplicates, used no retries, and completed in 7.775 seconds. The summed
individual request duration was 9.700 seconds because independent structure requests overlap. The
per-run guards were 40 requests, 40 pages, 8 retries, and 120 seconds.

The token debugger returned expiry fields as numeric zero. This means no finite timestamp was
reported by that response; it is not treated as proof that the credential can never expire. The
observed relevant permissions included `ads_read` and `business_management`. The token also has
broader scopes, so least-privilege replacement remains recommended.

## Read-only proof

- All live transport log entries were GET requests.
- Meta write helpers fail before authentication lookup or transport.
- Live proposals carry `execution_forbidden=true`.
- Executor, API, configuration, and UI guards independently reject live execution.
- Async Insights job creation is deliberately unavailable because Meta exposes it through POST.
- No notification was sent and no external system was mutated.

The official Meta Marketing API collection distinguishes GET reads from POST mutations and documents
the account/Insights resources exercised here: [Meta Marketing API collection](https://www.postman.com/meta/facebook-marketing-api/overview),
[account Insights example](https://www.postman.com/meta/facebook-marketing-api/request/u38qbri/get-insight-details-from-an-adaccount-l4),
and [official Python Business SDK](https://github.com/facebook/facebook-python-business-sdk).

## Evidence artifacts

- Sanitized machine evidence: `data/meta-live-readonly-evidence.json`
- Canonical bounded report input: `docs/artifacts/meta-live-readonly-report.artifact.json`
- Verified portable report: `docs/artifacts/meta-live-readonly-report.html`
- Manual Ads Manager comparison: `docs/meta-data-reconciliation.md`

These files contain no access token and no raw Meta account ID. The portable report passed canonical
schema, source-dialog, desktop, mobile, overflow, and external-request verification.
