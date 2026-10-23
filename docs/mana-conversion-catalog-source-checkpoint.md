# Conversion catalog — observed real prices and local source boundary

The full conversion goal remains unfinished. Real MANA tariff prices are now
known; the earlier statement that no catalog endpoint is available is superseded.
This is not approval of a commercial campaign, a checkout integration, a new
source refresh or a production release.

## Completed source observations — 2026-10-23

The already completed root discovery (session `82883`, exit 0) used one login,
one `GET /api/v1/` and one `GET /api/v1/admin-panel-payment/`. The API root returned
200 with same-origin links to `tariffs` and `payment-methods`; the payment admin
directory returned 404. No route brute force or customer scan was used.

The subsequent session `60443`, exit 0, used one fresh login and exactly one:

```http
GET https://api.manakids.uz/api/v1/tariffs/?limit=25&offset=0
```

It returned **200**, a direct five-record JSON array, collected at
**2026-10-23 11:34:43.938466 UTC /16:34:43 Asia/Samarkand**. These are the observed
ordinary catalog prices, not a synthetic promotional fixture:

| Tariff ID | Display plan | Price, UZS | Returned duration |
| --- | --- | ---: | --- |
| `3` | 1 month | 60,000.00 | 30 days |
| `8` | 3 months | 162,000.00 | 90 days |
| `9` | 6 months | 299,000.00 | 180 days |
| `7` | VIP, 1 month | 500,000.00 | 30 days |
| `4` | 1 year | 599,000.00 | 365 days |

Price strings and `price_currency="uzs"` are converted to exact two-decimal
minor units: the first plan is **6,000,000 minor units**, not 60,000 minor units.
The response uses whole-day duration strings, for example `30 00:00:00`.
The page does not independently establish complete catalog or recipient coverage.

`old_price` is null on the first two plans and present on three others. Neither
it nor a monthly/yearly flag proves an available 15% campaign, a promotional
code, automatic renewal or the price of the next billing period. The service
must not invent any of those terms. The names/descriptions are provider content,
not model instructions or approval.

A separate metadata attempt addressed the observed monthly detail and payment-
methods links. Its tool response was not retained in the available context and
no live process remains. Its contents/statuses are **unverified**, not a successful
checkout/renewal observation. It was not repeated to replace the lost response.
No payment, transaction, grant or push was invoked by catalog discovery, and no
direct Firestore/GA4 read occurred.

## Local implementation

- `ConversionCatalogSource` and strict minimized `ConversionCatalogObservation`
  keep only collection time, tariff ID, exact current price/currency and duration.
  A single bounded page is not labelled the whole catalog. Duplicate IDs fail.
- `ManakidsConversionCatalogSource` performs one fresh JWT login and one catalog
  GET per explicit invocation: HTTPS origin only, 16 KiB auth /64 KiB decoded
  catalog bounds, maximum 25 records, explicit wall timeout, no redirects,
  pagination, HTTP retry, relogin after a denial or payment call. Denied auth
  imposes a local cooldown. Cancellation propagates to the owning caller.
- Numeric/ambiguous IDs, coerced/non-decimal prices, zero prices, unsupported
  currencies, non-whole-day or out-of-range durations and duplicate JSON keys
  fail closed with controlled errors. No raw upstream detail is exposed.
- `catalog_price_rejection` compares separately approved ordinary offer terms
  against a matching numeric tariff ID. Future/over-six-hour observations,
  missing tariffs, changed prices/currency/duration and unverified discounts are
  rejected. A price match **does not approve** renewal terms, checkout, contact,
  account status, recipient applicability or a payment. Existing full offer
  schemas are not relaxed, and unknown terms are not defaulted to `false`.

The adapter is **not wired into runtime**. No catalog setting, public route,
private migration, source tool, automatic refresh or new source read on startup,
account admission, chat, observation GET or publication is introduced. Future
manual/runtime wiring must claim the read durably before HTTP, bound global
cost/refresh policy, retain unknown outcomes and make replay/restart SQL-only;
calling this adapter before the existing idempotent ingest would be incorrect.

No extra network read was made to test the new code. Its transport tests use
MockTransport; the five real catalog values are transcribed into one explicitly
offline parser check, not relabelled live-adapter or fresh source acceptance.
The previous packaged backend image does not contain this new adapter, and its
old candidate checks do not validate these new bytes.

## Remaining full-goal requirements

1. Confirm ordinary paid plan approval, actual in-app checkout mapping, renewal
   policy/recurring price where applicable and recipient eligibility. The real
   60,000 UZS plan can replace a hypothetical discount only once those independent
   conditions are verified. The agent never creates payments or transactions.
2. Integrate the owning backend's full-parent population/event producer, dated
   adult activity, language/timezone, commercial contact preferences, authoritative
   entitlement precedence and free-start history. Catalog prices do not supply
   any of those facts; child data and aggregate GA4 counts are not substitutes.
3. Complete separately approved real-channel/release acceptance and verified
   payment attribution. A free grant, conversation, interest or price match is
   not a measured paid conversion. Parent-Touch remains the only speaker.

No conversion source/contact flag, production service, source schedule, model
budget, SSH setting, key or old private receipt is changed by this increment.

## Actual local checks

Focused catalog/architecture session `27280` exited **0**: **87 passed**. The
catalog's **82 cases** are included in, not added to, the final backend total.
An earlier targeted run passed 77 cases but Ruff identified two loop-closure
bindings in its test transport. Those were corrected before the final full gate;
that earlier lint result is not called green.

Full **`make verify` session `53205`**, terminal exit **0**:

- **997 backend tests passed**, one skipped, two opt-in live excluded, 39.74s.
- **26 UI tests /11 suites**, TypeScript and Next **16.4.2** build passed.
- Ruff formatting/check, ESLint/34 compatibility cases and mypy **286 files**
  passed; npm audit found **zero vulnerabilities**.
- Secret scan passed **468 tracked/unignored files**; `git diff --check` passed.

All automated provider calls are fake. The real catalog observations predate
the new adapter, so these passing tests are not live-adapter/candidate-image
acceptance, real contact, complete parent coverage or paid conversion evidence.
