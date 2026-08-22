# MANA OPERATION AI agent model

## Status and authority

This document is the canonical product and architecture direction for MANA OPERATION AI. It
interprets `MANA OPERATION AI (1).pdf` as four durable operational domains rather than one agent
per report row, schedule, integration, or action. Future implementation work must preserve this
model unless an explicit architecture decision replaces it.

This document separates the target design from the current implementation:

- **Current:** only `marketing-agent` is implemented. Its complete write lifecycle is executable
  against `fake_meta`; the live Meta adapter is intentionally read-only.
- **Target:** four action-capable agents operate through typed ports, policies, approvals,
  idempotent executors, verification, and outcome measurement.

The purpose of the platform is to let the application's principal administrators analyze and
improve the external environment and internal state of MANA through one governed operational
control plane.

## The four agents

An agent is a durable owner of a business outcome, data authority, policy boundary, and action
surface. A capability, connector, report, scheduled job, or action kind is not a separate agent.

| Agent | Outcome ownership | Capabilities inside the agent | Representative actions |
| --- | --- | --- | --- |
| **Operations Orchestrator** (`operations-orchestrator`) | Translate administrative goals into measured cross-domain outcomes | Executive/admin analytics, goal intake, planning, forecasting, root-cause correlation, task delegation, dependency tracking, outcome evaluation, daily/weekly reporting | Create/pause/cancel agent tasks, request analysis, escalate incidents, request approval, notify administrators; delegate infrastructure changes to the owning domain agent |
| **Growth & Conversion Agent** (`growth-agent`) | Acquire qualified users and convert them into paying customers within CAC, budget, consent, and product-safety constraints | Advertising, channel/SMM analysis, acquisition, funnel analysis, conversion, upsell, offer selection, experimentation, growth reporting | Adjust approved ad budgets/status/audiences, create approved experiments, publish approved offers or campaign changes through scoped executors |
| **Retention & Loyalty Agent** (`retention-agent`) | Retain and grow existing customer relationships without abusive offers or contact | Churn prediction, risk zones, subscription lifecycle, engagement, win-back, loyalty, referral, abuse prevention, retention reporting | Send approved messages/offers, grant approved benefits, propose pause/discount/win-back flows, create referral rewards, suppress unsafe or excessive contact |
| **Technical Reliability Agent** (`technical-agent`) | Keep the application reliable, performant, diagnosable, and safe to operate | Crash/error clustering, latency, release regression, device/OS analysis, app-store reviews, support correlation, incident prioritization, technical reporting | Create/update approved issues and incidents, notify responders, propose rollback or release blocks; production deployment/rollback remains behind a dedicated high-risk policy |

The following names from source material are capabilities, not top-level agents:

- `Admin Analysis` belongs to Operations Orchestrator.
- `Advertising`, `SMM`, `Conversion`, and `Upsell` belong to Growth & Conversion.
- `Retention`, `Win-back`, `Referral`, and `Loyalty` belong to Retention & Loyalty.
- `Technical Analysis`, review clustering, and support-issue correlation belong to Technical
  Reliability.
- `Child Analysis` is not an operational agent. Child/family inference remains in the separate
  MANA AI bounded context; operation code may consume only explicitly authorized, minimized, and
  aggregated operational signals.

Do not create separate top-level agents for these capability names merely because they appear as
rows in a report or require different schedules.

## Why four, not one or twelve

One omnipotent agent would mix credentials, privacy boundaries, failure modes, and policies. Ten or
more micro-agents would duplicate data access, configuration, reports, and lifecycle code while
making cross-capability goals harder to manage. Four agents preserve the boundaries that actually
change independently:

- business outcome and accountable owner;
- source data and privacy classification;
- external integrations and credentials;
- action and approval policy;
- scheduling/event cadence;
- kill switch and failure isolation.

Multiple capabilities within one agent can run independently. The executable unit is a persisted,
typed capability task, while the agent remains the governance and product-level unit presented to
administrators.

## Administrative experience

Operations Orchestrator is the primary entry point for principal administrators. A request such
as "increase paid conversion from 8% to 11% without raising CAC above $6" becomes a durable goal,
not an ephemeral chat instruction.

The control flow is:

```text
administrator request
  -> persisted goal with metric, baseline, target, deadline, and constraints
  -> orchestrator proposes a typed, dependency-aware plan
  -> policy decides which tasks may start and which need approval
  -> domain agents execute capability tasks
  -> findings, recommendations, actions, and evidence are persisted
  -> action policies gate external or internal changes
  -> executors verify provider/application state
  -> outcome evaluation compares the result with the original goal
  -> orchestrator continues, replans, escalates, or closes the goal
```

The orchestrator has logical visibility across authorized operational facts, but must not receive
unrestricted provider credentials or emit arbitrary provider payloads. Infrastructure mutations
are delegated to the agent that owns the domain policy and typed executor.

## Capability and task model

The existing `OperationalAgent` registry remains the registry of the four domain owners. Each
agent should compose a registry of typed capability handlers rather than a growing `if job_type`
dispatcher.

Target contracts include:

- `CapabilityDefinition`: namespaced key, input/output schema, risk, required integrations,
  supported triggers, and owner agent;
- `AgentTask`: capability key, goal ID, evidence references, expected outcome, constraints,
  deadline, idempotency key, dependency IDs, and status;
- `CapabilityConfiguration`: independently versioned settings and schedules for one capability;
- `EvidenceRef`: source, subject scope, period, freshness, completeness, checksum, and privacy
  classification;
- `OutcomeEvaluation`: baseline, observed value, attribution limits, target progress, and decision
  to finish, continue, replan, or escalate.

Use namespaced capability keys, for example:

```text
orchestrator.admin.daily_report
orchestrator.goal.evaluate
growth.advertising.analyze
growth.advertising.optimize
growth.funnel.analyze
growth.offer.propose
growth.experiment.create
retention.churn.classify
retention.offer.propose
retention.referral.propose
technical.crash.analyze
technical.release.evaluate
technical.incident.create
```

Configurations and schedules must be versioned per capability. Adding conversion configuration
must not create a new version of unrelated advertising thresholds. Runs must record both
`agent_id` and `capability_key`. Support global, per-agent, per-capability, and per-resource kill
switches/leases where the risk justifies them.

## Shared operational data plane

Agents must not create private, conflicting copies of company truth. Provider-specific raw data
stays append-only at adapter boundaries; normalized facts and governed read models form the shared
operational data plane:

```text
provider/product sources
  -> immutable ingestion records
  -> normalized domain facts with lineage
  -> deterministic metrics and feature views
  -> scoped evidence references
  -> agent findings and decisions
```

Required source ports are introduced only with a concrete capability. Expected categories include
product analytics, billing/subscriptions, advertising platforms, experimentation, messaging,
support, app stores, observability, releases, and issue tracking.

The database is authoritative for goals, tasks, lifecycle state, evidence metadata, approvals,
executions, verification, outcomes, and audit. Vector search may assist retrieval of narrative
documents, but it is never authoritative memory for policy, metrics, action state, or task status.

Default to aggregate or pseudonymized facts. User-level access must be explicit, purpose-bound,
audited, and minimized. Raw child messages, precise location history, or other MANA AI evidence
must not cross into MANA OPERATION AI merely to improve business analytics.

## Agents must perform actions

Analysis-only agents do not satisfy the product goal. Every domain agent must eventually support
safe actions appropriate to its authority. An action is complete only when the platform can prove
the full lifecycle:

```text
evidence
  -> typed recommendation
  -> typed action intent
  -> deterministic policy evaluation
  -> required human approval
  -> fresh target-state/precondition read
  -> single idempotent dispatch
  -> persisted provider/application result
  -> verification read
  -> outcome measurement
  -> immutable audit trail
```

Action requirements:

1. Never allow an LLM to calculate authoritative financial metrics or construct an arbitrary
   provider write payload.
2. Define domain-specific discriminated action contracts. Do not expand one marketing-specific
   enum into an unbounded cross-domain enum with untyped JSON parameters.
3. Resolve actions through an `ActionExecutorRegistry`. An executor owns prepare/read, dispatch,
   verification, idempotency, uncertainty reconciliation, and sanitized error translation for one
   action family.
4. Re-evaluate active configuration, current policy, kill switches, limits, approval validity, and
   fresh target state immediately before dispatch.
5. Treat a lost/ambiguous write response as `outcome_uncertain`; reconcile by reading state and
   never blindly repeat the write.
6. Record expected effect and measurable success criteria before approval. Verification of the
   changed field is necessary but not the same as proof of business impact.
7. Start every new real integration in read-only/shadow mode, then approval-only execution, and
   consider bounded automation only after outcome and incident evidence justify it.

Operations Orchestrator performs orchestration actions directly (task/goal state, escalation, and
notification) but delegates advertising, billing, messaging, experimentation, issue-tracker, and
deployment actions to their owning domain agents.

## Action risk model

Policies are capability and action specific. A practical default classification is:

| Tier | Examples | Default governance |
| --- | --- | --- |
| Read | Collect metrics, classify crash clusters, calculate churn risk | Automatic with data-access audit |
| Propose | Create a recommendation, experiment draft, offer draft, or incident draft | Automatic persistence; no external mutation |
| Reversible write | Pause an ad, create an issue, update a bounded experiment allocation | Human approval until evidence supports a narrower policy |
| Financial/customer write | Increase budget, grant discount, send an offer, change subscription state | Explicit approval, rate/value limits, contact consent, verification |
| High-impact write | Broad customer campaign, large budget shift, production rollback/deployment | Separate policy and normally two-person or out-of-band operational approval |

Self-approval remains forbidden. Bulk approval is opt-in per homogeneous action type, never a
generic platform feature. Each executor needs a fake/sandbox implementation used by automated
tests; tests must not call live write APIs.

## Current runtime: keep and evolve

The following implemented foundation remains valuable:

- agent registry and status;
- persisted configurations and schedules;
- run and action state machines;
- findings, recommendations, reports, and audit;
- policy, approval, idempotency, provider-object locking, execution, verification, and recovery;
- fake provider lifecycle;
- admin authentication, RBAC, kill switches, API, UI, worker, PostgreSQL, and migrations.

Required evolution:

1. Add persisted goals, plans, tasks, dependencies, and outcome evaluations.
2. Add `capability_key` to task/run/configuration/schedule/audit query models.
3. Add a capability-handler registry inside each domain agent.
4. Generalize the advertising-specific action lifecycle behind typed action executor and policy
   registries while preserving current safety behavior.
5. Introduce source ports and normalized facts capability by capability; do not create a broad
   integration abstraction without a real consumer.
6. Change the admin information architecture to Command Center, Growth, Retention, Reliability,
   Approvals, Runs/Audit, and Integrations rather than one navigation entry per capability.

## Marketing Agent migration

Do not discard the working Marketing Agent. Evolve it into the advertising capability of Growth &
Conversion:

1. Extract collection, analytics, recommendations, reporting, and action mapping into a
   `growth.advertising` capability handler without changing behavior.
2. Introduce `growth-agent` and register the extracted handler under it.
3. Keep `marketing-agent` temporarily as a compatibility implementation for historical API/data
   access; do not run both sets of schedules.
4. Preserve historical runs under `marketing-agent`; create new runs under `growth-agent` after a
   controlled cutover.
5. Add funnel, offer, conversion, upsell, and experimentation capabilities independently.
6. Retire compatibility registration only after pending proposals/runs are settled and all callers
   use `growth-agent`.

Live Meta remains read-only until a separately approved product decision adds a real Meta action
adapter, permission model, sandbox/canary evidence, incident procedure, and explicit production
policy. Target action capability must not be documented as current production write availability.

## Delivery sequence

1. Restore all repository release gates and keep the current Marketing Agent stable.
2. Add capability/task/configuration contracts and generic typed executor registration.
3. Cut Marketing Agent over to `growth.advertising` with compatibility preserved.
4. Add Growth funnel/conversion/offer capabilities in read-only and shadow modes.
5. Add Retention classification/reporting, then governed offer/referral actions.
6. Add Technical analysis/reporting, then governed issue/incident actions.
7. Add read-only Operations Orchestrator over stable facts and agent outputs.
8. Add persisted planning/delegation, then governed cross-agent goal loops.
9. Permit narrowly bounded real actions only after integration-specific readiness evidence.

## Completion criteria for a capability

A capability is not complete merely because it produces a model response. It must have:

- a typed request/task and output contract;
- explicit source authority, privacy classification, and freshness/completeness semantics;
- deterministic metrics and safety checks where applicable;
- persisted evidence lineage, findings, recommendations, and reports;
- a versioned configuration and trigger/schedule policy;
- typed action contracts when the capability is expected to act;
- policy, approval, idempotency, execution, verification, uncertainty recovery, and audit coverage;
- a fake/sandbox adapter and hermetic tests for every write path;
- health, latency, failure, and outcome observability;
- documentation that clearly distinguishes current behavior from target behavior.
