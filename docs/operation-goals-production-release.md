# Goals and reasoning release — 2026-10-09

## Authority and scope

The owner explicitly requested deploying the accumulated changes, an orderly
sequence of genuine commits, production agent checks, stronger reasoning and a
manual model picker. This supersedes the earlier cost-workstream's **no-deploy**
boundary; archived QA results and unknown cost holds are not rewritten.
No backdating, published-history rewrite, source-data mutation, credential removal,
SSH changes, arbitrary customer contact or live financial/advertising writes.

## Delivered interaction design

- Private rooms/topics remain under exactly four operational agents.
- Shared durable Goals: plan, investigation, independent review, pause/resume,
  steering, preserved evidence, restart recovery and separately confirmed reads.
- A compact model and reasoning picker in the single chat composer applies to
  ordinary messages and newly created Goals. A running Goal keeps its original
  inference choices; steering cannot silently switch its model or budget.
- `auto` uses GPT-5.4 Mini/low only for whole trivial greetings/thanks. Other
  conversation and Goals use GPT-6.1 Sol/medium. GPT-6 Astra is manual-only.
  Users may choose low/medium/high reasoning; no unsupported `none` for GPT-6.
- Standard-tier Responses structured outputs, no provider tools, `store=false`,
  zero SDK retries and matched deployment-owned rate cards. Reasoning tokens are
  already output tokens and must not be charged twice.
- Model choice changes inference quality, **not** permissions. Existing typed
  action policy, approval, idempotency, freshness and verification still apply.
  Full Orchestrator/Technical handlers and Retention contact/billing actions are
  not created by this release and must not be described as available.

Official model/effort guidance:
[Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[Mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini),
[Astra](https://developers.openai.com/api/docs/models/gpt-6-astra).

## Token limits versus source safeguards

`OPERATION_MODEL_SELECTION_ENABLED` exposes the supported catalog.
`OPERATION_AI_TOKEN_LIMITS_ENABLED=false` removes aggregate input/output token
admission ceilings for new budget periods. It does **not** remove per-call
context/output bounds, dollar accounting/ceilings, hourly admission, unknown holds,
source six-hour gates, product bindings, auth refusal gates or read budgets.
SQL policies only tighten within an existing period: an operator must explicitly
raise an already-created period's limits, never delete usage or reservations.

`OPERATION_CHAT_MAX_OUTPUT_TOKENS` is independent of the audio provider's limit.
Goal step, context, output and dollar limits remain explicit. There is no
unbounded loop; waiting for missing order/payment evidence is not successful
completion of a sales investigation. No hidden retry of a timed-out source read.

## Data semantics and the regional-orders acceptance example

Owner clarification: MANA in-app activity/button clicks describe **parents**.
Backend child inventories remain a separate population. Never divide active
parents by the number of children. 360REC remains a request-based independent
service; its rooms cannot consume MANA reports.

The saved minimized engagement narrative now includes window counts, sessions,
event counts and activity dimensions so the model can actually use these facts.
Report provenance, observation time and completeness restrictions are preserved.

Cities/regions of active users are **not** cities/regions of orders. Profile
addresses and non-free tariffs are not confirmed sales. The regional-orders
question must either use actual order/payment evidence or explicitly report the
missing source and give conditional hypotheses, a prioritized measurement plan
and an actionable next step. It must not fabricate a highest/lowest-sales region.

## Production release procedure

1. Inspect running versions/configuration without printing secrets. Save exact
   container IDs/start times, revision labels, schema revision and source settings.
2. Pass `make verify`, schema sync, secret scan, isolated PostgreSQL migration and
   concurrency audit, standalone and fake-provider browser checks.
3. Commit coherent dependency, backend, interface and documentation increments
   with real timestamps; push the existing branch without rewriting history.
4. Build immutable revision-labelled backend/admin images from clean Git archives.
   Keep credentials out of source/images. Retain old images and configuration.
5. Back up PostgreSQL and verify the dump. Apply only additive migrations.
   New chat metadata uses a nullable separate column; prior persisted JSON keeps
   the old release's field set, unknown provenance and supported card kinds.
   Application-only rollback must not downgrade the database or erase Goals.
6. Update the operational API sidecar and worker/admin in their proper roles.
   Only one Goals worker and one operational scheduler. Preserve the independent
   main API/audio process; route operational endpoints to the updated sidecar.
7. Verify public and internal authenticated/unauthenticated routes, Goals/model
   selection, source-free page reads, actual bounded agent quality and rollback.
   Use isolated diagnostic topics, never approve a live customer/provider mutation.

This file is a procedure, not evidence of an already-completed deployment.
Actual revisions, checks, paid usage and limitations must be recorded after rollout.
