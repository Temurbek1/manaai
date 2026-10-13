# Completion diagnostics, pending usage holds and partial full-analysis QA

Status: **local checkpoint, not deployed**, 2026-10-14 (Asia/Samarkand).
The last verified production release remains `a7752dc`; production was not touched.
The full Codex/Claude-style administration workspace objective remains open.

## One independent real-model diagnostic

After [explicit timeouts](operation-goal-timeout-checkpoint.md), one new exclusive
local v13/v4 catalog attempt kept the original 800/200-parent historical synthetic
fixture, all7607 source characters, objective, criteria and constraints. The model
was unchanged `gpt-6.1-sol`/medium,8192 output tokens, at most12 calls and$0.49.
Only this child process used SDK HTTP/model-wall limits210/240; `.env`, production
defaults and every previous stopped Goal remained unchanged. No source adapter,
scheduler, live write, replay or paid model judge was assembled.

**The complete draft is numerically sound, but full runtime acceptance did not pass.**
Goal `b5a408d6-2389-468e-95df-9108dca3b10d` discovered the buried report, read both
contiguous pages and produced the complete analysis at step8. Manual review
independently verified all four funnel transitions85/50/80/50%, losses120/340/68/136,
overall confirmed fictional-payer conversion17%, D1 A65%, D7 A/B25/50%, delta−25pp,
relative−50% and weighted pooled D7=30%. It preserves the dated fictional scope,
parent/child and tariff/payment distinctions, no geographic sales/causal/lift claim,
prioritized hypotheses and a future measurement plan without executed actions.

The ninth response did not complete independent review. The Goal is waiting in
review, nine steps, no limit-stop marker, with the last plan task active. Eight
nonzero receipts total an **estimated256739microusd=$0.256739**. The ninth stored
record reports input/output0 and cost0, so the pre-fix ledger has unknown hold0.
This is reported accounting, not an invoice or proof of zero billing on that
request. Completion status/reason were discarded, so neither its exact reason
nor the finality of that last receipt can be established retrospectively.
Do not label it an output-limit error, filter, pending work, quota or timeout.

The SQL-reservation-to-event interval was about136.51 seconds for step8 and147.54
for step9. Step8 reached review under the new test-only allowance. Full/source hashes match, original request
retained, source attempts/grants/actions/extensions/production changes0. No second
paid party followed. The original `semantic_review=pending` receipt remains;
separate `review.md` records verified draft numbers and the incomplete runtime.
The previous timeout/budget/lost-receipt Goals are not resumed, recreated or refunded.

Ignored original evidence: `output/timeout-quality-20261014/independent-01/`.
Result SHA-256: `841f5573f1946ee56efbbb6c13302b779459cf00723d3c31c3b0610838127448`.
The validation/data-quality workflow required all original metrics, population,
dates and unsupported alternatives to be reviewed, not just a completed status.
This follows [official trace grading](https://developers.openai.com/api/docs/guides/trace-grading).
Configured rates were checked against [official pricing](https://developers.openai.com/api/docs/pricing).
It remains one fictional case, not broad quality, live MANA measurement or business lift.

## Completion facts survive safely

The model adapter already supplies bounded `provider_status` and
`incomplete_reason` after priced raw usage. The service previously discarded
those facts when persisting the safe stop message. `GoalModelResponseError` now
formats at most two allowlisted facts into the existing waiting reason/event:
`provider_status=…`, and `incomplete_reason=…` only with status`incomplete`.
Allowed reason values are`max_output_tokens` and`content_filter`; arbitrary text,
unrecognized status, mismatched reason, raw bodies/error messages, identifiers,
extra-key names and opaque reasoning never enter that feedback.

This is diagnostic observation, not corrective model feedback or new authority.
No native checkpoint, public schema, migration, UI, recovery cap, budget or tool
set changes. Known incomplete/failed/cancelled answers still stop; unknown holds
remain protected. No automatic retry, output-limit increase, source grant, polling
or manual replay of this diagnostic is introduced. Existing private-state/closed
legacy rollback boundaries remain unchanged, not newly deployment-verified here.

[Official reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning#allocating-space-for-reasoning)
describes the explicit`max_output_tokens` completion reason and warns that no
visible answer can still consume input/reasoning tokens. That is why current
raw priced usage is retained before answer validation and why this unrecorded
last failure must not be retroactively diagnosed from an empty answer.

## Pending usage never settles

Inspection plus12 initially failing real-SDK/mock-HTTP tests showed that explicit
`queued`/`in_progress` payloads with numeric usage—including all zeros—could settle
the admission hold before the noncompleted answer was rejected. These are not
final request states according to [official background-mode guidance](https://developers.openai.com/api/docs/guides/background).

A shared adapter-boundary check now refuses that provisional receipt in all three
operational lanes: native/legacy Goals, blocking chat and raw-SDK streamed chat.
It retains both global and Goal-local worst-case holds, stops safely, and cannot
resume/extend a tracked Goal without reconciliation. Even a named SSE
`response.completed` event cannot make its explicit pending payload final.
The stop retains only the closed pending-status fact with `unknown_usage`;
arbitrary values and unrelated error kinds cannot acquire that label. This
does not settle any cost or turn the pending request into a completed response.
Typed final pricing still precedes answer/schema validation; malformed answer/error
metadata do not erase a known receipt. The guarded two pending statuses are not
the same as terminal`incomplete`. No background mode, provider polling, second
request, altered SDK retries or token-coercing stream decoder is enabled.

This forward safety fix does not change the already stopped diagnostic's SQL or
retroactively reconstruct its missing status. The reported zero last receipt is
not used as proof that future pending responses are free or safely repeatable.

## Verification and remaining acceptance

Forty-two new hermetic cases cover closed/coherent diagnostic facts, known zero/
nonzero incomplete usage, private metadata rejection, one SDK attempt, SQL/HTTP
restart, all three pending-receipt lanes and refused resume/extensions with holds.
The initial regressions reproduced18 lost-diagnostic and12 premature-settlement
failures before the corresponding fixes. Ninety-five focused tests passed after
the initial fixes, including existing malformed-metadata and strict raw stream regressions.
No automated test calls OpenAI or a live Firebase/GA4 source.

Full quality gates and local flow checks are recorded after completion below.
The extra secret scanner still reports the same seven pre-existing synthetic-key
flags in unchanged older SDK tests; its nonzero result is not called green.

Final `make verify` passed after the last pending-status safety/diagnostic changes:
**1147 backend /136 UI tests**, Ruff lint/format, mypy **341** files, TypeScript,
production UI build and zero npm audit vulnerabilities. Twenty-one PostgreSQL cases
skipped there passed separately in an isolated PostgreSQL17 migration round-trip/
drift/persistence audit; two live suites remain deselected. OpenAPI/TypeScript
synchronization is unchanged. No migration or generated UI/client change is committed.

The ordinary local browser story passed: authenticated chat → operational API →
isolated SQL saved catalog/pages → fake native model/tools/review → displayed
result, stream/reconnect and reload without redispatch. It also retained full
original conditions through long sessions, explicit limits/lost replies, owner
isolation, CSRF and mobile accessibility. The reviewed-result screenshot was
inspected. This is ordinary fake-model/browser regression evidence, **not** a
browser completion of the failed real-model review or pending-response rendering;
SDK/service/SQL/HTTP tests above prove the new stop/hold paths. The final label
addition changes only the existing safe string, not UI/schema contracts.
The final production build restored browser-dev-generated `next-env.d.ts`.
Logs: `/tmp/manaai-completion-receipt-*`; ignored browser evidence:
`output/completion-receipt-20261014/browser/`. The `verification` workflow prompted
this boundary-by-boundary check without using a logged-in customer session.
Original current/previous diagnostic JSON and SQLite fingerprints remain unchanged.

Still needed: complete independent model review/full catalog acceptance, broader
strong-model quality cases, corrected fresh GA4 and deployed-browser acceptance,
scalable extended session context and Retention-first governed actions before
full Orchestrator/Technical delivery. Exact token preflight pricing/opaque-state
support remain unverified; no count endpoint or character/token discount was used.
A future production release requires its own scoped approval and protected-state
backup/rollback checks. No key, SSH, source data, schedule, main API/audio or
production configuration was changed here.
