# Growth advertising capability

> **Current implementation:** the former Marketing Agent runs as `growth.advertising` inside
> `growth-agent`. `marketing-agent` is a temporary API/runtime alias: it creates new runs under
> `growth-agent`, exposes preserved legacy history, and owns no duplicate schedules. Live Meta
> remains read-only; executable advertising lifecycle tests use `fake_meta`.

## Provider data

`AdsPlatform` is provider-neutral. The completed providers are:

- `fake_meta`: mutable, deterministic sandbox with campaigns, ad sets, ads, creatives, audiences,
  budgets, delivery, baselines, region/placement/age/gender/hour/day insights, and idempotent writes.
- `meta`: typed wrapper over the existing Graph API client. It normalizes account structure,
  creatives, custom audiences/targeting attributes, and daily ad insights.

Meta does not allow every breakdown combination. The adapter creates separate safe query plans for
base, placement, region, age+gender, and advertiser-timezone hour. Rows carry an internal query
scope; base KPIs use only base rows so spend is not counted once per breakdown. Day is derived from
daily rows. Pagination is bounded by `META_MAX_PAGES`; transient transport errors, 429, 5xx, and
Meta transient error codes use exponential backoff. Provider request IDs, retry counts, status, and
rate-limit signals are persisted without tokens.

## Deterministic analytics

Every run saves the normalized snapshot before analysis. Decimal code calculates spend,
impressions, reach, clicks, link clicks, conversions, leads, revenue, CTR, CPC, CPM, CPL, CPA, ROAS,
and frequency. Division by absent/zero values returns `unavailable` with a reason.

The engine identifies:

- best/weak creatives and cheap/expensive audiences;
- best/worst regions, placements, hours, and days when available;
- efficient budget-constrained and wasteful ad sets;
- efficient paused ad sets;
- frequency + CTR + cost fatigue;
- cost change against the object baseline;
- missing requested dimensions and insufficient observations.

All thresholds, objective, attribution, periods, financial limits, confidence, cooldown, permitted
actions, approval requirements, cron schedules, timezone, accounts, breakdowns, and notifications
come from the versioned `MarketingAgentConfiguration` schema.

## Recommendations and actions

The engine emits typed recommendations for budget increase/decrease, pause, resume, scale/disable
audience, maintain, observe longer, and propose a test. Maintain/observe/test recommendations never
reach a provider executor. Executable parameter unions are fixed Pydantic models; arbitrary model or
LLM payloads cannot be passed to Meta.

For executable fake-provider actions, the lifecycle service:

1. requires an approved proposal;
2. checks global, Growth-agent, and `growth.advertising` kill switches;
3. loads and validates the active configuration;
4. re-evaluates confidence, action, budget, cooldown, and daily execution limits;
5. reads provider state and compares its hash with proposal state;
6. claims a unique execution idempotency key;
7. records before state and typed requested change;
8. performs a dry run or provider action;
9. reads state again and compares Decimal budgets/status;
10. stores succeeded/partially-applied/failed execution, verification, and audit events.

Live Meta is a separate `live_read_only` provider mode. Recommendations are advisory,
`execution_forbidden=true` is persisted, acknowledgement cannot authorize execution, and any execute
request returns a typed 403 before a provider call. Startup rejects attempts to enable real Meta
writes.

## Reports

Analysis and nightly reports store structured and human-readable forms. They contain period, KPIs,
creative/audience/region rankings, anomalies, actions, pending approvals, failures, next
recommendations, and data quality. Missing values remain unavailable. Nightly reports complete and
surface pending approvals instead of waiting for them. `NotificationPort` is invoked only for
configured channels; the built-in `log` adapter records metadata but deliberately omits report text.
