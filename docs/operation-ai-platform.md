# MANA OPERATION AI platform

## Generic contracts

The domain defines `AgentDefinition`, `AgentRegistry`, `CapabilityDefinition`, `AgentStatus`, `AgentRun`,
`AgentRunResult`, `AgentConfiguration`, `AgentSchedule`, `Integration`, `IntegrationHealth`,
`DataSnapshot`, `Analysis`, `Finding`, `Recommendation`, `ActionProposal`, `ActionPolicy`,
`ApprovalRequest`, `ApprovalDecision`, `ActionExecution`, `ActionVerification`, `AgentReport`, and
`AuditEvent`, and `OutcomeEvaluation`.

`AgentRegistry` dispatches implementations by registration. A domain agent composes typed
`CapabilityHandler` implementations through `CapabilityRegistry`; each handler supplies its own
configuration schema/default, schedules, health checks, execution, and deferred finalization.
Configuration versions, schedules, run locks, and kill switches are capability-scoped.

The target registry contains four domain agents: Operations Orchestrator, Growth & Conversion,
Retention & Loyalty, and Technical Reliability. Their executable units are independently typed and
configured capability tasks. See `docs/operation-agent-model.md`. The current registry contains
`growth-agent`, with loaded `growth.advertising` and `growth.funnel.analyze` handlers, and
`retention-agent`, with loaded read-only `retention.engagement.analyze`. `marketing-agent` is a
compatibility alias rather than a second implementation. Operations Orchestrator, Technical
Reliability, unloaded Growth capabilities, and Retention actions must not be represented as
implemented.

## Lifecycle

Growth advertising and the funnel experiment sandbox demonstrate the reusable lifecycle:

`collect -> normalize -> analyze -> propose -> policy_check -> approval -> execute -> verify -> report`

All records use a run/correlation ID. A database lock prevents overlapping runs for one capability.
Scheduled retry attempts reuse one run idempotency key and increment `retry_count` after a failed
run. Actions have a second deterministic idempotency key based on target, typed change, and provider
state. Cooldowns and current-state hashes protect repeated scaling.

## Scheduler

`InProcessScheduler` is the persisted polling engine used by the local API when explicitly enabled
and by the standalone production worker:

- persisted cron expressions and next-run timestamps;
- six-hour Growth advertising and Retention engagement analysis, nightly advertising report, and
  twice-daily Growth funnel analysis;
- collection is part of each analysis/report job, so every analysis uses a saved current snapshot;
- hourly interrupted-action reconciliation;
- daily snapshot/lock retention cleanup;
- approval expiration each tick;
- database-backed run and occurrence leases, three retry attempts, timeout, and graceful shutdown.

Production keeps scheduling disabled in API replicas and runs the engine in a dedicated worker.
Transactional occurrence claims, run idempotency, and provider-object leases make multiple workers
duplicate-safe, including lease recovery after a dead worker. PostgreSQL is required for production;
SQLite remains a local/single-process option. A durable queue can replace polling later without
changing agent contracts.

## Adding the next capability

1. Place the capability under one of the four domain agents; do not create a top-level agent merely
   because it has a different integration, action, report, or schedule.
2. Add domain-specific typed task, configuration, evidence, output, and action contracts without
   weakening generic runtime contracts.
3. Implement a capability handler against typed repository/source/action ports and register it
   inside the owning agent.
4. Version configuration and schedules at capability granularity so unrelated capabilities do not
   change together.
5. Add migrations only for genuinely queryable state, not for every provider or domain field.
6. If the capability acts, implement policy, approval, idempotent dispatch, fresh-state checks,
   verification, uncertainty reconciliation, outcome measurement, audit, and a fake executor.
7. Add an admin-specific view only where the generic domain-agent view is insufficient. It already
   participates in runs, findings, reports, approvals, audit, and controls.

Adding a fifth top-level agent requires an explicit architecture decision demonstrating a new
outcome owner, data/privacy authority, credential/policy boundary, and failure-isolation need.
