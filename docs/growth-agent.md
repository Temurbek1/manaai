# Growth & Conversion Agent

`growth-agent` is the loaded MANA OPERATION AI Growth domain agent. It is the governance and
product-level owner; capabilities are independently configured and scheduled executable units.

## Loaded capabilities

| Capability | Current implementation | Write boundary |
| --- | --- | --- |
| `growth.advertising` | Existing deterministic advertising collection, analysis, recommendations, reports, and action lifecycle. Meta can be queried through the typed ads port. | `fake_meta` supports approval-gated writes. Live Meta is permanently `live_read_only` in this milestone. |
| `growth.funnel.analyze` | Deterministic acquisition-to-paid funnel calculation over typed Product Analytics, Billing, and Attribution facts, including freshness, completeness, and evidence references. Defaults to shadow mode. | Optional sandbox mode can create an approval-required experiment draft through the in-memory fake experiment adapter. It cannot contact customers or mutate billing. |

Conversion, offers, upsell, more acquisition channels, and real source adapters are future Growth
capabilities or extensions. Their names in product documents do not imply that they are implemented.

## Runtime map

- `application/capabilities.py`: typed capability handler protocol and registry.
- `application/growth/agent.py`: `growth-agent` composition and capability dispatch.
- `application/growth/funnel.py`: funnel configuration, collection, normalization, calculations,
  evidence, findings, hypotheses, sandbox proposal, report, and outcome persistence.
- `application/marketing/agent.py`: advertising capability handler retained from the proven
  Marketing implementation.
- `application/action_executors.py` and `action_policies.py`: extensible action-family registries.
- `domain/growth.py`: provider-neutral Growth facts and experiment contracts.
- `infrastructure/growth/fake.py`: hermetic fake sources and experiment sandbox.

The operational database scopes configurations, schedules, runs, audit, and outcomes with both
`agent_id` and `capability_key`. A capability has its own run lock and kill switch. Configuration
changes rebuild schedules only for that capability.

## Marketing compatibility

`marketing-agent` is an alias, not a second loaded agent. Requests through it select
`growth-agent` and default to `growth.advertising`; new rows therefore use `growth-agent`. The old
agent row and historical runs remain untouched for referential integrity. History queries for
either identifier merge current Growth rows with legacy marketing rows. Only Growth schedule IDs
are bootstrapped, preventing a double scheduler cutover.

The browser route `/marketing` redirects to `/growth`. The API route
`/api/v1/admin/operation/marketing/overview` remains a compatibility projection of advertising.

## Funnel authority and action safety

Funnel counts and ratios are calculated in Python from normalized facts. An LLM is not used for an
authoritative metric or write payload; future model use is limited to explanations and hypotheses.
Each stored snapshot carries evidence references, source periods, collection times, freshness,
completeness, and availability.

The sandbox experiment lifecycle requires deterministic policy evaluation and human approval. It
re-reads fresh experiment state, validates a state hash, dispatches once with an idempotency key,
verifies by reading again, and persists audit plus a separate business-outcome evaluation. An
ambiguous provider response is reconciled by state read and is never blindly retried.

No real customer, experiment, offer, subscription, billing, or financial write is enabled by this
implementation.

## Extension checklist

When adding a Growth capability:

1. Add typed domain facts/configuration/output and explicit source ports.
2. Implement one `CapabilityHandler` and register it in `app/main.py`.
3. Give it stable capability and schedule keys; never reuse another capability's configuration.
4. Keep authoritative calculations deterministic and persist evidence lineage.
5. Register a domain-specific action executor and policy only when a real action is required.
6. Start external integrations in read-only/shadow mode and provide a hermetic fake/sandbox.
7. Add API/UI coverage, migration changes where needed, lifecycle tests, and update the capability
   matrix without describing fake behavior as production readiness.

The first Retention & Loyalty engagement/reporting foundation is now loaded. Delivery continues
with Retention risk/actions, then **Operations Orchestrator → Technical Reliability**.
