# Meta live-readiness

The Marketing Agent is live-read-ready in a permanent read-only mode. Graph/Marketing API `v25.0`
was validated on 2026-07-22 against exactly one accessible account. Detailed evidence is in
`docs/meta-live-validation.md`; operations are in `docs/live-read-only-runbook.md`.

## Contract

Async `httpx` calls and Meta dictionaries terminate inside the advertising infrastructure adapter.
The agent receives provider-neutral typed snapshots. API version, fields, time range, breakdowns,
pagination, retries, and run budgets are explicit configuration. The official contract references
are the [Meta Python Business SDK](https://github.com/facebook/facebook-python-business-sdk), its
[releases](https://github.com/facebook/facebook-python-business-sdk/releases), and Meta's
[official Marketing API collection](https://www.postman.com/meta/facebook-marketing-api/overview).

## Proven live surface

- credential debug and owned/client account discovery;
- campaigns, ad sets, ads, creatives, and custom audiences;
- account/campaign/ad-set/ad Insights;
- base daily reads and placement, region, age/gender, and account-time-zone hourly breakdown plans;
- currency, account time zone, attribution identity, completed-period boundaries;
- bounded pagination, request/page/retry/time cancellation, error classification, and redacted logs.

The selected account had no delivery rows. Endpoint access and empty-result semantics are proven;
multi-page cursor behavior, delayed conversions, non-empty breakdown values, and rate-limit recovery
remain fixture-tested rather than live-observed.

## Compatibility policy

Every query records one of `supported`, `empty`, `permission_denied`, `unavailable`, `rate_limited`,
`invalid_combination`, or `partial`. A failed/missing query never becomes zero. Mixed currency or
attribution suppresses unsafe financial aggregation. Derived metrics require available inputs and
positive denominators.

Async Insights creation is POST and therefore unavailable in live mode. Large accounts must reduce
period/breakdown scope or use a separately authorized read-only architecture that does not weaken the
no-POST boundary.

## Permanent write prohibition

The live provider mode is `live_read_only`. Startup rejects real-write configuration, the Meta client
rejects POST before transport, the adapter rejects execution, the lifecycle marks proposals
forbidden/advisory, the API returns typed 403, and the UI offers acknowledgement only. The token's
ability to hold broader scopes does not change this application policy.

No real Meta write was attempted. No canary or write rollout is planned by this contract.
