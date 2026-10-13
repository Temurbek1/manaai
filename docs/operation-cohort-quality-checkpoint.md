# Complete historical cohort analysis and bounded schema feedback

Status: **bounded schema-feedback diagnostic deployed to the operational sidecar
on 2026-10-14 (Asia/Samarkand)**, immutable commit
`a7752dc3c8a0d0c4a8db14c2620826551d9c3e5d`. The complete synthetic analysis remains
a separate local quality diagnostic, not a production customer measurement.
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

Outstanding: broader model quality coverage; corrected live GA4 publication;
authenticated production-browser acceptance; scalable extended session context;
Retention-first owning-domain actions, then full Orchestrator and Technical last.
A completed fixture analysis does not
close those requirements or prove real retention improvement.

## Scoped production release

Explicit owner approval covered only the operational API and its single in-process
Goals worker. The candidate uses a clean `git archive a7752dc` application overlay
on the exact existing `b81f458` runtime; immutable base identity and dependency-layer
prefix were verified. No UI, main/audio, scheduler, provider, SSH or source change
was included. No migration or production database restore was needed.

- Runtime: `mana-ai-operation:a7752dc`, image
  `sha256:36de524c701947b39e5c2f9142ebf48f4d241819d06a188a1b6315dd440a67d6`.
  The container is healthy with `APP_ENV=production`. Its original environment,
  mounts and host configuration match exactly; workspace, Goals, worker and
  explicit-limit flags are restored, and the sidecar scheduler remains disabled.
- Root-only backup: `/var/backups/mana-ai/decision-feedback-a7752dc`, including
  the existing container/configuration inventory and a custom PostgreSQL dump
  of 1,771,571 bytes, SHA-256
  `7abff83078bc0674ea2ced1380b0bc810214beba5d410910764e4c5eec4181f4`.
  `pg_restore --list` verified the dump; it was not restored.
- Fresh preflight/drain/stage/final SQL inspections found no queued/running Goal,
  lease, active chat turn or source run. Admission/execution were temporarily
  disabled for staging, then the exact prior flags were restored.
- Actual candidate, `b81f458` and `2ea7b9a` images passed networkless synthetic
  read/pause compatibility checks, retaining private state, consumed reads,
  unknown holds and grants. A pure candidate schema probe passed without
  settings/provider I/O. Its first invocation selected the installed package
  because the external probe omitted the working-directory import path; fixing
  the probe resolved this without changing application startup or release code.
- Main/audio `e73c10a`, UI `0d27000`, scheduler `2ea7b9a` and PostgreSQL retained
  their exact container IDs, starts, configurations and mounts. All **34** protected
  original files, including credentials, SSH, Nginx and public Swagger assets,
  retained their hashes.
- Seven source configurations, six schedule configurations, two source gates,
  controls and schema `a36d9f7b802c` retained their SQL fingerprints. Schedule
  comparison excludes only ordinary `next_run_at`/`last_run_at` progression,
  not enabled flags, cron, scope or circuit configuration. No auto-refresh,
  listener, source activation, cooldown reset or new schedule was introduced.
- All three original unknown reservation rows retained their full fingerprint.
  Goal `cd91c5e9-07fd-4959-ba4b-15ed51498e66` retained its complete state:
  waiting in review, revision 16, four steps, conservative accounted $0.215847
  including unknown hold $0.157238. It was not resumed, extended or retried.
- Authenticated read-only API availability matched the pre-release result.
  Public main health, Swagger/schema/assets and frontend GETs passed; existing
  capability authentication still denies anonymous requests and accepts the
  unchanged token. The unauthenticated frontend operational proxy returns 401.
  The same proxy accepts an authenticated availability GET with the unchanged
  technical key and advertises the original enabled flags and 120-step/$0.50 ceilings.
  An isolated browser rendered the protected login and, after expanding the
  initially collapsed Swagger tag, all twelve product contracts without page errors.
  The first browser assertion incorrectly expected expanded contracts; the corrected
  read-only check passed without any docs/application change or inference POST.
  Release verification made **zero model inferences, external source reads,
  actions or Goal commands**. A public login-page check is not authenticated
  production-browser Goal acceptance.

The compatible application-only rollback is the immediately previous `b81f458`
image with the same environment/mounts and private v10 state. Drain admission and
inspect active work before switching; retain unknown holds and never overwrite
newer SQL history with the backup. The separate `2ea7b9a` legacy fallback still
requires the established pause procedure and disabled native execution.
The initial 30-second health observation expired while Docker reported `starting`;
the subsequent exact runtime check confirmed `healthy`, not an unhealthy rollback.

Ignored release evidence: `output/decision-feedback-release-20261013/`.
The source-catalog paging investigation is not implemented or included in this release.

This evaluates the whole decision/tool/review trace, following
[official OpenAI trace-grading guidance](https://developers.openai.com/api/docs/guides/trace-grading),
without exposing private reasoning or introducing an LLM judge.
