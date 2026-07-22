# Meta attribution and metric identity

The live normalized snapshot records `7d_click` as its attribution identity. The analysis period is
based on completed account-local days in `Asia/Karachi`, ending before the current day. Currency is
USD. These three dimensions are part of every finding/report identity and must match Ads Manager
before values are compared.

The configured Insights request supports explicit action attribution windows (`1d_click` and
`7d_click` in the environment template). The normalized live report uses the declared `7d_click`
identity for human comparison. It does not merge view-through results or pretend attribution windows
are interchangeable.

Meta Insights exposes action attribution windows and unified attribution settings as distinct query
controls: [official attribution request example](https://www.postman.com/meta/facebook-marketing-api/request/5wdl62t/attributionsetting).

## Metric rules

- Spend, impressions, reach, clicks, leads, conversions, and conversion value come from normalized
  available fields only.
- CTR, CPC, CPM, CPL, CPA, and ROAS are computed only when required numerators/denominators are
  available and denominators are positive.
- Empty responses produce unavailable metrics, not zeros.
- Baseline comparison uses disjoint completed periods and the same account/currency/attribution
  identity.
- Conversion-lag interpretation requires observed historical data; it was not estimated from the
  empty live period.

For manual reconciliation, use the exact procedure in `docs/meta-data-reconciliation.md`. If the UI
cannot select the same attribution identity, record the comparison as non-comparable.
