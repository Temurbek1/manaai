# Marketing AI Layer Design

This document captures the implementation contract for the marketing layer.
It is based on official Meta Marketing API, Graph API, Business Management API,
and OpenAI Responses API guidance.

## Official API Baseline

- Meta Graph API / Marketing API version: `v25.0`, configurable with `META_GRAPH_API_VERSION`.
- Meta app id, business id, ad account ids, and access token must come from environment variables.
- Automated server integrations should use a Meta Business system user access token assigned to the required business assets.
- Marketing API data must be requested with explicit fields, cursor pagination, and rate-limit-aware error handling.
- Large or expensive insights pulls should use async insights jobs: submit a job, poll `report_run_id`, then download paginated results.
- OpenAI analysis should use typed structured outputs instead of free-form text when the backend needs reliable downstream analytics.

Official sources:

- Meta Marketing API overview: https://developers.facebook.com/documentation/ads-commerce/marketing-api
- Meta Ads Insights API: https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights
- Meta Insights best practices: https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights/best-practices
- Meta Marketing API rate limiting: https://developers.facebook.com/documentation/ads-commerce/marketing-api/overview/rate-limiting
- Meta Business system users: https://developers.facebook.com/docs/business-management-apis/system-users/
- Meta Graph API changelog: https://developers.facebook.com/docs/graph-api/changelog/
- OpenAI Structured Outputs: https://developers.openai.com/api/docs/guides/structured-outputs
- OpenAI Responses API migration notes: https://developers.openai.com/api/docs/guides/migrate-to-responses

## Entity Relationships

The useful operational graph for Meta ads analytics is:

```text
app
business
  -> ad_account
      -> campaign
          -> ad_set
              -> ad
                  -> creative
      -> insights
```

Insights can be requested at multiple levels:

- `account`: macro health, spend pace, broad efficiency.
- `campaign`: objective-level and budget allocation decisions.
- `adset`: audience, placement, schedule, and delivery diagnostics.
- `ad`: creative/message-level performance diagnostics.

The backend stores every fetched or uploaded payload as a raw record before
deriving KPIs. This protects the project from premature modeling choices and
allows re-analysis when new relationships or fields become useful.

## Raw Data Strategy

Raw records are append-only snapshots with:

- source: `meta_marketing_api` or `manual_upload`
- entity type: app, business, ad account, campaign, ad set, ad, creative, insight, or custom
- provider record id when available
- account id and parent id when available
- observed timestamp/date window when available
- Graph API version when available
- untouched JSON payload
- stable payload hash for deduplication and debugging

The API exposes raw ingestion separately from Meta sync so exports from Meta Ads
Manager, CSV-to-JSON pipelines, or future connectors can be analyzed without
requiring a live Meta token.

## Deterministic Metrics

Before using AI, the backend computes deterministic KPI rows from raw insights:

- spend
- impressions
- reach
- clicks
- inline link clicks
- conversions from `actions`
- conversion value from `action_values`
- CTR
- CPC
- CPM
- CPA
- ROAS
- Deterministic patterns: spend concentration, wasted spend, efficiency opportunities, cost/engagement outliers, trend movements, and data quality gaps.

The model receives only this compact KPI evidence plus selected metadata by
default. Raw record ids remain attached to the response for audit and deeper
follow-up analysis.

## AI Output Contract

The marketing AI layer returns a typed report:

- executive summary
- health score
- key findings with evidence and confidence
- prioritized actions
- data quality notes
- suggested raw-data follow-up queries

The model must not invent missing fields. When source data is insufficient, the
report should say which additional Meta dimensions, breakdowns, or conversion
events are needed.

Before the AI report is generated, the backend runs deterministic pattern
detection over KPI rows. The model receives those patterns as evidence, but the
patterns remain available through a separate endpoint so analytics workflows can
inspect them without model interpretation.

## Implementation Stages

1. Add environment-driven Meta/OpenAI marketing configuration.
2. Add Meta discovery for app and accessible ad account metadata.
3. Add raw record persistence and repository methods.
4. Add Meta Graph client and sync service.
5. Add deterministic KPI builder.
6. Add structured OpenAI marketing analysis service.
7. Add async insights job contracts for large report pulls.
8. Add API routes and Swagger descriptions.
9. Add tests with fakes; tests must never call Meta or OpenAI.
