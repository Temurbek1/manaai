# Meta request budgets and rate-limit behavior

Meta can limit Graph/Marketing API traffic by app, business use case, and ad account. The service does
not hardcode or claim a provider quota formula. It reads available usage headers, records sanitized
usage diagnostics, classifies 429/rate-limit errors, honors `Retry-After`, and applies bounded
exponential retry behavior for transient failures.

## Application limits

| Guard | Default | Behavior |
| --- | ---: | --- |
| Requests per live run | 40 | Reservation happens before transport; request 41 is never sent. |
| Pages per live run | 40 | Page reservation happens before following pagination. |
| Pages per endpoint | 10 | Stops one list/breakdown from consuming the whole run. |
| Total retries | 8 | Shared across the run, not reset per endpoint. |
| Duration | 120 seconds | Cancellation/time check applies before later work. |
| Accounts | 1 | The live workflow stops unless exactly one account is accessible. |

The verified nightly run used 15/40 requests, 15/40 pages, 0/8 retries, and 7.775/120 seconds. No
rate-limit event occurred and no provider usage value was returned that warranted throttling.

The official Meta Insights collection calls out limits and best practices and notes async jobs for
large results: [Insights API collection](https://www.postman.com/meta/facebook-marketing-api/folder/zzd6d5p/insights-api).
This application does not use async jobs in live mode because creating them is POST.

## Operator response

1. Do not raise budgets during an incident.
2. Inspect sanitized error class, status, retry-after, usage headers, run ID, and account alias.
3. Let the current run stop at its deterministic boundary; do not replay without an idempotent reason.
4. Reduce requested period/breakdowns or schedule frequency after the provider window recovers.
5. Treat repeated permission or invalid-combination errors as permanent configuration issues, not
   retry candidates.
6. Keep the last successful snapshot/report visible and mark freshness unavailable or stale.
