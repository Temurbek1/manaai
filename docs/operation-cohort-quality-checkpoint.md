# Complete historical cohort analysis and bounded schema feedback

Status: **local diagnostic/implementation, not a new production release**.
The operational sidecar remains the approved `b81f458` inference-receipt release.
This work advances the existing four-agent workspace, not a fifth agent or full
Codex/Claude parity. The broad objective remains open.

## One complete real-model analysis, not a replay

`scripts/operation_cohort_goal_evaluate.py` is offline by default. Its explicit
paid mode creates one new local SQLite Goal in a previously nonexistent directory,
with at most six model calls and $0.49 accounting admission. It starts no app
factory, source adapter, scheduler or production connection. Existing attempts
cannot be resumed or recreated; an unknown receipt stops the party. It neither
extends budgets nor issues read/action grants. The oracle is local grading context
only, never model input; completed workflow state is not automatically a quality grade.

The pinned test asks for a **complete historical analysis of a supplied synthetic
parent-cohort fixture**. It does not narrow or relabel a current-data customer task.
Counts and exact windows are fixed before dispatch: cohort A has 900 registered
parents, B has 100 distinct parents; D1 means [24h,48h), D7 [168h,192h) after
registration; the ordered funnel covers each parent's first fully observed 14 days.
These are fixture definitions, not a claim about GA4 calendar-day cohort identity.
Confirmed fictional payers are intentionally supplied alongside misleading tariff,
child, DAU/WAU and geography aggregates to test evidence distinctions.

The one new `gpt-6.1-sol`/medium Goal completed with its exact original request,
all five public tasks done, complete dated saved evidence and independent review:

- Four transitions: 80%, 50%, 75%, 50%; losses 180, 360, 90, 135.
- Overall payment conversion in the **fixture**: 135/900 = 15%, not tariff labels.
- D1 A = 60%; D7 A = 20%; D7 B = 60%; comparison −40 pp / −66.67% relative.
- Weighted pooled D7 = 240/1000 = **24%**, not unweighted 40%.
- Largest absolute loss is linking (360 parents); linking/payment tie at 50%
  relative loss. No individual churn cause or D1/D7 group intersection is invented.
- The answer separates parent/child populations, rejects activity geography as
  sales, and proposes measured hypotheses without claiming contacts/actions/lift.

Main-agent semantic review independently checked all original criteria and
additional arithmetic in the final 8,215-character Russian analysis. This is
one case, not a statistical model-quality score or real customer outcome.

Six priced calls used **137,379 microusd = estimated $0.137379**, unknown holds
zero, source attempts zero, production changes zero. The fourth call produced
a known-priced invalid decision; existing bounded recovery corrected it without
a source read or grant. Its exact schema failure was **not retained**, so its cause
must not be guessed. Two provider compaction events were observed; this does not
prove unlimited history or broad long-session acceptance. No prior failed party
or production Goal was rerun or reconciled by this success.

Ignored exact evidence: `output/cohort-quality-20261013/independent-01/`, including
fixed plan/oracle, Goal ID, per-step public state, original cost receipt and the
separate `review.md` assessment. The runner's original `semantic_review=pending`
receipt is not rewritten after manual review.

## Local safe diagnostic improvement

The evaluated failure exposed an observability gap: recovery had only generic
format feedback. The subsequent code adds typed **allowlisted field + error-code**
facts for verified decision-schema failures. This improvement was implemented
after the paid case and has not received another paid quality party.

Only Pydantic errors belonging to `GoalDecisionBody`/`GoalDecision` qualify.
At most three unique closed facts are emitted. Root/nested plan fields and error
codes are validated again at the application port. Inputs, provider messages,
extra-key names, custom error types, URLs, context dictionaries and raw answer
text are never included. An unrelated SDK-metadata validation failure retains
known usage but does **not** enter the decision-correction lane.

Examples such as `draft: string_too_long` or `plan.status: literal_error` are
server-derived schema facts, not evidence, user instructions or permissions.
The next model receives them in the existing private `model_feedback.message`.
Public progress remains generic and never exposes internal reasoning/tool results.
The original objective, complete conditions, evidence, budgets and shared
two-recovery-step ceiling stay unchanged. No direct tool redispatch occurs.
Unknown usage, lost requests, source failures and unsafe continuations still stop.

No schema, checkpoint version, route or UI contract changes. Existing v7/v10
readers retain the same message shape and closed legacy projection. Source
approvals, global/Goal cost holds, schedules and production configuration are
unchanged. The evaluator is an opt-in local diagnostic, not an installed job.

## Verification and remaining acceptance

Thirteen initial SDK/application feedback tests passed; a further test verifies
that unrelated SDK-metadata validation cannot become decision correction. The
combined feedback/continuation/fault/evaluator suite passed **73 tests** without
real provider calls. Six evaluator tests cover offline defaults, exclusive attempts,
full original historical scope, strict native tools, independent review, known
incomplete usage and unknown quota holds. Their fake workflows do not grade quality.

Isolated PostgreSQL migration round-trip/drift and **17 persistence/concurrency
tests** passed. Native browser regression passed with fake models/providers:
same-room handoff, durable progress/reconnect, questions, reviewed results, retained
conditions, historical mode, 110-turn/105-Goal/report paging, sandbox review,
lost-reply observation, owner isolation, CSRF, mobile controls and accessibility.
The local image `mana-ai-operation:decision-feedback-final-20261013-local`
(`cb57bafa811d678794068d86c85937583ff4a83edaeb5bee40cd337fbe0d0c7b`)
and actual supported `2ea7b9a` passed networkless synthetic read/pause/rollback
checks, preserving private state, grants, unknown holds and consumed reads.
No customer or production configuration was mounted.

Final `make verify` passed: **979 backend / 135 UI**, Ruff lint/format,
mypy (328 files), TypeScript, production build and zero npm audit vulnerabilities.
Seventeen PostgreSQL tests are skipped in that ordinary suite and verified
separately above; two live suites are deliberately deselected. OpenAPI/UI public
schemas and the production-generated `next-env.d.ts` remain unchanged.
Full final code/UI gates are recorded in `output/cohort-quality-20261013/checkpoint/`.
The additional secret scanner has seven pre-existing false positives for explicit
`synthetic-only`/`synthetic-key` SDK fixture credentials in unchanged older tests;
no new file is flagged. This is not reported as a green secret-scan command.

Outstanding: approved production rollout of the new diagnostic; broader model
quality coverage; corrected live GA4 publication; authenticated production-browser
acceptance; scalable extended session context; Retention-first owning-domain actions,
then full Orchestrator and Technical last. A completed fixture analysis does not
close those requirements or prove real retention improvement.

This evaluates the whole decision/tool/review trace, following
[official OpenAI trace-grading guidance](https://developers.openai.com/api/docs/guides/trace-grading),
without exposing private reasoning or introducing an LLM judge.
