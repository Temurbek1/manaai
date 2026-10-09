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

## Verified deployment and diagnostics

Deployed on 2026-10-09 to [the administration site](https://ai-frontend.360rec.uz/)
and [the API](https://ai.360rec.uz/). The site still uses its existing sign-in;
no SSH access, existing identity/role or source documents were changed.

### Actual versions and scope

- Operational API/Goals sidecar and the existing scheduler worker:
  `2ea7b9ab0737180f2ad708ffc4d17755e5f2f39f`, image `mana-ai-operation:2ea7b9a`.
- Admin UI: `a871ddfed4d28fb6f30c2337223d513baf4a8444`,
  image `mana-ai-admin:a871ddf`. The later backend-only greeting refinement did
  not require recreating the UI. A subsequent documentation-only commit is not
  a different running application image.
- Main API/audio stays on `e73c10a`; its container ID and start time and those
  of PostgreSQL were unchanged. Audio readiness returned `ready`; no new real
  child recording was sent for this operational release check.
- Additive PostgreSQL schema at `b64e9c2f703d`. Backup was verified with
  `pg_restore --list`, not a claimed production restore drill. Historical data,
  chats, Goals, unknown cost reservations and prior archives were retained.
- Public `/api/v1/admin/operation/` now routes to the operational sidecar;
  auth/audio/other API paths keep their existing target. Exactly one operational
  scheduler and one Goals worker, in separate process roles.
- Compact model/reasoning controls and Goals are enabled. Aggregate token
  ceilings are disabled in the actual current day/month SQL policies as well as
  configuration; per-call/dollar/source/approval guards remain active.

Commit history uses genuine staged commits: dependency/security fixes; durable
Goals, cost control and first-party adapters; conversational UI/model controls;
documentation; then a small evidence-led chat prompt refinement. No backdating,
published history rewrite or fabricated historical development sequence.

### Quality gates

Full `make verify` passed after the final code change: 674 backend tests passed,
6 isolated PostgreSQL cases skipped in that command, 2 opt-in live cases excluded;
93 UI tests passed across 19 suites. Ruff, mypy, ESLint, TypeScript, production
build and npm audit passed (zero npm advisories). Isolated PostgreSQL migration
round-trip/schema check and all 6 PostgreSQL cases separately passed. Schema
sync, secret scan and runtime image dependency audit passed.

Standalone/bundle smoke and fake-provider browser checks covered private topics,
Goals controls, report scope/freshness, permissions/CSRF, logout, 320 px mobile
layout and WCAG-tagged axe checks. This is not a claim that the user's real
production browser/OTP session was automated.

On production, authenticated operational routes returned 200 and unauthenticated
routes 401. Repeating six saved-data/availability/Goal GETs three times produced
zero new cost reservations and zero agent runs. After replacement, the SQL Goal
and its three checkpoints remained readable without another model/source call.
The old image's pure `ChatTurn` contract successfully parsed the latest eight
persisted chat payloads; new metadata is separate and old provenance remains
unknown. This proves payload read compatibility, not every old route or a
whole-stack rollback.

### Bounded live results

| Diagnostic | Verified result |
| --- | --- |
| Auto greeting → Mini/low | First response was unnecessarily verbose. After the prompt refinement, one new check returned `Привет! Чем помочь?`, no plan/card; 7.97 seconds. |
| Regional-orders question → Sol/medium | 13.24 seconds; explicitly missing payment/order evidence, no fabricated city ranking, conditional traffic/checkout/payment/offer tests with a measurement plan. |
| Synthetic 120 parents / 300 children → manual Sol/high | 11.48 seconds; arithmetic is 40%, **not** retention; separate populations and a useful parent-cohort measurement plan. |
| Technical deployment question → manual Astra/low | 6.99 seconds; honestly describes missing operational handlers, no claimed server mutation. |
| Durable regional-sales Goal → Sol/medium | Plan → investigate → independent review; three saved steps, then `waiting` for payment-confirmed MANA order aggregates. No source read or external action. |
| One explicitly confirmed MANA Parent summary | Two HTTP requests (login + one page); API total 208,985, 10 parents read, only minimized counters saved, no model call/pagination/retry. |

These are a few practical acceptance checks, not a statistical accuracy score,
proof of regional sales improvement or certification of unimplemented actions.
The original paid helper finished its four chat checks, then was refused with
403 for an unregistered arbitrary Goal owner. A separate supported trusted-key
check using an **existing active registered administrator** exercised Goals;
no account, session or role was forged/changed. Normal session authentication
and CSRF remain enforced for browser users.

The owner's private Goal `cf2f5e6c-f7eb-4878-b385-314b0ad81d26` is in the Growth
topic `Проверка Goals: география продаж`. It preserves useful partial analysis
and a focused missing-data request. Waiting is deliberate: it has neither a
confirmed regional paid-order source nor permission for fresh collection.
Do not advertise this as a completed analysis of actual regional sales.

**Measured release diagnostics:** 8 settled OpenAI calls, 2 settled Manakids
HTTP requests; estimated model charges from recorded usage/rate cards
**$0.101212**. Zero unknown holds, zero Firebase/GA4 requests, zero source-data
mutations, zero live financial/advertising writes or customer-contact actions.
This is local metered usage, not a provider billing invoice or a future forecast.
Historical paid QA charges are separate and were not reset or folded into this
release's measurement.

### Production guards and remaining limitations

The MANA-only Parent source is explicit and manual-only:
`MANAKIDS_PARENT_SAMPLE_LIMIT=10`, zero retries, no next-page requests, a shared
six-hour cooldown recorded before I/O and no default schedule. Its real sample
is profile/tariff/link evidence, not payment, activity, inactivity or churn.

Firestore prefix telemetry is disabled in the updated sidecar and scheduler;
public Firestore reads are disabled. Engagement's application binding remains
`unverified`, so no new broad GA4/Firestore collection was enabled. The untouched
legacy main API retains its previous telemetry configuration but has no scheduler;
public operational paths now use the guarded new sidecar. Do not reactivate its
old collector or restart audio as a routine operational release step.

Default newly created UI Goals may use up to 12 steps and $5; LLM admission
ceilings are $10/day and $300/month, not expected spend. Provider call, response
byte, data-read, owner/global chat, source freshness and approval limits remain.
Actual requests can finish much earlier or wait for missing evidence. Raising
an existing SQL period policy requires an explicit operator procedure that
preserves all usage and reservations.

Full Orchestrator/Technical execution and Retention contact/billing actions are
still unbuilt; existing advertising/experiment mutation testing uses fakes or
sandbox. Model selection never grants tools or permissions. For real regional
sales ranking, supply an owner-verified, minimized payment/order aggregate with
common period, payment definition, geography definition, deduplication/refunds,
coverage and unknown-geography group. Parent activity geography cannot replace it.

### Operator handoff

Current deployment definitions and split-version rollback guidance are recorded
on the server in `/etc/manaai/deploy/ACTIVE-RELEASE.md`. The operational API uses
`operation-release-a871ddf.yml`; the existing main Compose stack appends
`worker-admin-a871ddf.yml`. Filename suffixes identify the release cycle; actual
image tags are the revisions above. Never bring up the entire old stack blindly.

Protected backup/evidence: `/var/backups/mana-ai/goals-a871ddf/`. Database dump
SHA256: `32d98462b88ca20bd69f00decfef4fd35afd242b73892a41bbc8864d800a56c5`.
Main env/keys and prior images/configuration remain available. UI-only rollback
keeps the new backend/source guards and additive database history. No database
downgrade, chat/Goal deletion, SSH change, main audio restart or restoration of
historical expensive Firestore telemetry is part of the routine rollback.
