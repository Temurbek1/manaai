# Meta API to Ads Manager reconciliation

Automated Ads Manager UI access was not available. The table therefore preserves visible
placeholders for the human-entered UI values and does not invent reconciliation evidence.

## Exact Ads Manager setup

1. Open Ads Manager and select account alias `2b6c4ddcc5` using the privately maintained alias map.
2. Set the account reporting time zone to the displayed account setting, `Asia/Karachi`.
3. Set an absolute date range from 2026-07-15 through 2026-07-21. Do not include 2026-07-22.
4. Select the same attribution identity used by the normalized run: 7-day click. Record any UI
   option that also enables view-through attribution as a mismatch rather than silently accepting it.
5. Use delivery columns for spend, impressions, reach, clicks, leads, conversions, CTR, CPC, CPM,
   CPL, CPA, and ROAS. Confirm currency is USD.
6. Compare campaign, ad-set, and ad tabs without a delivery-status filter, then repeat with the UI's
   active/delivering filter and record that filter separately.
7. Enter the UI values below. A reviewer must sign and date the result.

## Comparison worksheet

| Metric | API result | Ads Manager UI actual | Difference | Status |
| --- | ---: | ---: | ---: | --- |
| Campaigns | 0 | `<enter UI value>` | `<calculate>` | `pending manual check` |
| Ad sets | 0 | `<enter UI value>` | `<calculate>` | `pending manual check` |
| Ads | 0 | `<enter UI value>` | `<calculate>` | `pending manual check` |
| Spend (USD) | unavailable | `<enter UI value>` | `<calculate if comparable>` | `pending manual check` |
| Impressions | unavailable | `<enter UI value>` | `<calculate if comparable>` | `pending manual check` |
| Reach | unavailable | `<enter UI value>` | `<calculate if comparable>` | `pending manual check` |
| Clicks | unavailable | `<enter UI value>` | `<calculate if comparable>` | `pending manual check` |
| Leads | unavailable | `<enter UI value>` | `<calculate if comparable>` | `pending manual check` |
| Conversions | unavailable | `<enter UI value>` | `<calculate if comparable>` | `pending manual check` |
| CTR | unavailable | `<enter UI value>` | `<calculate if comparable>` | `pending manual check` |
| CPC / CPM | unavailable | `<enter UI value>` | `<calculate if comparable>` | `pending manual check` |
| CPL / CPA / ROAS | unavailable | `<enter UI value>` | `<calculate if comparable>` | `pending manual check` |

`Unavailable` is intentional: an empty Insights response is not evidence for a computed zero rate or
cost. If Ads Manager shows non-zero delivery, capture the UI date/time zone, attribution setting,
column preset, status filters, and export timestamp before investigating delayed attribution,
account selection, permissions, or API/UI freshness.

Reviewer: `<name>`

Reviewed at: `<ISO-8601 timestamp>`
Outcome: `<matched / mismatch under investigation>`
