# MANA OPERATION AI platform

## Generic contracts

The domain defines `AgentDefinition`, `AgentRegistry`, `AgentCapability`, `AgentStatus`, `AgentRun`,
`AgentRunResult`, `AgentConfiguration`, `AgentSchedule`, `Integration`, `IntegrationHealth`,
`DataSnapshot`, `Analysis`, `Finding`, `Recommendation`, `ActionProposal`, `ActionPolicy`,
`ApprovalRequest`, `ApprovalDecision`, `ActionExecution`, `ActionVerification`, `AgentReport`, and
`AuditEvent`.

`AgentRegistry` dispatches implementations by registration. Each implementation supplies its
definition, typed configuration schema/default, schedules, health checks, execution, and deferred
finalization. Configuration versions and schedules are persisted. Changing the Marketing Agent
schedule fields recalculates the persisted next occurrence in the configured timezone.

## Lifecycle

The Marketing Agent demonstrates the full reusable lifecycle:

`collect -> normalize -> analyze -> propose -> policy_check -> approval -> execute -> verify -> report`

All records use a run/correlation ID. A database lock prevents overlapping runs for one agent.
Scheduled retry attempts reuse one run idempotency key and increment `retry_count` after a failed
run. Actions have a second deterministic idempotency key based on target, typed change, and provider
state. Cooldowns and current-state hashes protect repeated scaling.

## Scheduler

`InProcessScheduler` is the persisted polling engine used by the local API when explicitly enabled
and by the standalone production worker:

- persisted cron expressions and next-run timestamps;
- six-hour Marketing Agent analysis and nightly report;
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

## Adding the next agent

1. Add domain-specific configuration and evidence models without changing generic contracts.
2. Implement `OperationalAgent` against repository/integration protocols.
3. Register the implementation in `app/main.py` (later via a plugin composition module).
4. Add migrations only for genuinely queryable new data, not for every domain field.
5. Add schedules, policy actions, tests, and an admin-specific view only where generic views are
   insufficient. It will already appear in registry, dashboard, runs, reports, and controls.
