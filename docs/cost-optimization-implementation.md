# Operational cost optimization

## Authority and release boundary

**2026-10-09 scope update:** the owner subsequently authorized the accumulated
production release and manual stronger-model selection. The paragraphs below
describe the earlier cost goal's authority/history, not a veto on the new release.
See [current release procedure](operation-goals-production-release.md). Source
mutation, SSH/key changes and unrestricted paid reads remain prohibited.

The active goal covers the shared operational data plane, deterministic metrics,
durable budgets, bounded AI context, correctness tests, a reproducible forecast,
and documented source limitations. It does **not** authorize production deployment,
new schedules, unapproved paid live tests, Firebase writes/deletes, IAM changes, SSH changes,
or changes to the independent child-audio moderation service.

Work started locally on 2026-10-07 (Asia/Samarkand). Existing uncommitted Parent API,
risk, documentation, and UI/API-schema changes are preserved. No live product-source
requests have been made for this goal. One synthetic OpenAI QA batch was
separately approved and completed on 2026-10-08: 16 calls, $0.010689 by usage/rate
card; its failed quality review is linked below. On 2026-10-08 the user approved
the corrected follow-up and gave standing permission for checks costing **less
than $0.50** without another question. Ten bounded follow-up batches completed:
160 calls, $0.196035; the first eleven synthetic batches total 176 calls and $0.206724.
The required-reply comparison accounts for 16 calls and $0.025220 and was
rejected for semantic regressions. Only that candidate prompt was restored to the
preceding exact hash; deterministic UI safeguards remain. Post-fix mini now
selects the engagement card and preserves observation/creation order. Mini low
better obeys user constraints than mini none on this regression set, but quality
is not accepted: representative coverage and owner acceptance are missing, and
answer usability remains imperfect. Post-fix replies have empty plans and fuller
calculations, but stale/admission qualifications remain missing. This set also fails its
preregistered gate: mini low has 6/8 functional passes rather than 7/8 and both
complete positive controls. Neither working model nor reasoning has
been switched. This
permission does not supply source-owner
mappings or authorize production, product-source reads or deployment.
The earlier $5 one-shot Firestore approval
does not authorize a new scan or model evaluation.
The twelfth diagnostic, GPT-5.4/low, stopped on its first `APITimeoutError` after
45 seconds: seven cases not sent, no retry. At that checkpoint: **177 attempts**,
**176 settled/$0.206724 known**, **1 unknown/$0.050128 held**. Known plus held is
**$0.256852**, not confirmed spending/invoice. No full-profile quality was obtained.
The thirteenth [reviewed Sol diagnostic](operation-chat-sol-qa-plan.md), a different
model-selection scope rather than an old-request retry, completed 8/8 for
**$0.032552**. All thirteen ledgers now total **185 attempts, 184 settled/$0.239276
known, 1 previous unknown/$0.050128 held**; known plus held **$0.289404** is not an
invoice. Sol/low reaches 7/8 and utility 15/16 without unambiguous critical errors,
but its Parent admission qualifications are incomplete: both full controls fail
the combined gate. Working model/effort/prompt are unchanged; no further party
or production/source activation followed. The next local checkpoint adds typed,
server-owned read conditions independently of model prose, without a paid rerun
or regrading the Sol score. Conditions are derived from current policy, not
persisted as a read grant; source/role checks still refuse unsupported requests.
The subsequent [recorded delivery replay](operation-chat-delivery-replay-results.md)
adds no paid calls: known Sol replies pass8/8 with the current server/UI contract,
while their original raw-model7/8 score remains unchanged. It does not accept a
future model or replace owner review. The next PostgreSQL safety checkpoint
revalidates actual database concurrency/migration behaviour without external data.
Latest full verification is **617 backend/80 UI**, plus **5 isolated PostgreSQL tests**
run separately, and zero npm audit findings; details are recorded below.

## Current implementation checkpoint

Implemented:

- `ResourceUsage`, `CostLimits`, `CostAttribution`, and an explicit `LlmRateCard`.
- One durable UTC-day/calendar-month ledger shared by API/worker connections.
  Admission reserves before I/O, checks both periods atomically, and records
  product/source/agent/capability without raw provider or conversation content.
- Known usage can reconcile a reservation exactly once. Unknown charges remain
  reserved after cancellation, timeout, or process loss. Observed overruns are
  recorded rather than clipped to the estimate.
- Persisted period policies only tighten during a rolling deployment: a stale
  worker cannot restore a higher limit. Raising a current-period limit requires
  an explicit operator procedure; changing environment values alone cannot do it.
- The operational conversation gateway is wired to this ledger in `app/main.py`.
  It makes one Responses call with zero SDK retries, `store=false`, and the
  standard tier. Model/rate-card mismatches are rejected before external I/O.
  Usage includes reasoning in output tokens; cached and cache-write input tokens
  are not double-counted. Unknown model/tier/usage keeps the reservation.
- Conversation context is byte-bounded. The current question and evidence
  identity/date/application scope are retained. Verbose older assistant text is
  excerpted before removing whole turns, preserving supplied user constraints
  when they fit. Excerpts, omitted turns and shortened report text are explicitly
  flagged. This is not durable memory outside the six-turn input window and no
  paid summarization step is introduced.
- Typed aggregate cache and source-wide six-hour admission store. Leases and
  cooldown survive restart, are isolated by application/source binding, and cannot
  be bypassed by another lookback or agent. A failed refresh can return the prior
  aggregate with its original collection time and a limitation. Unverified
  application ownership is refused. Stale publishers are fenced out.
- The live Manakids/GA4 engagement ports are now wrapped by the shared reader in
  `app/main.py`; a lookback change or a different consumer does not bypass its
  source-wide cooldown. Live backend authentication/admission finishes before
  other collection starts. Fake/demo workflows remain offline.
- `MeteredReadHttp` reserves every provider HTTP attempt before dispatch, with
  redirects disabled, identity encoding and a raw response-payload ceiling. Known successful
  Firestore document responses can reconcile reads, including the minimum one
  read for an empty query; malformed responses, errors and interrupted reads keep
  conservative document reservations. No raw payloads or credentials enter the
  ledger. Raw Firestore adapters accept this transport for controlled future use;
  they are not automatic sources in the candidate runtime.
- Chat budget exhaustion returns only the latest matching saved summary, with its
  original collection date, age and source limitations. It performs no new source
  or model call. Source metadata and the UI distinguish unknown dates from report
  creation dates; an expired `live` report is shown as stale. Replaying the same
  chat request returns the same persisted fallback. Another application's reports
  are not substituted when no matching summary exists.
- Each live source bundle needs explicitly approved application ownership and a
  binding revision. GA4 uses an explicit numeric `streamId` filter on all fourteen
  aggregate report shapes. One bundle serves one approved application; configuring
  a MANA bundle does not provide 360REC business data.
- Registry health polling performs no external reads through the shared ports.
  Source collection dates survive cache fallback and report rebuilding; overview
  age reflects the oldest source collection date, not the new run date. Mobile
  metrics from an unavailable source have typed unavailable values, not observed
  zeroes. Product-specific chats exclude unverified/mismatching saved reports.
- Existing action lifecycle now checks source evidence at proposal creation and
  again before action safety approval/execution. Stale, expired, mixed-application,
  unverified explicitly scoped and future-dated evidence is refused. Existing
  provider target-state validation remains independent and unchanged. No Retention
  action capability was introduced.
- `scripts/operation_cost_forecast.py` is a pure offline calculator with Decimal
  arithmetic and tested separate read/transfer/model/reserve line items. It does
  not load `.env`, start the app or call a provider. Proposed model rates are a
  capacity calculation, not a model switch or quality evaluation.
  Optional explicit ordinary rate-card JSON and workload counts can price a
  chat-only capacity separately from future scheduled AI; invalid inputs are
  controlled CLI errors. They do not read settings or enable an application model.
- Google service-account refresh now uses the Google library's public JWT signer
  and the same metered async HTTP transport, never the SDK's retrying refresh
  transport. The fixed Google token endpoint, explicit scopes, one attempt,
  response-byte ceiling, token validation and early expiry are enforced. Cached
  tokens stay in memory. Parallel callers share one successful refresh; rejection
  blocks further local attempts and the enclosing durable source gate blocks the
  source across restart. Transient/uncertain failures cool down; quota exhaustion
  does not invalidate credentials and can recover after budget rollover.
- The existing deterministic Retention engagement assessment is durably reused.
  Its identity covers the full minimized observation, product, periods, source
  lineage, limitations, complete typed task configuration/configuration version
  and explicit rules version. Delivery status/elapsed evidence age are not changed
  observations, but original expiry, stale status, scope and future dates are
  rechecked on every reuse. New audit identities refer to the current equivalent
  snapshot; `analysis_calculated_at` remains the original calculation time and
  `analysis_reused` is explicit in the report. Fake/unverified and stale results
  are not memoized. Concurrent CPU-only calculations cannot overwrite or extend
  a saved result; this memo is not a paid-work single-flight mechanism.

**Not yet complete:** Source owners must confirm the actual product/cohort mappings before
activation. The separately approved synthetic model-quality comparison found
errors, not accepted quality; the authorized follow-ups also found semantic errors.
Production spend verification has not been authorized. The local `make verify`
gate now passes, including the full dependency audit, using the guarded private
development fork described below. This is not an upstream patch or universal
security claim. Source/model acceptance is still pending; the goal remains active.

Free-text conversation answers are deliberately not substituted by a similar saved
answer: history, goals, current time and policies may change their meaning. The
deterministic assessment has no free-text goal or model dependency; future task/model
inputs require a revised identity and separate quality tests. New chat tasks still
use a bounded, budgeted model call. Provider prompt caching is not response caching
and still generates billable output; it is not counted as a zero-cost answer reuse.

## Configuration added so far

`OPERATION_COST_DAILY_LIMITS` and `OPERATION_COST_MONTHLY_LIMITS` are JSON objects
validated into the typed resource contract at composition time. Units:

| Key | Unit |
| --- | --- |
| `document_reads` | Conservatively reserved document reads |
| `response_bytes` | Reserved/known response bytes |
| `provider_requests` | External attempts, including retries |
| `llm_calls` | Individual model requests, not whole autonomous tasks |
| `input_tokens`, `output_tokens` | Input and total billable output tokens |
| `data_microusd`, `llm_microusd` | Estimated micro-USD; 1,000,000 equals $1 |

No free quota is assumed to be available: it is shared with the application.
These counters do not replace Cloud Billing, measure existing Firebase storage,
or automatically capture index/rules-dependent reads. Supported document-response
accounting covers bounded `runQuery`/`listDocuments`, not aggregation indexes,
offsets, listeners or arbitrary SDK operations. Payload-byte accounting is not an
exact measurement of wire/header/TLS transfer. Any new delta query must include its
index-read billing implications before activation.

For metered data/OAuth HTTP attempts, admission reserves the configured maximum
payload plus 65,536 bytes of transport read-ahead. The pinned httpcore HTTP/1.1 and
HTTP/2 implementations read 64 KiB blocks; HTTPX's small `chunk_size` would only
split an already-read block and is not a network ceiling. Raw iteration avoids
decoder/chunker allocations. A provider returning compressed content despite
`Accept-Encoding: identity` is refused before body iteration. Successful EOF
receipts reconcile the margin to observed payload bytes; timeout, cancellation,
compression rejection and ordinary overflow keep the full conservative reserve.
If a replacement transport yields an unexpectedly larger overflow block, its
observed lower-bound usage is recorded, not clipped to the reservation. This does
not promise a physical network limit for arbitrary transports or measure headers,
TLS, server-side pending reads or unrelated billable work.
The operational dependency extra explicitly pins the inspected `httpcore==1.0.9`;
the existing independent MANA AI lockfile already uses that version and is unchanged.
Caller header casing cannot bypass identity negotiation.

The operational chat rate card has its own model identifier and input/cached-input/
cache-write/output prices in USD per million tokens. Defaults describe the existing
`gpt-5.4-nano`; no model switch has been made. Optional `OPERATION_CHAT_MODEL` and
`OPERATION_CHAT_REASONING_EFFORT` override only operational conversation dispatch.
Blank values preserve `OPENAI_MODEL`/`OPENAI_REASONING_EFFORT`; public MANA AI and
audio continue using their existing settings. An explicit chat model requires an
explicit matching rate-model identifier and all four prices before an SDK client
can be constructed, including for copied Settings. The application checks presence
and model agreement, not that operator-supplied prices match the provider's invoice.
A candidate still requires verified rates and quality acceptance before activation.
Changing the shared `OPENAI_MODEL` is not the mechanism for a chat-only rollout.
The audio gateway is unchanged.

Plain-text input uses a conservative UTF-8 byte reservation including instructions,
output schema and protocol allowance. An observed bound violation is recorded and
refused. It is not advertised as exact tokenization. The configured input cap and
global token/currency limits protect the admission path.

## Firestore contract investigation and enforced limitation

The local canonical contract and adapter query require `occurred_at`, not a
confirmed ingestion/update field. Existing operational masks contain current
state but no confirmed queryable update timestamp or deletion marker. The prior
2026-10-05 one-shot scan discarded document contents: its counts **cannot** prove
field/index semantics, immutable events, deletion coverage or application ownership.
No additional paid schema probe has been made.

Consequently, the candidate composition does not instantiate automatic Firestore
readers. `manakids_firebase` emits an honest unavailable mobile source; requested
operational telemetry adds an explicit limitation and performs no prefix scan.
There is no pretend incremental cursor, additive current-state rollup or silent
historical bootstrap. The raw adapter classes remain for separately approved,
bounded diagnostics, not recurring collection.

Before approving a delta implementation, obtain a producer contract covering:

- queryable server-controlled update/ingestion time and its index;
- stable timestamp plus document identity ordering, billing implications, tie handling;
- explicit deletion/tombstone events or another approved deletion-complete feed;
- replay/late-update retention bounds and an explicit bootstrap scope;
- current-state revisions: replace previous contributions, never add repeated states;
- atomic local apply plus cursor commit, durable fencing and restart/replay tests.

`occurred_at` alone misses late events and edits to old events; advancing a document
name pagination token alone misses updates/deletions. Hard deletes leave nothing
for a later ordinary query to return. No external producer changes, exports or
functions are performed under this goal without the owners' agreement.

## Forecast — conditional capacity, not current runtime spend

Run locally:

```bash
.venv/bin/python scripts/operation_cost_forecast.py --products 1
```

The owner clarified on 2026-10-09 that 360REC is request-based and has no
application DB for this analytical work. Current planning is MANA-only; use
`--products 1`. The calculator's historical default remains two products for
reproducibility of archived capacity cases, not a current two-collector plan.
The historical table below is retained as such; the current one-product cases
are in [the MANA scope checkpoint](#mana-only-planning-checkpoint--2026-10-09).

At 50,000 document reads/day, 5 KiB/document, $0.06/100k reads and $0.12/GiB,
the data-only scenario is $0.058610/day, $1.758307/30 days, $21.392734/365 days.
No free allowance is subtracted. Actual delta volume has not been measured and
automatic Firestore collection is currently disabled, so these are assumptions.

The earlier quality-capacity scenario uses two applications, four shared cycles,
up to four analyses/application/cycle (32/day), 20 interactive calls and one complex
call/day. With standard short-context rates checked on 2026-10-08, all input priced
at the conservative cache-write rate and no assumed cache hits:

| Item | Per day USD | 30 days USD | 365 days USD |
| --- | ---: | ---: | ---: |
| Firestore document reads | 0.030000 | 0.900000 | 10.950000 |
| Estimated Firestore payload transfer | 0.028610 | 0.858307 | 10.442734 |
| Scheduled analysis capacity | 1.120000 | 33.600000 | 408.800000 |
| Interactive analysis capacity | 0.800000 | 24.000000 | 292.000000 |
| Complex analysis capacity | 0.300000 | 9.000000 | 109.500000 |
| Total before reserve | 2.278610 | 68.358307 | 831.692734 |
| Total including 25% reserve | 2.848263 | 85.447884 | 1039.615917 |

The capacity uses `gpt-6.1-sol`/$2.50 worst-case input/$10 output per million
and `gpt-6-astra`/$12.50 worst-case input/$50 output. These models are **not selected
or deployed**. Current engagement metrics are deterministic, not 32 scheduled model
calls/day; the operational chat remains `gpt-5.4-nano`. For illustration, 20 current
nano chat calls/day at 8k input/2k output, without cache discounts, cost $0.072/day,
$2.16/30 days and $26.28/365 days for tokens alone. This is also not measured usage
or proof of equal model quality.

The $2 and $90 references are conditional planning envelopes, not complete bills.
Existing servers/storage, upstream backend work, index/rules reads, taxes, audio,
marketing actions and unapproved exports/tools remain outside the calculation.
One application halves only the scheduled capacity component, not chat/data costs.

### Goals capacity checkpoint — 2026-10-09

The separately requested durable Goals workspace is implemented locally, not deployed.
It does not implement absent domain agents or action families. Its separate strong-model
planning/investigation/review shares the existing cost ledger and source cooldowns.
Read delegation is opt-in, fixed-capability and product-bound. It does not make a saved
report fresh or make unconfirmed GA4 mappings usable. Ordinary chat/audio settings are
unchanged. See [Goals scope and verification](operation-goals.md).

The calculator now emits `operation-cost-forecast-v2`. Explicit Goals workload/rates
are separate from ordinary chat: one goal is multiple paid calls, not one call.
The misleading v1 `models_not_selected_or_deployed` list was replaced with
`rate_cards_not_runtime_configuration`: a forecast cannot establish or change a
runtime model, and the local Goals model now exists. Historical v1 artifacts remain
unchanged. The CLI still loads no settings, key, app startup or SDK client.

Prices were rechecked in [official OpenAI Docs](https://developers.openai.com/api/docs/pricing):
Sol Standard short-context input/cache read/cache write/output are $2/$0.10/$2.50/$10
per million tokens. Capacity conservatively uses the highest input category, without
an assumed cache discount. Each Goal assumes **six calls**, **8,000 total input tokens
and 4,096 total output tokens per call**, including reasoning. That is $0.365760/goal
before the separate 25% planning reserve. These are assumptions, not token averages
measured on real administrator goals. Another task, context size or review iteration
can change cost and quality.

Reproducible future-capacity scenarios retain the original 53 calls/day, the same
50,000 reads/day, 5 KiB/document and four shared data refreshes. All totals include
25% reserve; the extra Goals do **not** imply an additional scheduled source read.

| Extra Goals/day | Total calls/day | USD/day | USD/30 days | USD/365 days |
| --- | ---: | ---: | ---: | ---: |
| 0 | 53 | 2.848263 | 85.447884 | 1039.615917 |
| 1 | 59 | 3.305463 | 99.163884 | 1206.493917 |
| 3 | 71 | 4.219863 | 126.595884 | 1540.249917 |

One Goal/day adds **$13.716000/30 days with reserve**. Even this added workload makes
the historical $90 envelope insufficient. The forecast exposes this rather than
silently reducing load or clipping cost to a target. Data-only still costs
$2.197884/30 days with reserve, above the $2 reference. Any extra explicitly approved
source reads must be included in the same daily data volume; they are not free.

There is also an explicitly different chat-only capacity (20 ordinary Sol calls at
8k/2048 tokens plus one six-step Goal/day, no scheduled or Astra model calls):
**$1.542463/day, $46.273884/30 days, $562.998917/365 days** with reserve and the same
data assumptions. Current engagement metrics are deterministic, so no automatic
32-call/day AI analysis is needed for them. This is an explicit alternative workload,
not evidence of equal quality or savings at the original 53-call load. The ordinary
Sol chat profile is not enabled or quality-accepted by this calculation.

Run the pure calculator, without credentials or live I/O:

```bash
.venv/bin/python scripts/operation_cost_forecast.py --goals-per-day 1
.venv/bin/python scripts/operation_cost_forecast.py --goals-per-day 3
.venv/bin/python scripts/operation_cost_forecast.py --analyses-per-product-refresh 0 --complex-calls-per-day 0 --chat-output-tokens 2048 --goals-per-day 1
```

`goal_capacity` separately shows per-step/per-goal costs, assumed tokens/calls,
whether all planned steps fit `--goal-budget-microusd`, and the admission envelope.
It is **not another expense line**. Default $0.50/goal envelopes are $15/30 days and
$182.50/365 days for one new goal daily, before stricter shared limits. Nominal cost
is never lowered to this envelope: 64k input tokens/call makes six steps $1.205760,
so the default admission budget cannot fund the assumed full plan. A goal may pause
instead of completing. Pausing/resuming retains its cost reservations. Unknown
charges, other users, byte-based preflight reservations and daily/monthly resources
can refuse work even when a nominal forecast fits; observed overrun is recorded,
not clipped. Thus these admission limits are not provider-invoice guarantees.

New offline forecast regression coverage proves that Goals do not change data volume,
ordinary rates, old workload or cached-input assumptions; ceilings are not added
twice or used to hide an insufficient plan; CLI validation/network/settings isolation
are enforced. Four generated scenario JSON files are under
`output/cost-forecast-goals-20261009/`; 24 focused forecast tests passed. Final
`make verify` exited **0**: **655 backend tests passed**, 6 isolated PostgreSQL tests
skipped here (already verified for the unchanged persistence checkpoint), 2 opt-in
live tests deselected; **91 UI tests / 19 suites**, mypy **259 source files**,
format/lint/TypeScript, Next.js production build and full npm audit **0 findings**.
Authoritative log: `output/cost-forecast-goals-20261009/make-verify.log`.
Secret scan passed for **739 tracked/unignored files**; `git diff --check` passed.
Only pure forecast code and docs changed at this checkpoint; previous Goals browser,
SQLite and PostgreSQL artifacts are not represented as new production checks.
No source call, new paid check, new schedule, deployment or external state change
was made in this forecast checkpoint.

The separately approved synthetic Goals evaluation completed three Sol/medium calls
for **$0.064916** with all usage settled and no new unknown holds. D1/D7 arithmetic,
percentage points, parent/child separation, tariff-vs-payment distinction, citations
and bounded analysis were manually checked. It is one synthetic workflow, not a
representative comparison or acceptance of ordinary chat. Combined with the previous
immutable diagnostics: **188 attempts, 187 settled/$0.304192 known**, one old
**$0.050128 unknown hold**. Known plus held **$0.354320** is not a reconciled invoice;
UTC daily/monthly rows must not be summed together. No old failed request was retried.

### MANA-only planning checkpoint — 2026-10-09

The product-owner clarification removes the need to discover a 360REC DB or
create a second recurring collector. It does not classify all Firebase collections
or parent/child GA4 streams as MANA, nor activate a source. Exact MANA populations
and ordinary-chat model acceptance are still unresolved. The source confirmation
sheet now asks only for the MANA composition needed for this work.

The following offline runs use **one product**, but retain the same assumed 50k
reads/day, 5 KiB/document, 20 ordinary calls/day and one complex call/day. Only
the hypothetical scheduled model capacity changes from 32 to 16 calls/day;
per-request chat, complex work, Goals and data volume are **not halved**. All
totals include 25% reserve; monthly/yearly periods use 30/365 days respectively.

| Extra Goals/day | Total calls/day | USD/day | USD/30 days | USD/365 days |
| --- | ---: | ---: | ---: | ---: |
| 0 | 37 | 2.148263 | 64.447884 | 784.115917 |
| 1 | 43 | 2.605463 | 78.163884 | 950.993917 |
| 3 | 55 | 3.519863 | 105.595884 | 1284.749917 |

This corrects the planning scope; it is not a same-load optimization or observed
production saving. The original two-product scenario and artifacts are unchanged.
The data assumption remains **$2.197884/30 days with reserve**, above the $2 reference.
Three Goals/day still exceed the $90 combined reference in this future-capacity case.
Existing engagement calculations are deterministic; this table does not create or
claim implemented scheduled LLM analysis, four agents' handlers or new source jobs.

An explicitly different **GA4/saved-aggregate chat-and-Goal capacity** excludes
Firestore until its missing delta contract is resolved, and excludes nonexistent
scheduled/complex model work. At 20 ordinary Sol calls/day (8k input/2048 output)
and one Sol Goal/day (six calls of 8k input/4096 output), token capacity including
25% reserve is **$1.469200/day, $44.076000/30 days, $536.258000/365 days**.
Input is conservatively priced at cache-write cost and includes no assumed cache
hits. Prices were rechecked against
[OpenAI Docs](https://developers.openai.com/api/docs/pricing); rate cards, runtime
models and per-goal admission budgets were not changed.

This is a candidate capacity, **not a current invoice or an accepted model switch**.
Ordinary chat remains nano; the single synthetic strong-model Goal does not accept
the ordinary Sol chat profile. GA4/backend/API direct-fee entries counted here are
zero under the calculator's assumptions, not a claim that backend work, servers,
traffic, storage, taxes or other services are free. Raw requests/SDK startup, external
data reads and source/model activation are absent from this calculation.

Reproduce without loading `.env` or using any credential:

```bash
.venv/bin/python scripts/operation_cost_forecast.py --products 1
.venv/bin/python scripts/operation_cost_forecast.py --products 1 --goals-per-day 1
.venv/bin/python scripts/operation_cost_forecast.py --products 1 --goals-per-day 3
.venv/bin/python scripts/operation_cost_forecast.py --products 1 --reads-per-day 0 --analyses-per-product-refresh 0 --complex-calls-per-day 0 --chat-output-tokens 2048 --goals-per-day 1
```

Four generated artifacts are in `output/mana-cost-scope-20261009/`. Four added fake
regression cases verify the exact one-product totals, unchanged data/per-request
costs and Goals budget, explicit $2/$90 comparisons, and zero priced Firestore or
scheduled/complex model work in the latter case. All **28** focused forecast tests pass.
Fresh `make verify` completed **exit 0**: **659 backend / 91 UI tests**, 6 isolated PG
tests skipped here, 2 opt-in live tests excluded, mypy **259 files**, lint/format/TS,
production Next.js build and full npm audit **0 vulnerabilities**. Log:
`output/mana-cost-scope-20261009/make-verify.log`. The prior docs-only endpoint failure
remains historical evidence, not the outcome of this new command. Secret scan passed
for **746 files**; `git diff --check` passed. Persistence, migrations and UI were not
changed here; no new PG/browser/source audit is claimed.
No new paid model check, source request, `.env` edit, schedule, migration, production
operation or audio/client-service change occurred. The old unknown charge remains held.

## Remaining implementation sequence

1. Complete requirement-by-requirement verification, schema/dependency gates and
   adversarial cases before claiming the agreed implementation scope is finished.
2. Obtain source ownership/cohort confirmation and a bounded representative
   model-quality evaluation under explicit or applicable standing budget approval
   before selecting a replacement model. Known-output replay is not that acceptance.
3. Prepare a separately approved
   canary release/rollback procedure, leaving production untouched until approval.

## Evidence and test scope

- `tests/test_operation_cost_ledger.py`: independent connections, shared global
  admission across products, restart, monthly rollback, uncertain charges,
  concurrent idempotent settlement, rollover and observed overrun.
- `tests/test_operation_shared_data.py`: restart/cache reuse, product separation,
  unverified-scope refusal, source-wide cooldown across query shapes, single flight,
  crashed lease, stale publisher fencing, permanent failure and dated fallback,
  recoverable quota exhaustion. A 24-hour fake-clock test polls four consumers
  hourly for both separately approved fixture applications through three database
  connections, including restart. All 192 logical requests cause exactly eight
  source loads: four per application, with the original cycle dates retained.
- `tests/test_operation_chat_costs.py`: fake SDK receipts, pre-I/O rejection,
  settlement/caching arithmetic, retained timeout reservation, context byte bounds
  and preservation of question/evidence scope.
- `scripts/operation_chat_evaluate.py` and `tests/test_operation_chat_evaluation.py`:
  deterministic synthetic paired QA plan, same actual context/input-bound helpers,
  offline mode without credentials/SDK/HTTP, explicit whole-batch budget guards,
  scoped one-use attempt marker, refusal of an unreviewed model, retained cancelled/
  unknown attempt and stop without retries. Fake SDK completion never means model
  quality passed. See [the QA procedure](operation-chat-quality-evaluation.md).
- `tests/test_operation_metered_http.py`: pre-dispatch reservation, known receipts,
  empty-query charges, unknown HTTP/error/cancellation/oversized charges, GA4 stream
  filters on all report shapes and per-attempt retry accounting. Real async byte
  streams also cover the detection block, early close without consuming another
  block, compression rejection before iteration, margin refund at EOF, admission
  of the margin and recording a nonconforming transport's observed overrun.
- `tests/test_operation_google_auth.py`: fake Google signer/HTTP, concurrent
  refresh, fixed trusted endpoint and explicit JWT scope/claims, expiry, permanent
  rejection, transient cooldown, timeout/cancellation, redirects/oversize,
  invalid receipts and recovery after daily quota rollover. Actual app composition
  uses 21 initial backend/OAuth/GA4 requests and zero additional requests after
  restart/cache reuse; the original assessment calculation time is retained.
- `tests/test_operation_assessment_cache.py`: existing real deterministic rules,
  equality on reuse/restart, changed thresholds/configuration version/facts/rules,
  application separation, future/stale/expired refusal and immutable concurrent
  publication. No provider call occurs in assessment calculation.
- `tests/test_operation_data_runtime.py`: real composition with a fake HTTP source,
  six initial backend requests then zero extra after restart/cache reuse, quota
  refusal before dispatch, oldest collection date, honest mobile unavailability,
  MANA/360REC context separation and unverified pre-authentication refusal.
- `tests/test_operation_evidence_freshness.py`: cached vs stale, expiry not extended
  by report rebuilding, mixed/unverified/future evidence refusal. Actual approval
  and execution HTTP routes also cover a fresh verified fake action and a six-hour
  stale block before provider state reads/writes, including saved approval and app
  restart. New proposals using stale evidence are refused too. No live Meta call
  or new action family is introduced.
- `tests/test_operation_chat_fallback.py` and UI source-detail tests: dated scoped
  fallback after budget exhaustion, no paid dispatch, request replay, expired/future/
  naive/missing collection dates and legacy source metadata without invented freshness.
- `tests/test_operation_cost_forecast.py`: exact reproducible projection, independent
  read/transfer components, application scaling and invalid assumptions.
- `tests/test_postgres_repository.py`: isolated PostgreSQL 17 verification of
  independent-connection global reservations, once-only concurrent settlement and
  shared source admission/permanent failure, plus immutable scoped assessment
  persistence, in addition to existing repository
  concurrency tests.

All provider tests are offline. Full-suite results and further coverage must be
recorded at the next completed checkpoint; focused tests do not prove release readiness.

The evidence-to-requirement audit is maintained separately in
[cost-optimization-requirements-audit.md](cost-optimization-requirements-audit.md).

## Verification checkpoint — 2026-10-08

- `ruff check .`: passed; `mypy .`: 236 source files passed.
- Latest `make verify` completed formatting, lint, Python/TypeScript typechecking,
  370 backend tests, 47 UI tests/16 suites and the Next.js production build.
  It **failed** at the final full `npm audit`: 32 high-severity transitive
  development-tool findings rooted in `braces`.
- Updated only patched `sharp=0.35.5` and `source-map-js=1.2.2`, with a regenerated
  lockfile. `npm audit --omit=dev --audit-level=high` reports zero vulnerabilities.
  This does **not** waive the full audit failure. The published
  [braces advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) has no patched
  version; `npm view braces version` returned `3.0.3`. No forced Next/ESLint downgrade,
  advisory suppression or replacement of the gate was performed.
- `make audit-schema`: passed, OpenAPI and TypeScript generated client synchronized.
- `make audit-migrations`: clean SQLite round trip, existing-copy upgrade, legacy
  cutover and no schema drift passed. Only throwaway audit databases were used.
- `make audit-postgres`: PostgreSQL 17 clean upgrade/downgrade/upgrade and no drift
  passed, plus all four repository/shared-cost integration tests. Confirmed the
  Docker endpoint was a local Unix socket before using the existing audit script.
  Its own temporary test container/database was removed by the script; no existing
  container, working database, production server or credential was altered.
- No paid provider call, Firebase operation, model comparison, deployment, push,
  new schedule or external backend change was performed.

### Additional OAuth/assessment checkpoint

- The focused OAuth/assessment/runtime/Retention suite passed 37 tests. After the
  final quota-rollover fix, OAuth/assessment tests passed all 30 cases; the OAuth
  suite also passed all 22 cases after explicit fake-token fixture naming.
- Repeat `make verify` passed formatting/lint, Python/TypeScript typechecks,
  400 backend tests (five isolated PostgreSQL tests skipped here, two paid/live
  tests deselected), 47 UI tests and the Next.js build. It exited with code 2 at
  the same unsuppressed full `npm audit` (32 high transitive findings rooted in
  `braces`). Therefore the overall release gate is **not** passing.
- Final `ruff check .`, formatting check, `mypy .` (241 source files), secret/skip
  scans, Docker Compose configuration validation and `git diff --check` passed.
- SQLite round trip/existing-copy/drift and OpenAPI/client synchronization passed
  with the additive `f83a4c2d910b` assessment migration. Isolated PostgreSQL round
  trip/drift plus all five integration tests passed. No live database was migrated.
- The pure forecast was rerun unchanged; it remains conditional capacity, not
  observed spend. Assessment memoization saves repeated deterministic computation,
  not model charges: those metrics already made zero model calls.

### Shared-cycle, fallback and transport checkpoint

- Final `make verify` passed Python/UI formatting, lint, Python typechecking
  (242 source files), TypeScript typechecking, **420 backend tests** (five isolated
  PostgreSQL cases skipped, two live cases deselected), **50 UI tests / 17 suites**
  and the Next.js production build. It still exited with code 2 at full `npm audit`:
  **five high** transitive findings through ESLint/Next → fast-glob → micromatch →
  `braces`. The gate remains unwaived; release readiness is not claimed.
- Updated Jest and its jsdom environment to `30.5.2` within the existing major
  version and regenerated the lockfile. The full audit decreased from 32 to five
  high findings. `npm audit --omit=dev --audit-level=high` returned zero findings;
  that is not a replacement for the full audit. No forced downgrade or patch of
  a dependency's source was performed.
- A separate Python dependency audit found three advisories in the local
  `urllib3==2.7.0`. The operational extra now pins the official patched `2.8.0`;
  the independent MANA AI lockfile and production environment are not changed.
  After local installation, `pip check` reported no broken requirements and
  `pip-audit` reported no known dependency vulnerabilities. The local `manaai-api`
  package itself is not on PyPI and is covered by the code/test gates, not the
  advisory database. Repeat full verification with the patched environment passed
  the same 420 backend/50 UI tests and build, then failed at the unchanged five
  high npm findings.
- Async-stream HTTP tests prove that the read-ahead margin is admitted before
  dispatch, oversized/compressed streams close early, successful EOF refunds the
  margin and observed unexpected transport overrun is recorded. No compression
  decoder runs before the body ceiling check.
- The shared 24-hour cycle, dated/no-I/O budget fallback, UI source-date display
  and actual stale-action HTTP path passed. A saved approval and app restart
  cannot bypass stale evidence; a fresh fake-provider control still executes and
  verifies successfully. Live provider writes were not tested or enabled.
- `make audit-schema`, secret scan, TODO/skip scan and `git diff --check` passed.
  Isolated SQLite and PostgreSQL migration round trips/drift checks passed; all
  five PostgreSQL integration cases passed separately. The Docker endpoint was
  verified local, and the script removed only its own temporary test container.
  Existing database files, external data and production services were unchanged.
- The offline forecast was rerun: conditional data-only capacity remains
  $1.758307 per 30 days, total capacity including 25% reserve $85.447884 per 30
  days. No source volume, model quality or production saving was measured in this
  checkpoint. Paid calls and deployment remain unapproved and unperformed.

### Synthetic context-quality harness checkpoint

- Added an offline-first paired evaluation script for eight existing chat tasks
  (16 reference/bounded requests), with task-specific human review criteria.
  No Evals platform integration, automatic model judge, new agent/action, source
  read or model switch was introduced. The default command does not load `.env`
  or construct a gateway; current synthetic conservative token capacity is
  $0.078782, not measured spend. Live batch approval remains outstanding.
- The input reservation helper is now shared with the actual conversation
  gateway, preserving its previous arithmetic. Failed/cancelled fake requests
  retain admission and stop the batch; a used attempt directory cannot be replayed.
  The synthetic long-history case explicitly exposes a dropped earlier budget
  constraint; an honest clarification is not counted as proven equal usefulness.
- Focused QA/chat tests passed 28 cases, followed by all 21 QA cases after adding
  complete opt-in-path fake-SDK checks (artifact/ledger persistence, client closure,
  endpoint refusal and no replay). Final `make verify` passed formatting,
  lint, Python typechecking (244 files), TypeScript typechecking, **441 backend
  tests** (five separate PostgreSQL cases skipped, two live cases deselected),
  **50 UI tests / 17 suites**, and production build. It still failed at the full
  npm audit's five high transitive `braces` findings; no waiver was added.
- OpenAPI/client synchronization, secret/skip scans and whitespace validation
  passed. Persistence/migrations and independent audio/client service contracts
  are unchanged by this QA checkpoint. There is no model-quality result, paid
  provider usage, deployment, push or enabled schedule to report.

### Approved single-batch quality review and local follow-up

- User explicitly approved one synthetic batch, at most 16 current-model calls
  and $0.50, no product-source/production I/O or repeated batches. It completed
  16 calls with model `gpt-5.4-nano-2026-03-17`; every reservation settled.
  Usage/rate-card accounting totals **$0.010689**, 29,315 input/3,854 output tokens.
  This is not an invoice or a projection of the production workload. The immutable
  plan, responses, ledger and exact old instruction snapshot are in
  [the batch review](../output/operation-chat-evaluation/user-approved-20261008-context-qa/review.md).
- **Quality was not accepted.** Raw replies proposed MANA parent data for 360REC,
  confused child/parent counts, cited report-generation rather than collection
  dates, lost an earlier budget and overstated planned-agent proposal workflows.
  Existing server guards would refuse the invalid MANA card; no foreign-app
  source read or operational action actually occurred. Successful schema/HTTP
  receipts do not override the semantic errors.
- Local follow-up shares the existing confirmation-card policy between server
  context and output guard, scopes the parent-availability flag to the topic,
  labels `report_created_at` explicitly, and strengthens evidence/entity/planned
  workflow instructions. Excerpting assistant text first preserves all six user
  messages/$30/no-discount/no-contact constraints in this offline long-history
  case at 23,715 bytes. Other oversized histories can still omit old turns.
- The v2 offline plan records its complete instruction snapshot and estimates
  $0.083639 for a potential 16-call batch. At this initial checkpoint it was not
  run or approved; the later explicit follow-up/standing approval and measured
  results are recorded below. The first approval's unused allowance alone was
  never authority for another batch. Owner quality review is still needed.
- Local SDK parsed-object size accounting no longer emits generic serialization
  warnings containing reply text. An actual SDK parser with fake HTTP reproduces
  that warning and verifies identical serialized size/known cost without warnings.
  Model/tier/usage checks and conservative unknown reservations are not weakened;
  no global warning filter or additional paid request was introduced.
- Newly reported direct Next.js advisories were resolved locally by pinning
  `next` and `eslint-config-next` to the same **16.3.8** patch release and
  regenerating the lockfile. The official advisories identify this patched release;
  see [cache poisoning](https://github.com/advisories/GHSA-4jqv-mc3x-m676) and
  [image SSRF](https://github.com/advisories/GHSA-cjq9-62q9-8jv4).
  Production dependency audit is clean; the full development audit still has
  five high transitive `braces` findings, with no suppression/forced downgrade.
- Final `make verify` passes Python/UI formatting, Ruff/ESLint, mypy (245 files),
  TypeScript, **465 backend tests** (five isolated PostgreSQL cases skipped,
  two opt-in live cases deselected), **50 UI tests / 17 suites**, and the Next.js
  16.3.8 production build. It still exits 2 at the full npm audit; release
  readiness and goal completion are **not** claimed.
- Focused QA/grounding/gateway tests pass 49 cases. OpenAPI/client synchronization,
  secret scan, whitespace validation and the old instruction hash check pass.
  Persistence/migrations are unchanged by this follow-up; the separate PostgreSQL
  checkpoint above is not a newly executed production database check.
- No push, deployment, new schedule, Firebase/GA4/backend read, source mutation,
  IAM/SSH/audio/client-service change or second paid batch occurred.

### Authorized follow-up and standing low-cost checks

- The user explicitly approved the follow-up and authorized future checks costing
  **less than $0.50** without a separate question. This is not permission for
  unlimited automatic retries, source changes, mappings, live product reads or
  deployment. A bounded batch still has a documented scope and explicit ledger
  cap. Exclusive attempt IDs and stop-on-first-error behavior remain intact.
- [v2 review](../output/operation-chat-evaluation/user-approved-20261008-context-qa-v2/review.md):
  16/16 completed, all receipts settled, $0.012338 known rate-card cost under a
  $0.49 ledger cap. Scope/date/long-history behavior improved; unsupported parent
  audience/payment substitutions and planned workflow overstatements remained.
- Local follow-up labels evidence with `capability_key`/`report_type`, distinguishes
  a source's availability from fitness for the requested metric, and clarifies
  unavailable Retention contact and planned-agent handlers. This changes only
  model context/instructions, not operational permissions or implementations.
- [v3 review](../output/operation-chat-evaluation/standing-approved-20261008-context-qa-v3/review.md):
  16/16 completed, all receipts settled, $0.013334 under a $0.10 ledger cap;
  conservative preflight cost $0.088082. All replies selected `none`; prior user
  constraints and scope were retained in this synthetic set. Payment proxies,
  incomplete stale/truncation disclosure and an unsupported guarantee of future
  360REC analysis still prevent semantic quality acceptance. Raw results remain
  `manual_review_pending`; successful HTTP/schema is not an accepted quality score.
- Two follow-ups cost $0.025672; including v1, 48 calls cost $0.036361 by usage/rate
  cards, not invoice reconciliation. Each batch has a separate preserved SQL
  ledger/instruction snapshot. UTC-day and month counters are not summed twice.
  No unknown charges remain in these batches. Product-source calls, document
  reads, operational actions, deployment, push and newly enabled schedules are zero.
- The full dependency audit still reports the same five high findings rooted in
  `braces`; the latest registry version is 3.0.3 and the
  [advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) lists no patched
  version. No audit waiver, forced downgrade or fabricated remediation was used.
- Verification after v3 context changes: `make lint`, `make typecheck`, `make test`
  pass; the corrected final `make verify` passes formatting, Ruff/ESLint, mypy
  (245 files), TypeScript, 465 backend tests (five isolated PostgreSQL skipped,
  two live cases deselected), 50 UI tests/17 suites and the production build,
  then exits 2 at full npm audit. Production-only npm audit reports zero findings.
  OpenAPI/client sync, secret scan (509 files), whitespace checks and exact v3
  instruction snapshot verification pass. No paid process remains running.

### Controlled reasoning/model comparisons and context correctness

- Fixed hidden history truncation before `_bounded_context`: stored user constraints
  beyond character 3000 now reach the byte-bound helper. Assistant prose is shortened
  first; older whole turns may still be explicitly omitted. This is not durable
  full-conversation memory. Initial report summary/note clipping now sets
  `report_text_shortened` before the overall byte bound. Real HTTP-route tests use
  fake models and cover both defects.
- Removed the misleading root `scope_verified=false` from the conversation envelope.
  Topic selection is not source-access verification; per-report product checks and
  source admission remain. Added typed descriptions of existing allowed cards so
  the model does not confuse saved reports with the saved proposal queue. No tools,
  permissions, agent handlers or action families were added. Approval cards still
  disclose that proposal-to-product binding is unconfirmed.
- [Reasoning comparison](../output/operation-chat-evaluation/standing-approved-20261008-reasoning-holdout/review.md):
  eight new synthetic tasks, 16 calls, nano `none` versus `low` with identical
  paired inputs. All receipts settled; $0.010484 under a $0.10 cap. Low cost 15.1%
  more in this single batch without sufficient quality improvement; both profiles
  missed the positive Growth approval-card control. Reasoning was not switched.
- After the context corrections,
  [model comparison](../output/operation-chat-evaluation/standing-approved-20261008-model-comparison/review.md):
  the same eight tasks, 16 calls, nano versus mini, both `none`. All receipts settled;
  $0.016959 under a $0.20 cap. Mini preserved sample boundaries/numbers and useful
  cards better; nano still invented numbers and unsupported source/workflow steps.
  Mini is a preliminary validation candidate, not production acceptance. These
  tasks are now a regression set, not an independent unseen benchmark; owner
  acceptance and broader representative quality validation remain outstanding.
- The offline-first harness has mutually exclusive typed reasoning/model comparison
  modes, per-profile rate cards, cloned evaluation Settings and one shared isolated
  ledger. It validates all candidate endpoints before dispatch, closes every client,
  stops on the first failure and never retries automatically. Working Settings,
  `.env` and the current nano/none configuration are unchanged.
- These two batches total 32 calls/$0.027443; all five preserved batches total
  80 calls/$0.063804 by known usage/rate cards, not invoice reconciliation. There
  are no unknown charges in these batches; day/month counters are the same spend.
  Source reads, operational actions, push, deployment and newly enabled schedules
  remain zero. The main capacity forecast is unchanged; a small model smoke does
  not establish production workload or savings.
- Latest verification: focused chat/grounding/evaluation/gateway tests pass **69**
  cases; `make lint` and `make typecheck` pass. Final `make verify` passes formatting,
  Ruff/ESLint, mypy **245 files**, TypeScript, **480 backend tests** (five isolated
  PostgreSQL skipped, two live cases deselected), **50 UI tests/17 suites** and
  the Next.js **16.3.8** production build, then exits 2 at full npm audit.
  Production-only npm audit has zero findings; five high development-tool-chain
  findings remain rooted in `braces` 3.0.3, with no published patched version at
  this check. No audit waiver, unsafe downgrade or fabricated remediation was used.
  OpenAPI/client synchronization, secret scan (**517 files**), whitespace checks
  and the exact latest instruction snapshot match also pass. No paid evaluation
  process remains running. Persistence/migrations were not changed by this
  comparison checkpoint.

### Additional validation and exact card-capability context

- [Validation comparison](../output/operation-chat-evaluation/standing-approved-20261008-validation-comparison/review.md):
  eight tasks not previously used for calls/context corrections; 16 nano/mini
  answers with identical paired inputs and unchanged instructions. All 16 receipts
  settled; $0.022007 known usage/rate-card cost under a $0.20 cap (preflight
  $0.182251). Six batches now total 96 calls/$0.085811, not invoice or whole-project
  spend. Product-source reads, operational actions, retries and deployment are zero.
- This new set contradicts broad quality acceptance: mini reversed report creation
  order in its temporal explanation, while both models selected `mana_parents` for
  fresh activity analysis. Prefix/payment and zero-denominator answers improved,
  but a correct numeric answer alone does not prove correct evidence/workflow.
- Corrected the ambiguous card context without adding execution capabilities:
  `analyze` now names the actual default capability from the existing agent
  registry, distinguishing `retention.engagement.analyze` from Parent tariffs/links
  and Growth advertising from its separate funnel capability. The typed helper
  requires the default key whenever an analysis card is offered. Planned chats
  still have no analysis card; server permission/product checks are unchanged.
- A first verbose metadata draft displaced the oldest user budget turn under the
  24 kB bound. The regression test failed and the draft was shortened, not the
  test weakened. Current v5 preserves all six user messages at **23,861 bytes**
  (reference 41,501). New paid validation v1 remains immutable; current v2 is an
  offline regression set, not a second unseen test or completed paid rerun.
- The additional mode has fake-SDK success/timeout tests and offline tests that
  forbid SDK, settings and HTTP access. Updated focused chat/grounding/QA tests
  pass **77** cases. The source configuration was inspected without provider I/O:
  product/binding remain `unverified`, GA4 stream IDs empty. Owner-confirmed
  product/cohort boundaries must not be invented from labels in historical output.
- Rechecked the dependency blocker: `braces` latest 3.0.3 remains unpatched;
  `micromatch` 4.0.8 still depends on it. Even the published Next ESLint plugin
  16.4.0 retains `fast-glob`/the same chain. No dependency migration, forced
  downgrade or audit waiver was applied; production-only npm audit remains clean.
- The context correction has no post-fix paid quality result. Temporal explanation
  accuracy, appropriate cards and independent representative acceptance remain
  open requirements, not optional production polish.
- Final post-correction `make verify`: formatting, Ruff/ESLint, mypy **245 files**,
  TypeScript, **488 backend tests** (five isolated PostgreSQL skipped, two live
  cases deselected), **50 UI tests/17 suites** and Next.js **16.3.8** production
  build pass. Full npm audit still causes exit 2 with the same five high findings.
  `make lint`, `make typecheck`, the focused **77** tests, secret scan **521 files**
  and whitespace checks pass. Production-only audit reports zero findings. No
  paid process remains running; no push or deployment was performed.

### Post-fix regression and mini-effort comparison

- [Validation-v2 rerun](../output/operation-chat-evaluation/standing-approved-20261008-validation-v2/review.md):
  one bounded 16-call nano/mini party, cap $0.20, preflight $0.182258, known cost
  **$0.020762**, all receipts settled. Mini now offers engagement `analyze` rather
  than Parent summary and describes creation/observation order correctly. Nano
  still unnecessarily asks activity-versus-Parent clarification; missing citations
  and cohort wording limit broader acceptance. This is a regression check after
  context correction, not a fresh independent benchmark.
- [Mini none/low](../output/operation-chat-evaluation/standing-approved-20261008-mini-reasoning/review.md):
  another bounded 16-call party, cap $0.30, preflight $0.286478, known cost
  **$0.027500**, all 16 receipts settled with no unknown remainder. Same eight
  regression tasks and identical paired inputs/instructions/schema; only effort
  differs. The SDK constructs two mini clients, not an unused nano client, with
  cloned settings, matching rate cards, one isolated durable ledger, zero retries
  and `store=false`. A failed request stops the party; attempt IDs cannot replay.
- Mini low preserves the $17/month/no-discount/no-contact/no-Parent constraints
  and evidence citations better. Mini none suggests Parent reading in its plan
  despite that prohibition, even with card `none`: it is not accepted. Low is a
  preliminary local candidate, not promotion/representative owner acceptance.
  Missing explicit confirmation/admission language, unnecessary plans and minimal
  UX still need evaluation. Supporting an effort setting is not quality evidence.
- Mini none/low cost $0.009271/$0.018229 at observed usage, with 15,847 input each
  and 1,415/1,985 output tokens. The difference includes unequal prompt-cache hits,
  not just reasoning overhead. Conservative forecasts must not assume caching;
  output includes reasoning without double billing. Eight parties now total
  **128 calls/$0.134073**, not a production invoice or complete project bill.
- This checkpoint changes only the local evaluation harness, fake tests, reviews
  and documentation; working `.env`, app defaults, dependencies, sources, UI,
  audio, schedules and production remain unchanged. The shared global model is
  not switched merely to activate an operational candidate. Source-owner mappings
  remain pending; unverified bindings/empty stream lists are not guessed.
- Updated fake/offline/grounding focus passes **84** tests. `make lint` and
  `make typecheck` pass. Latest `make verify` passes formatting, Ruff/ESLint, mypy
  **245 files**, TypeScript, **495 backend tests** (five isolated PostgreSQL skipped,
  two live cases deselected), **50 UI tests/17 suites**, and Next.js **16.3.8** build.
  Full verification still exits 2 at the unchanged five-high transitive
  `braces`/ESLint dependency audit; the gate is not waived. Earlier checkpoint
  counts above remain historical, not latest results.
- Rechecked production-only npm audit: **zero findings**. Secret scan passes
  **529 tracked/unignored files**, whitespace validation passes, and the eight
  preserved SQL ledgers independently sum to 128 settled receipts/$0.134073 with
  zero unknown charges. No paid evaluator or verification process remains running.

### Operational model configuration isolation

- Added optional typed chat model/effort settings with blank-value inheritance.
  Defaults and the working `.env` are unchanged; no candidate is activated.
  `OpenAIConversationModel` snapshots the resolved operational model/effort and
  meters that model's explicit rate card, without mutating the global Settings.
- Explicit model overrides cannot silently use an incomplete default rate card.
  Settings validation and gateway construction both check the configuration;
  even a `model_copy()` bypass is rejected before SDK creation. Existing ledger,
  output ceiling, unknown-charge treatment, zero retries and privacy controls remain.
  Configuration error text hides input values so a cross-field pricing error does
  not print unrelated secret inputs; controlled errors remain readable.
- The synthetic QA tool now checks the effective operational baseline and changes
  only scoped fields in candidate Settings. A public model/effort different from
  the operational baseline remains untouched. A normal none-baseline plan also
  refuses a changed operational effort before constructing a gateway or attempt.
- Configuration tests use fakes only: inheritance/blank values, explicit `none`
  versus global `high`, invalid identifiers/effort, five missing card fields,
  copied-setting bypasses, mini dispatch/573-micro-USD fake settlement, and the
  real chat HTTP route with public MANA AI still on the global model. External
  network access is forbidden in the composition test. The evaluation comparison
  test likewise proves public settings are unchanged. No paid call, source read,
  deployment, schedule, key, SSH or audio-code change occurs in this checkpoint.
- Final verification: focused configuration/QA/cost/fallback/public-gateway tests
  pass **87** cases. `make verify` passes formatting, Ruff/ESLint, mypy **246 files**,
  TypeScript, **514 backend tests** (five isolated PostgreSQL skipped, two live
  deselected), **50 UI tests/17 suites** and Next.js **16.3.8** build. The unchanged
  full npm audit still exits 2 on five high dev-chain findings; production-only
  audit reports zero. Secret scan passes **530 tracked/unignored files** and
  whitespace validation passes. No gate or vulnerability finding is suppressed.
- Read-only inspection of effective local settings confirms nano/none, no explicit
  chat-model override, nano rate model, unverified product/binding, zero configured
  GA4 streams and scheduler disabled. Paid-party totals remain 128 settled calls/
  $0.134073; this checkpoint's paid/source calls are zero. Production is untouched.

### Guarded development dependency checkpoint

- The upstream `braces@3.0.3` denial-of-service advisory still has no patched
  release. Replacing the glob library or brace parser changed literal-directory,
  globstar, absolute-path, bracket and quoted-pattern behavior in local checks.
  No forced Next downgrade, advisory waiver or removal of Next lint rules was used.
- Added a private MIT-preserving fork, `@manaai/bounded-braces@0.1.0`, with the
  original parser semantics within explicit resource bounds. Parsing limits both
  brace and parenthesis nesting; iterative AST validation checks children and
  parent cycles before recursive compile/expand/stringify walkers. Iterative
  flattening/Cartesian concatenation and pre-allocation numeric range checks bound
  result counts and output text. Exponent/hex/plus-sign ranges, descending ranges,
  unsafe integers, `rangeLimit: false`/NaN/Infinity and direct AST inputs are covered.
  Limits throw rather than silently omit application roots. The input ceiling is
  10,000 characters, traversal depth 128, results 1,000 and output text 1 MiB.
- The root dev dependency and `$braces` override resolve the local package without
  an invented upstream version. Lockfile checks permit only the inspected current
  `micromatch@4.0.8` consumer through Next 16.3.8/fast-glob 3.3.1. A CommonJS-only
  import-style exception is scoped to the vendored JavaScript; application import
  restrictions and all recommended Next rules stay enabled. `npm audit` remains
  unchanged and mandatory. Maintenance/removal rules are in the
  [fork README](../admin-ui/vendor/bounded-braces/README.md).
- Fixed an npm file-override installation artifact and validated the final graph
  with clean `npm ci --ignore-scripts` and `npm ls --all`, not just successful
  fallback module resolution. Relative to the preserved pre-checkpoint lock,
  only the root dev declaration, `braces` link and new vendor package differ;
  unrelated transitive versions were preserved. Docker copies the fork before
  installing dependencies. No runtime service/container was replaced.
- Added **34** mandatory Node tests to every lint invocation: exact dependency
  identity, bounded syntax/AST/options, hostile deep/cyclic/range inputs, real
  Next root discovery and actual lint-rule rejection/control cases. All pass
  locally and in the Node 24 Alpine build image with networking disabled.
  A separate comparison against the original npm tarball matches **150** finite
  safe pattern/options outcomes, including matching pre-existing exceptions.
- Final `make verify` completes with **exit 0**: formatting, Ruff/ESLint, mypy
  **246 files**, TypeScript, **514 backend tests** (five isolated PostgreSQL skipped,
  two live deselected), **50 UI tests/17 suites**, Next **16.3.8** build and
  **zero full npm audit findings**. Production-only npm audit and `npm ls --all`
  also pass. The standalone health/root/nested-route smoke passes locally; the
  Node 24 Docker image builds successfully. Secret scan and whitespace checks
  pass. Evidence is in
  [dependency checkpoint](../output/glob-compat-20261008-4yrGTe/review.md).
- This removes the local dependency release-gate blocker, not missing live source
  ownership or model-quality acceptance. No additional OpenAI or product-source
  requests, deployment, schedule, keys, IAM, SSH or audio changes occurred. The
  eight paid parties remain **128 settled calls/$0.134073**, with no unknown charges.

### Fresh profile quality checkpoint

- Added a disjoint eight-task synthetic dataset and `--fresh-comparison` to compare
  the current nano/none profile with mini/low on identical bounded contexts.
  No runtime instructions, model configuration, source bindings or services changed.
  All five comparison modes are exclusive. Fake-only tests verify determinism,
  old-set disjointness, paired hashes, preserved user-tail constraints, real initial
  report-minimization shape, budgets and credential/SDK/network-free offline mode.
- Fixed the rubric before execution in
  [fresh QA plan](operation-chat-fresh-qa-plan.md). The one standing-approved party
  has at most 16 attempts/$0.25, a $0.191582 conservative reserve, no retries and
  no product data. It completed 16/16 at **$0.023060** by settled usage/rate cards,
  33,084 input/3,949 output tokens; all sixteen SQL receipts match results and
  cumulative cost. Unknown charges are zero. No automatic repeat was started.
- [Review](../output/operation-chat-evaluation/standing-approved-20261008-fresh-comparison/review.md):
  mini avoids nano's unsupported payment/source card and better preserves the
  no-read constraints, but has **6/8** strict functional passes, missing explicit
  share differences and adding an unnecessary Growth display plan. The required
  7/8 plus both full positive controls are not met; no profile is accepted or
  activated. This is Codex review, not independent owner labels or production data.
  Both model and effort differ; cache splits are not persisted, so measured money
  and latency differences are not attributed solely to a single profile parameter.
- `make lint typecheck` and focused fake-only **99** cases pass. Full `make verify`
  completes **exit 0**: Ruff/ESLint/format, mypy **246 files**, TypeScript,
  **520 backend tests** (five isolated PostgreSQL skipped, two live deselected),
  **50 UI tests/17 suites**, **34 dependency checks**, Next **16.3.8** build and
  zero full npm findings. Earlier dependency Docker/standalone and isolated
  PostgreSQL evidence remains separate, not a new production test.
- All nine preserved party ledgers contain **144 settled receipts/$0.157133**,
  zero unknowns. Day/month counters are not double-counted. Source reads/actions,
  deployment, scheduling, `.env`, working model, keys, IAM, SSH and audio changes
  are zero. Owner-confirmed product/cohort mappings and quality acceptance remain
  open; the complete objective is not marked achieved by passing narrower gates.

### Subsequent output-contract correction

- Following the completed fresh review, tightened only the chat instructions and
  existing Parent-card purpose: simple answers/cards use empty plans, requested
  deltas are answered directly, flat totals do not establish stable cohort members,
  and supported reads remain subject to scope/access/cooldown/budget admission.
  No semantic output postprocessor, heuristic intent router or new handler added.
- Historical party manifests/results/ledgers/reviews and the preregistered rubric
  remain unchanged. The new instruction hash and exact boundaries are recorded in
  [output-contract checkpoint](operation-chat-output-contract-checkpoint.md).
  All used cases are regression sets; there is **no post-fix paid quality result**.
- Five new actual-route fake regressions preserve empty simple plans, explicit
  complex plans, scoped cards, evidence dates and request replay without runs.
  Focused QA/configuration/grounding tests pass **104** cases. New conservative
  fresh reserve is $0.199397, still below its $0.25 cap; this is not a payment.
- `make lint typecheck` and full `make verify` complete **exit 0**: formatting,
  Ruff/ESLint, mypy 246 files, TypeScript, **525 backend/50 UI tests**, 34 dependency
  compatibility tests, Next 16.3.8 build and zero npm findings. Five isolated
  PostgreSQL tests skipped, two live deselected; previous PostgreSQL/Docker
  evidence remains separate. Secret scan: 565 files; whitespace checks pass.
- No paid party, live source read or deployment was started. Nine prior parties
  remain 144 settled calls/$0.157133. Default model, `.env`, keys, source bindings,
  schedules, IAM, SSH, audio and client services are unchanged. Source-owner
  mappings and real-model quality remain prerequisites, not assumed completion.

### Post-fix profile regression and deterministic UI boundary

- Fixed a separate post-fix plan before dispatch; unchanged eight regression
  tasks, identical paired inputs, nano/none versus mini/low and the current
  instruction hash. Standing approval covers this one 16-attempt/$0.25 party,
  reserve $0.199397; there was no automatic blind retry, paid grader or new data.
- [Review](../output/operation-chat-evaluation/standing-approved-20261008-postfix-comparison/review.md):
  completed 16/16, **$0.024371**, 36,084 input/3,594 output tokens. All settled SQL
  usage/cost receipts match results, unknown zero. All ten party ledgers now have
  **160 settled calls/$0.181504**, not an invoice or production/Firebase bill.
- Both profiles now use empty plans and correct card enums; mini gives the full
  numerical delta. However mini still omits stale/admission qualifications: 6/8,
  with the Parent control failing. Nano has a critical percent-point/count unit
  error. Neither passes the fixed model gate. At that checkpoint no additional
  party or model switch had occurred. The separately planned candidate and its
  rejection/rollback are recorded below; earlier raw results were not rewritten.
- Added deterministic UI warnings for stale/unknown/unverified source metadata
  outside collapsed details, including failed/budget-fallback turns. A bounded
  local timeout updates display when verified evidence expires, with cleanup on
  evidence change/unmount; no source/model polling. Browser time is advisory,
  never action authority. Existing server freshness/admission policies remain.
- Existing confirmation text explicitly says access, budget or the read interval
  can refuse a request; no new button, read, action, handler or contract. These
  UI safeguards do not retroactively make either model answer pass its rubric.
- Added 18 fake-only UI regressions: fresh/stale/expired/unknown/future/malformed
  evidence, old payloads, failed turns, timer replacement/cleanup and conditional
  read confirmation. Focused UI: **34 passed**. That checkpoint's `make verify` is
  **exit 0**: 525 backend/68 UI tests, mypy 246 files, TypeScript, formatting/lint,
  34 dependency checks, Next 16.3.8 build and zero npm findings. Five PostgreSQL
  integration tests skipped, two live deselected. Earlier failed intermediate
  checks are not the final result; accepted log is
  `output/operation-chat-evaluation/postfix-comparison-final-verification.log`.
- Browser fixture is isolated behind the existing fake/local-only settings guard:
  seeded synthetic historical Parent run/report, no real parents/source reads.
  Browser checks cover visible warnings, conditional confirmation, accessibility
  and 320-pixel mobile layout. Browser check **passed**, terminal log:
  `output/operation-chat-evaluation/postfix-ui-browser-cached.log`; desktop/mobile
  screenshots were visually inspected in `postfix-ui-20261008-cached-browser`.
  Initial unconditional Chromium download timed out before application testing;
  the helper now probes a private installed-browser session and installs only if
  no working runtime is available. It never attaches to the user's Chrome.
- Runtime preflight still shows scheduler disabled, unverified source binding and
  zero GA4 streams. `.env`, source mappings, production, IAM/SSH/keys, audio and
  client services are untouched. Goal/model/source acceptance is not claimed.

### Required-reply candidate rejection and local rollback

- A new [preregistered party](operation-chat-required-reply-qa-plan.md) followed a
  concrete instruction reorganization, not a resume: mandatory evidence/read
  qualifications were moved into a delimited first section. 7,103 bytes versus
  7,125, same context hashes/tasks/schemas/rates; no task-specific answers added.
  Reserve $0.199291, cap $0.25, 16 attempts under standing permission.
- [Completed review](../output/operation-chat-evaluation/standing-approved-20261008-required-reply-comparison/review.md):
  **16/16**, **$0.025220**, 36,052 input/3,727 output tokens, 193,964 response bytes.
  All settled SQL receipts match results; unknown zero. Eleven ledgers total
  **176 calls/$0.206724**; the two parties in this checkpoint cost **$0.049591**.
  No product-source read, mutation, paid judge or further party.
- Nano 5/8, mini 4/8 against unchanged functional checks; both utility 12/16.
  The stale warning appears in mini's comparison, but denominator delta is
  incomplete. Mini replaces the requested Parent refresh with a saved explanation
  and misdescribes proposal viewing as read confirmation. Other missing evidence
  qualifiers/regressions remain. Neither passes the fixed gate. These tiny reused
  tasks do not establish general model ranking or representative acceptance.
- Rejected only that prompt change and restored exact instruction hash
  `a06137c6f5884c7a5894ef9085e93f3b42268871d1fe0db32773cd7cc3f058db`
  (7,125 bytes). Earlier dirty-worktree changes and new UI safeguards remain.
  Successful parsing and low cost are not grounds to keep a semantically regressed
  prompt. OpenAI Docs shaped the delimited candidate and fixed task-specific review;
  no production/model/configuration change was made.
- Final restored-code `make verify` **exit 0**: 525 backend/68 UI tests, mypy
  246 files, TS/lint/format, 34 dependency checks, Next 16.3.8 build and npm audit
  zero. Log: `output/operation-chat-evaluation/required-reply-restored-make-verify.log`.
  Focused 118 backend cases pass. Five PostgreSQL tests skipped/two live excluded;
  prior PostgreSQL/Docker evidence remains separate from this checkpoint.
- Mobile browser coverage now explicitly scrolls the transcript to verify the
  confirmation button and source warning are reachable above the composer,
  with details still closed. Screenshot directories are created before launch;
  even failure cleanup has explicit no-auto-connect/no-session-restore flags.
  The earlier output-directory failure was test setup, not a passed UI check.
  Final browser **exit 0**, including fake OTP/session, private-topic isolation,
  Parent confirmation, Growth review/approval/verification, reload/logout, axe
  accessibility and 320-pixel scroll-reachability checks. Log:
  `output/operation-chat-evaluation/required-reply-browser-accepted.log`;
  screenshots in `required-reply-ui-20261008`, desktop/mobile visually inspected.
  Failed setup log is retained separately; no further paid call. `bash -n`,
  secret scan (610 files) and `git diff --check` pass. No live source/production,
  `.env`, key, IAM, SSH, audio, client-service, scheduling or model-default change.

### Flagship timeout, explicit charge states and profile forecasts

- [Preregistered GPT-5.4 diagnostic](operation-chat-flagship-qa-plan.md): all eight
  unchanged regression cases/current instructions, full/low, explicit 1536 output
  ceiling, reserve $0.461117/cap $0.49. Not a same-ceiling paired model comparison;
  no default/rate/timeout/prompt change. The first request timed out after 45,844.7
  ms, seven cases not sent. Semantic quality was **not evaluated**, not scored zero
  or accepted. [Review/receipts](../output/operation-chat-evaluation/standing-approved-20261008-flagship-quality/review.md).
- Preserved one **unknown hold/$0.050128**, no refund/retry/new party. Across all
  twelve ledgers: **177 attempts, 176 settled/$0.206724 known, one unresolved**;
  known plus held $0.256852 is not a confirmed invoice. SQL JSON `null` decodes to
  no actual receipt, even though `actual IS NOT NULL` can be true in SQLite.
  New diagnostic reports explicitly separate known charges and unknown holds
  using ORM-decoded receipts; original manifests/results are not rewritten.
- Added 13 fake/offline diagnostic cases for whole-set preservation, fixed
  ceiling/rates/admission, exclusivity, isolated Settings and timeout stop/retained
  holds/no resume. Extended the pure forecast with explicit typed rate-card JSON,
  scheduled/complex counts and chat output assumption. Seven new forecast cases
  cover offline operation/invalid inputs, unchanged default capacity, chat-only
  cost and the original future load exceeding the planning reference.
- Two separate Decimal scenarios, not a claim of same-load cost reduction:
  [20-chat-only capacity](../output/operation-chat-flagship-capacity-20261008.json):
  $1.149263/day, $34.477884/30 days, $419.480917/365 days including 25% reserve.
  [Original 53-call future capacity](../output/operation-chat-flagship-full-capacity-20261008.json):
  $3.324263/day, $99.727884/30 days, $1213.355917/365 days including reserve.
  Both use explicit hypothetical 50k reads/day/5 KiB and no free quota; data-only
  before reserve remains $1.758307/30 days, not an enabled Firestore source.
  The future complex profile uses the existing conservative cache-write input
  price, not an observed cache-write or an implemented agent. No chat rate card
  or quality acceptance is inferred from arithmetic or a timed-out request.
- Final `make verify` **exit 0**, **545 backend/68 UI**, mypy 246 files, TS/lint/
  format, 34 dependency checks, Next 16.3.8 build and npm findings zero. Log:
  `output/operation-chat-evaluation/flagship-handoff-make-verify.log`. Five isolated
  PostgreSQL tests skipped/two live excluded. Focused diagnostic/forecast tests:
  **77 passed**; secret scan (621 files) and `git diff --check` pass.
  No new browser run: UI is unchanged since the preceding passed browser/visual
  checkpoint. Source-owner/representative model acceptance, unknown reconciliation
  and separately authorized deployment are not claimed complete.
- OpenAI Docs influenced selection, explicit rates and rejecting savings without
  semantic evidence. No live source, production, `.env`, IAM/key/SSH/audio,
  application schedule or client-service changes. No automatic follow-up after
  the timeout; root cause/access/billing cannot be inferred from its class alone.

### Sol profile, retained unknown charge and data-reserve forecast

- Following a fresh OpenAI Docs capability/pricing check, implemented the fixed
  offline/live diagnostic selector `--sol-quality`: all eight unchanged regression
  cases, original prompt/context hashes, Sol/low/2048, standard tier and existing
  45-second timeout. `none` is unsupported, so preflight refuses it. Whole-batch
  reserve $0.440637/cap $0.49, zero SDK retries, isolated copied Settings/SQL ledger.
  This was a reviewed different-profile selection step, not automatic retry of
  the GPT-5.4 timeout or a new prompt experiment. Old party/hold remain intact.
- [Raw receipts and fixed review](../output/operation-chat-evaluation/standing-approved-20261008-sol-quality/review.md):
  eight settled/$0.032552, 18,042 input/1,190 output tokens, zero new unknown holds;
  mean/median latency 5225.0/5061.1 ms. **7/8**, utility15/16, zero unambiguous
  critical errors and no regression on the six previous mini passing cases.
  Parent correctly offers bounded confirmation but only says access/limits, not
  explicit scope/cooldown/budget. Both full controls are required; **gate not
  passed**. No retrospective waiver from deterministic UI warnings or model switch.
  No further party, paid grader or prompt tuning. No representative acceptance.
- All thirteen archived ledgers: **185 attempts, 184 settled/$0.239276 known**,
  **one old unknown/$0.050128 held**. $0.289404 combines known/held, not an invoice.
  Original manifests/results and old receipt remain untouched; read-only audit
  decodes JSON `null` correctly. UTC day/month usage is not summed twice.
- Added 14 fake/offline diagnostic tests: no credential/network in offline mode,
  preserved all cases/hashes, fixed prices/ceilings/exclusivity, unsupported none
  rejected before SDK, original/audio settings preserved, cache-write accounting,
  fail-first/fail-four stop/held reservation, no resume. Two Sol forecast cases
  verify explicit counts, unchanged data assumptions and no hidden reserve.
- Added additive `data_only_with_reserve_usd` to the pure forecast. Existing
  `data_only_usd` and original default workload/totals remain unchanged. At the
  assumed 50k reads/day/5 KiB, data-only is **$1.758307/30 days before reserve**, but
  **$2.197884 including 25%**: above the $2 planning reference, not a guaranteed cap.
  Future [53-call Sol capacity](../output/operation-chat-sol-full-capacity-20261008.json)
  preserves 32 scheduled +20 chat +1 complex and yields **$2.860263/day,
  $85.807884/30 days, $1043.995917/365 days** incl. reserve. The separate
  [20-chat-only scenario](../output/operation-chat-sol-capacity-20261008.json) gives
  $1.085263/$32.557884/$396.120917; do not call a lower workload same-load savings.
  Sol chat-output assumption is 2048; ordinary admission uses the conservative
  cache-write input upper rate, no cache/free-quota discount. Complex Astra is
  previously documented hypothetical capacity, not a called/accepted handler.
  Firestore is still disabled without a delta contract and data volumes unmeasured.
- Final `make verify` **exit 0**: **561 backend/68 UI**, mypy 246 files, TS/lint/
  formatting, 34 dependency checks, Next16.3.8 build, full npm audit zero findings.
  `output/operation-chat-evaluation/sol-final-make-verify.log`; five isolated PG
  tests skipped/two live excluded. Focused diagnostic/forecast **93 passed**;
  secret scan and whitespace checks pass. UI unchanged, no new browser claim.
- OpenAI Docs influenced model-support and price checks before dispatch, not
  semantic acceptance. No source reads, production, `.env`, IAM/key/SSH/audio,
  client-service or schedule changes. Goal still requires model/source acceptance;
  documented prices/forecasts do not establish actual bills or source ownership.

### Server-owned read confirmation and rollback compatibility

- [Contract checkpoint](operation-chat-read-confirmation-checkpoint.md): additive
  response-only `ChatTurn.read_confirmation`, fixed typed access/product_scope/
  cooldown/budget conditions, separate user confirmation and actual capability.
  Parent interval comes from the same setting as its handler; default analysis
  does not invent an unverified numeric interval. Proposal views/discussion,
  planned agents, unavailable/unsupported cards, failures/cancellation and actual
  analysis turns receive no read grant. Product is topic scope, not proved source
  ownership. No new action, source call or background execution from this metadata.
- Conditions are rebuilt on private history/replay from saved intent and current
  availability/configuration without model/provider I/O. The new response field
  is **excluded from persisted turn JSON** to avoid a new unknown key for an older
  strict reader. Existing history/cost rows untouched; this does not certify every
  other uncommitted change's rollback/migration compatibility. DTO is not in the
  model output schema or analysis request; forged request metadata is rejected.
- Eleven added backend cases cover fixed schema/ranges, allowed cards, real ASGI
  replay/restart, no stored policy/grant, zero runs, viewer refusal and disabled
  Parent source refusing an operator before background work. Twelve added UI
  cases cover malformed/legacy/current interval metadata and no policy authority
  in POST; ChatPage passes valid metadata to its existing card. Four admission
  controls visible without new buttons/double confirmation. Existing actual
  executor/admission checks are unchanged and remain authoritative.
- Prompt hash remains `a06137c6f5884c7a5894ef9085e93f3b42268871d1fe0db32773cd7cc3f058db`;
  `ChatReply` fields remain answer/plan/next_action. Paid model score stays 7/8 and
  model/source-owner acceptance remains pending. No paid test/candidate switch;
  archived known $0.239276 and old unknown $0.050128 unchanged.
- Final `make verify` **exit 0**: **572 backend/80 UI**, mypy246 files, formatting/
  Ruff/lint/TS, 34 dependency checks, Next16.3.8 build, full npm audit zero findings.
  Log: `output/operation-chat-evaluation/read-confirmation-compatibility-accepted-make-verify.log`.
  Five isolated PG tests skipped/two live excluded; focused ASGI/chat/Parent/
  fallback **61 passed**, `make audit-schema`, secret scan and whitespace pass.
  Intermediate optional-field TS failure and incorrect fixture-role expectation
  corrected, no gate waiver or failure-log deletion.
- Final isolated fake browser/axe run **exit 0**:
  `output/operation-chat-evaluation/read-confirmation-compatibility-browser.log`;
  Parent min86400, private no-auto-connect session, typed response checked before
  consent, mobile320px warning/button reachable outside details, desktop/mobile
  screenshots visually inspected in `read-confirmation-compatibility-ui-20261008`.
  Fake OTP/private topics/separate-admin approval/fake verification/Parent confirm/
  reload/logout pass. Its own temporary fake DB/processes were cleaned by the
  harness; no existing browser session/data, container or production was changed.
- OpenAI Docs influenced structured-flow isolation and human confirmation, not
  a new provider/Agent Builder integration. No product sources, `.env`, live paid
  API, production, Firebase, IAM/key/SSH/audio/client services or schedule changes.
  Full objective remains active; this guard does not substitute for source
  ownership or complete model-quality evidence.

### Recorded-output delivery replay — no new provider calls

- [Fixed scope](operation-chat-delivery-replay-plan.md) and
  [review/results](operation-chat-delivery-replay-results.md): actual private-history
  delivery through `OperationChatService.detail`, fake owned ports, fixed synthetic
  time, eight Sol/sixteen paired boundary records. Full report rows/scope basis are
  explicitly reconstructed fixtures, not observed owner approval or a fresh trace.
- New CLI refuses incomplete/duplicate/misordered/mismatched evidence, changed
  instructions/fixture contexts, oversized files and unsafe paths. It cannot call
  a model, write a topic, confirm a read or run an agent. Original archive bytes,
  free-form replies/cards/plans/tokens remain unchanged during replay; only current
  response-only policy is projected. Input hashes identify observed files, not an
  external immutable historical signature.
- Manual recorded-delivery review: Sol8/8 utility16/16; mini7/8 utility15/16;
  nano3/8 utility10/16. Server/UI conditions complete the Parent workflow, but
  cannot fix mini's cohort inference or nano's unit mistake/invented textual card
  ID. Original raw scores/gates remain Sol7/8, mini6/8, nano3/8. These known outputs
  do not prove future robustness, independent owner acceptance or production quality.
- Thirty-three new fake/offline cases pass, including actual6h/24h/non-round
  policy intervals, no settings/SDK/HTTP, preserved source dates/archives and safe
  CLI refusals. Current `make verify` **exit0**: **605 backend/80 UI**, mypy248 files,
  formatting/Ruff/ESLint/TS, 34 dependency checks, Next16.3.8 build and npm audit0.
  Log: `output/operation-chat-evaluation/delivery-replay-accepted-make-verify.log`.
  Five isolated PG tests skipped/two live tests excluded; this does not replace
  previously recorded isolated PG/browser/schema evidence. No UI code changed in
  this replay checkpoint, so the preceding fake-browser result remains unchanged.
- No new external model/source charge, reservation or paid party. Known$0.239276
  and old unknown hold$0.050128 unchanged; no refund/retry. Default nano/none,
  prompt/configuration, `.env`, sources, production, Firebase/GA4/backend, IAM/key/
  SSH/audio/client services and schedules untouched. Objective remains active:
  source ownership and representative quality acceptance still need confirmation.
- OpenAI Docs influenced separating model-node correctness from application
  delivery; no hosted Evals/tracing/upload integration was introduced.

### Final isolated PostgreSQL and audit-target safety

- Reviewed current shared source/result cache/ledger code against the objective.
  Deterministic Retention reuse retains facts, original calculation time, product,
  configuration/rules identity and expiry. No additional AI-token savings are
  attributed to a calculation that already had no model call.
- `scripts/postgres_audit.sh` now refuses remote/TCP Docker endpoints before a
  container or migration operation. It respects explicit context precedence,
  pins every operation to the validated local Unix socket using child-command
  environment overrides, and cleans only the immutable ID returned by its own
  successful create. Failed creation/name collision/malformed ID cannot target
  an existing container for cleanup. Docker configuration and caller environment
  are not persisted or changed. Context precedence follows
  [Docker CLI documentation](https://docs.docker.com/reference/cli/docker/#environment-variables).
- Twelve fake shell-harness tests pass: SSH/TCP/loopback TCP refusal, explicit
  context priority, pinned child socket, successful/malformed/failed create and
  failure cleanup. Initial test typing error corrected without a gate waiver.
- Current `make audit-postgres` **exit0**: PostgreSQL17 clean upgrade/downgrade/
  upgrade, `alembic check` no drift, **5 integration tests passed**. Independent
  connections share cost admission/once-only settlement, source single-flight/
  durable denial, immutable product-scoped assessment, chat admission and existing
  run/schedule locks. Authoritative final log:
  `output/operation-chat-evaluation/pinned-postgres-cost-audit-20261008.log`.
  This is isolated database evidence, not a production-source/API verification.
- Current `make verify` **exit0**: **617 backend/80 UI**, mypy249 files, formatting/
  Ruff/ESLint/TS, 34 dependency tests, Next16.3.8 build and npm audit0. Five PG tests
  skipped in this ordinary suite but passed separately above; two live tests
  excluded. Log: `output/operation-chat-evaluation/postgres-safety-accepted-make-verify-20261008.log`.
  Secret scan/whitespace and shell syntax pass. No UI code changed this checkpoint.
- Only temporary audit containers/databases were created and removed; synthetic
  fixtures can be recreated by the script. Existing local containers stayed
  running. No existing database/ledger/key, `.env`, Firebase/GA4/backend, production,
  SSH/IAM/audio/client service or schedule was changed. No paid calls or budget
  settlement; old known charges/unknown hold unchanged. Goal remains active while
  source ownership and representative model-quality acceptance are unresolved.

## Proposed separate rollout and rollback (not executed)

Do not deploy while the full quality gate remains unfinished or the source/model
acceptance prerequisites are missing. Before approval, provide a scoped change manifest, current verification
evidence, accepted source ownership/cohort mapping, a canary budget and rollback
owner to the application's backend developers.

1. Back up the operational database with the owner's approved procedure; retain
   audit/cost rows and secrets. Verify the old and new code/image identifiers.
2. Deploy the additive operational migration/code only with existing schedules
   still disabled and kill switches set as agreed. Do not migrate unrelated apps,
   SSH access, IAM or audio services. Do not downgrade tables containing cost
   reservations as a routine rollback: that would erase budget evidence.
3. Configure one verified source bundle/product and matching engagement product.
   Agree the exact GA4 streams rather than assuming all streams in the shared
   property belong to MANA. Keep automatic Firestore collection disabled.
4. With explicit budget approval, run one bounded manual source cycle. Replaying
   its request key and another equivalent read must not increase provider reads.
   Check original collection dates, product separation, quota counters, sanitized
   logs, unavailable metrics and actual Billing/Monitoring where accessible.
5. Enable a shared six-hour cycle only after a separate schedule approval and an
   accepted canary. Other agents consume saved facts; do not create parallel
   source-owning schedules per agent. New applications need approved mappings.
6. If rejected, stop operational collection/chat admission using scoped switches
   and revert the agreed code/configuration to the known release. Preserve additive
   ledger/cache tables, pending reservations and keys. Do not restart an old unsafe
   full-scan schedule as part of rollback. Confirm audio/client services remain
   healthy using their existing read-only checks; do not modify them.

## Primary references

- [OpenAI spending controller](https://developers.openai.com/cookbook/articles/per_run_spending_controller_responses_api)
- [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
- [OpenAI cache accounting](https://developers.openai.com/api/docs/guides/prompt-caching#monitor-cache-performance)
- [OpenAI prompt cache is not an answer cache](https://developers.openai.com/api/docs/guides/prompt-caching#does-prompt-caching-affect-output-generation)
- [Google service-account OAuth](https://developers.google.com/identity/protocols/oauth2/service-account)
- [Google public JWT signing API](https://google-auth.readthedocs.io/en/latest/reference/google.auth.jwt.html)
- [Firestore billing](https://firebase.google.com/docs/firestore/pricing)
- [urllib3 2.8.0 security fixes](https://github.com/urllib3/urllib3/releases/tag/2.8.0)
- [Prior one-shot evidence](../output/firestore-one-shot-cost-20261005.md)
