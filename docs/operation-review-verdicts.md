# Independent full-scope verdict without regenerating the report

Status: **local, default disabled, not deployed**, 2026-10-14 (Asia/Samarkand).
The broader administration workspace objective remains open. Last verified
production release is `a7752dc`; this checkpoint changes no production state.

## Contract and rationale

The existing review phase asks for another `GoalDecisionBody`, including a complete
draft and plan. A reviewer can instead return findings and a verdict on the exact
already-written artifact, as in [official Codex structured phase handoffs](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex#define-structured-outputs).
This does **not** establish why the previous diagnostic did not finish review,
promise a token/dollar saving or weaken the original analysis/review criteria.

`OPERATION_WORKSPACE_REVIEW_VERDICTS_ENABLED=false` is captured only on new tracked
native paged-catalog Goals. It requires the existing native workspace, continuation,
explicit-limit tracking, catalog discovery, snapshot replacement and exact-page
projection contract. Its current scoped implementation does not upgrade old tasks
or claim support in the legacy analysis lane. It adds no new button or fifth agent.
Old request replay retains its original bit; saves reject changing it. Runtime or
adapter disablement stops the captured task before another model request.

Private checkpoint **v14** and continuation **v5** bind the new semantics to the
same owner/product/original request/quoted conditions. Older checkpoint/protocol
serializers omit the new fields and retain their digests. No migration or historical
rewrite occurs. The public read-only flag is optional in the UI compatibility type.
The latest receipt is private SQL state, omitted from authenticated public Goal
responses and from the next model snapshot. Saved private completion requires it;
the public projection does not falsely claim that the receipt was deleted.

## Full input, bounded structured output

Investigation still produces the complete original analysis. Independent review
starts with a fresh native input, not the investigator's opaque reasoning. It gets
the complete unchanged original objective, success criteria, constraints, steering,
quoted session conditions, plan, evidence text/qualifications and stored draft.
The runtime adds only two hashes and a fixed descriptor; no source/user text is
summarized to fit. Descriptor bytes count toward existing context/cost admission.

`GoalReviewVerdictBody` contains input/draft hashes, exact quoted checks of the
objective and success criteria, checked plan positions, conditions/evidence flags,
loaded evidence references, `accepted|revise|waiting` and public feedback.
There is no rewritten draft/plan, source request or action field. The SDK uses
the separate strict schema only for the captured review phase, following
[official Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

Quotes may be contiguous fragments but must concatenate to the **entire exact**
original target, without dropped words, normalization, reordering or a prefix
substitute. Acceptance requires every check passed, conditions and evidence
checked, all original plan positions exactly accounted for, and loaded citations.
Hash mismatches, duplicate/unknown positions, missing criteria or extra fields
are rejected. These are technical binding/coverage checks, **not proof that a
model's semantic judgment is correct**. Real-model quality and manual numerical
review remain necessary.

The adapter and application revalidate the verdict against the same frozen input.
Accepted output preserves the already stored draft verbatim and only marks the
original checked plan items done. The existing source/date/product/freshness/
full-text completion policy still gates Goal completion. Waiting preserves the
draft. Revision preserves the draft and returns to investigation with the exact
bounded public critique labelled historical model opinion, not fresh evidence.
The next independent review does not inherit that critique as its own reasoning.

The latest private receipt binds the completed draft and retains all quoted target
text. Private SQL read/write validation requires the accepted proof; HTTP projections
omit the receipt and remain valid. An initial REST regression reproduced a 500 when
that private invariant was mistakenly applied to the public projection; it was fixed
without exposing the receipt or weakening persistence validation.

## Safety and compatibility

Raw verified pricing still precedes schema/verdict validation. Invalid completed
decisions share the existing two-step corrective limit and unchanged budgets; their
feedback names the correct review schema. Incomplete/pending responses, timeouts,
unknown usage and lost source reads still stop and preserve their applicable holds.
No SDK retry, lower-strength model, output/context/step/dollar increase, source
approval, auto-refresh, schedule, provider polling or financial/contact mutation
is introduced. In-flight pause/steering revisions fence the stale verdict; only
verified costs reconcile. The receipt is historical context, never permission.

The standalone catalog evaluator adds optional `--review-verdicts` with
`--project-saved-pages`. The full original 800/200-parent fixture, all 7607 source
characters, oracle outside model input, `gpt-6.1-sol`/medium, 8192 output ceiling,
twelve-call/$0.49 ceiling and no-source/no-production policy remain unchanged.
Default execution is offline; existing attempt directories cannot be reopened.
No prior incomplete or unknown-cost Goal is resumed/recreated or relabelled a pass.

New v14/v5 cannot be executed by `1b5582e`, `a7752dc` or the older native readers.
The supported `2ea7b9a` fallback must keep native execution disabled, preserve
private state/holds and use the drain/inspect/pause procedure. Never restore an
older database over populated workspace history. A future production update needs
separate scoped approval, backup and protected-state checks.

## Verification

Twenty-eight focused domain/SDK/SQL/HTTP cases cover full Unicode quote coverage,
strict booleans, hash/criterion/citation/plan rejection, separate schema and exact
full input, one model attempt, known incomplete/pending holds, v14 restart/tamper,
old idempotent capture, runtime disablement, accepted/revised/waiting/pause paths,
private receipt and valid public GET. Four more real-SDK/mock-HTTP catalog cases
exercise the complete discovery/page/analysis/new-review flow and failure fences.
Two isolated PostgreSQL cases add complete/noncomplete private receipt, full draft,
v5 continuation, immutable original request and unknown hold across connections.
Fakes prove mechanics, not business measurements or semantic quality.

Local browser → API → SQL → fake-model/tool → verdict → unchanged report passed,
including stream/reconnect, reload without redispatch, full saved-report tail,
long-session conditions, explicit human limits/lost replies, owner isolation,
CSRF and mobile accessibility. The reviewed mobile result was inspected.
No logged-in customer/browser session or source provider was used.

The current local image `mana-ai-operation:review-verdict-v14-local-20261014`
(`4833b71f0b3f446cfbf3a68d81ab3c5b63689bb4caee74e4a7db8f021b58364f`)
and actual `2ea7b9a` passed networkless read/pause/rollback, retaining a nonempty
historical receipt, quoted conditions, exact source tail, page provenance, consumed
reads, explicit limits and unknown holds. No credentials/customer configuration
were mounted or image deployed. Full final gates and any new independent paid
diagnostic are recorded below after completion.

Final `make verify` passed: **1179 backend /136 UI tests**, Ruff lint/format,
mypy **344** files, TypeScript, production UI build and zero npm audit vulnerabilities.
Twenty-three PostgreSQL cases skipped there passed separately in the isolated local
PostgreSQL17 migration up/down/drift/persistence audit. Two live suites remain
deliberately deselected. OpenAPI/TypeScript synchronization passed. The final
production build restored browser-dev-generated `next-env.d.ts`. Initial local
typing/formatting and the public-projection regression were corrected before gates.

## One new independent real-model diagnostic

After all local gates, one exclusive `--project-saved-pages --review-verdicts` party
used the unchanged full fixture, strong model and 12-call/$0.49 ceiling. It loaded
all 7607 source characters but stopped in investigation on call 8. The safely retained
facts now identify `provider_status=incomplete; incomplete_reason=max_output_tokens`.
There is no full numerical analysis or v14 reviewer output, so **the original full
acceptance did not pass and the new review contract has not been real-model verified**.

Goal `4833cf7d-39f6-4e14-a589-74f2847bf7ab` is waiting at step 8, recoveries 0,
limit_stop null, review_receipt null. Eight priced receipts total an estimated
**265862 microusd = $0.265862**, unknown hold 0, not a billing invoice. Last reported
usage was 28516 input /3024 output tokens; the reason is not proof that all 8192
allowed tokens were generated or that a larger bound alone would fix it.
The [documented reason](https://developers.openai.com/api/docs/guides/reasoning#allocating-space-for-reasoning)
can also cover a context limit; raw private reasoning was
not inspected and no speculative cause or saving is claimed.

Source/grant/action/extension/production attempts 0, original request unchanged,
full/loaded source hashes equal. No second paid party, retry, limit increase or
weaker/narrower replacement followed. All previous protected attempts remain
untouched. Original ignored evidence and separate honest manual review:
`output/review-verdict-quality-20261014/independent-01/`. Result SHA-256:
`f378e8e3087880e77edaf6fc3bed2d186a8bc93e78149f07758415b3e5943e45`.
The validation/data-quality skills require all original metrics, grain, definitions,
dates and caveats; an absent answer and unexecuted review are not graded a pass.
Current prices were checked against [official API pricing](https://developers.openai.com/api/docs/pricing).

Logs: `/tmp/manaai-review-verdict-*`; ignored browser evidence:
`output/review-verdict-v14-20261014/browser/`. The extra secret scan still flags
seven pre-existing synthetic keys in unchanged SDK tests; that nonzero result is
not called a successful security gate. No key, SSH, Firebase/GA4, source, schedule,
main API/audio or production setting was changed.

## Independent review-stage pair, not full-loop acceptance

One new party subsequently exercised the isolated review stage on two fresh
handwritten synthetic artifacts, not prior model results or stopped tasks.
`scripts/operation_review_verdict_evaluate.py` is offline by default, uses an
exclusive directory and one shared two-call/$0.49 ledger, and stops the whole
party on any unknown hold. There is no application factory, Goals worker, source
executor or production connection. `catalog_request()` is shared with the full-loop
evaluator without changing any original objective, criteria, constraints or limits. Both stage
inputs retain all 7607 source characters; only one pooled-D7 formula differs.
Expected labels and manual arithmetic are outside model input. No test calls a
real provider; the paid CLI is an explicit separate opt-in diagnostic.

The actual `gpt-6.1-sol`/medium reviewer accepted the correct analysis and revised
the erroneous `(25%+50%)/2=37.5%`, identifying `(200+100)/(800+200)=30%` and preserving
the other correct metrics and caveats. Full quote/hash/plan/citation bindings passed
and neither stored draft was rewritten. Two priced calls estimated **$0.052719**
(26969+25750 microusd), unknown hold 0, under the single shared budget. This is not
a billing invoice or a model-quality rate. Rates were checked against
[official API pricing](https://developers.openai.com/api/docs/pricing).
Output 8192 and test-only 210/240 timeouts
were unchanged from the preceding diagnostic; no retry/second party followed.

Separate manual validation recomputed every requested metric and inspected both
verdicts, scope, dates, denominators, priorities and caveats. Both verdicts explicitly
note that supplied text does not prove catalog-discovery history. Thus the positive
acceptance establishes this **review-stage pair only**, not full original Goal
acceptance, generated analysis, worker/UI completion, long-history review or real
MANA measurement. The full-loop failure above remains untouched. Original ignored
evidence and separate review: `output/review-stage-quality-20261014/independent-01/`.
Original result SHA-256:
`a60f3bdaafb756ac9afbc330133d166df7affacdd9129ba27fba7a0447d33a46`.

Ten new offline cases cover plan-only/exclusive admission, exact full inputs,
expected-label isolation, strict SDK output, false acceptance exposure, binding
failure, incomplete/pending/timeout/quota receipts and no retry/next case after
unknown usage. Combined review/catalog suites passed 53 tests. Final `make verify`
passed **1189 backend /136 UI**, Ruff, mypy 346 files, TypeScript/build and npm audit.
The 23 PostgreSQL cases remain skipped there and unchanged; no persistence/runtime
contract was changed by this evaluator. Local source-fixture whitespace issues were
resolved before the paid run; the source itself was never trimmed. Production,
sources, schedules, SSH, keys and all prior evidence/unknown holds remain unchanged.
The validation/data-quality skills keep this stage result qualified and the broader
workspace acceptance open, rather than equating two expected verdicts with readiness.

The following [deferred-compaction checkpoint](operation-compaction-quality-checkpoint.md)
passed one complete model-driven original catalog/analysis/review task with manual
full-criteria verification. It neither relabels the earlier incomplete attempt nor
closes broader acceptance, and remains local without source/production activation.

Remaining acceptance: broader strong-model full-task quality,
broader quality cases, corrected fresh GA4/deployed-browser flows, scalable extended
session context and Retention-first governed actions before full Orchestrator and
Technical. This feature alone does not close the full Codex/Claude-style objective.
