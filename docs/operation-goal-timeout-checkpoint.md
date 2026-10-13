# Explicit Goal model timeouts and incomplete v13 quality diagnostic

Status: **local checkpoint, not deployed**, 2026-10-14 (Asia/Samarkand).
The last verified production release is the separately approved `a7752dc` sidecar;
no production operation was performed in this checkpoint.
The full Codex/Claude-style workspace objective remains open.

## One new independent full-scope diagnostic

After the [exact page projection checkpoint](operation-saved-page-projection.md),
one new exclusive `--project-saved-pages` attempt used the unchanged complete
800/200-parent synthetic catalog/cohort fixture, original objective/criteria,
`gpt-6.1-sol`/medium, 8192 output tokens, twelve-call and $0.49 ceilings.
No previous attempt was replayed and the numerical oracle stayed outside model input.

**This attempt did not pass analytical acceptance.** Goal
`84052efc-d9d4-4fa3-92e6-b7c538cc2037` discovered and loaded all 7607 characters,
then stopped on its eighth model request without a verified usage receipt.
It is waiting in investigation, eight steps, no limit-stop marker or recovery.
The result remains a scope declaration, with no complete numerical draft or
independent review; its five plan entries remain pending. Source acquisition
alone does not satisfy the original full analytical success criteria.

| Accounting | Microusd | USD |
| --- | ---: | ---: |
| Seven verified receipts, estimated by the configured rate card | 164365 | 0.164365 |
| Eighth request, unknown outcome retained as a hold | 301848 | 0.301848 |
| Conservative Goal total | 466213 | 0.466213 |

These are priced usage and a reservation, not a billing invoice or $0.466213
confirmed spend. The original local SQL Goal and all prior protected holds remain
untouched. Do not refund, resume, recreate or extend the lost request. There was
no second paid party after this stop and no recurring worker for its local database.
No source reads/grants, limit extensions, external actions or production changes occurred.

The safe journal reports a timeout, with 120.142982 seconds between the last page
completion and stop, consistent with the then-hardcoded SDK HTTP timeout of 120
seconds. The model's enclosing wall-clock timeout was 180 seconds. This is not a
quota or budget stop. Provider/network latency and success with a longer deadline
are unknown; neither full quality nor a percentage/dollar optimization is inferred
by comparing this incomplete trace with the older budget-stopped attempt.

Original ignored evidence and separate manual review:
`output/page-projection-quality-20261014/independent-01/`.
Original result SHA-256:
`dc615fc46c5d4f2c542b6149150c90c8658be6642601b17f8a1dad4751101ff3`.
The runner's `semantic_review=pending` remains unchanged; `review.md` records
incomplete acceptance separately. Full/loaded text hashes match and the final
retention observations/whitespace remain. Evaluation includes the tool and
completion trace, following [official trace-grading guidance](https://developers.openai.com/api/docs/guides/trace-grading).

## Local configuration change

Two explicit settings replace hardcoded model-only limits while preserving defaults:

- `OPERATION_GOALS_REQUEST_TIMEOUT_SECONDS=120`: SDK HTTP timeout, range 1–230.
- `OPERATION_GOALS_MODEL_STEP_TIMEOUT_SECONDS=180`: encompassing model-call
  wall-clock timeout, range 11–240, at least ten seconds greater than the SDK setting.

The SDK timeout is not a total end-to-end wall timer; the installed SDK passes it
to HTTPX. The application timeout surrounds both native continuation and the legacy
model call, including local continuation/receipt processing within that call.
The 240-second maximum leaves sixty seconds below the current five-minute SQL
claim lease; the direct service constructor also rejects unsafe values.
This margin is not a SQL performance guarantee or a lease heartbeat implementation.

`AsyncOpenAI(max_retries=0)` remains mandatory. The existing one-time cost admission,
raw receipt validation, conservative unknown holds, two shared known-recovery steps,
objective/scope, strong model and output/context/step/dollar bounds are unchanged.
An application model-wall timeout now uses the same sanitized timeout message as
the SDK error, not a generic request to clarify the objective. The separately
approved external-source branch retains its hardcoded 180-second bound and
consumes its grant before I/O; it is not governed by these model settings.

The official [error guidance](https://developers.openai.com/api/docs/guides/error-codes#python-library-error-types)
classifies `APITimeoutError` as timeout. Its generic retry suggestion does **not**
override MANA's stricter unknown-receipt/no-replay policy. No automatic retry,
background polling or cached approval is introduced. A timeout setting cannot
release an existing unknown hold or grant permission to read any source.

All four local Goal evaluators wire the same validated model-wall setting.
The catalog evaluator additionally records only allowlisted durations/retry
count in `runtime-configuration.json`.
Offline execution still loads no credentials. Existing directories remain
exclusive; no key, provider body or opaque continuation is written to that receipt.
An explicit 210/240-second override is possible for a future independent bounded
diagnostic, but has not been used in another real call or on production here.

## Verification and remaining acceptance

Focused tests cover default preservation, invalid/nonfinite/unsafe settings,
SDK timeout wiring with retries disabled, real asyncio cancellation using a
shortened test-only deadline, native timeout classification, unchanged
180-second separately approved fake read, unknown-hold persistence and denial
of resume/limit extension after SQL restart. Real SDK/mock HTTP catalog tests
cover both v11/v2 and v13/v4 under custom settings, one timeout attempt only,
retained original request and Goal/global unknown holds. No automated test uses
the real OpenAI API or a live Firebase/GA4 source.

Final `make verify` passed after the browser audit and final evaluator wiring:
**1105 backend / 136 UI tests**, Ruff lint/format, mypy **339** files,
TypeScript, production UI build and zero npm audit vulnerabilities. Twenty-one
PostgreSQL cases skipped in that suite passed separately in an isolated local
PostgreSQL 17 migration up/down/drift/concurrency/persistence audit. Two live suites
remain deliberately deselected. The focused SDK/service/evaluator checks passed
**52 tests**. OpenAPI/TypeScript synchronization passed. Initial missing fake-key,
dynamic-base typing and formatting issues were corrected before the final gates.

The local user story was chat Goal submission → authenticated workspace API →
private SQL catalog/text pages → fake native model/tools/review → displayed result.
All boundaries passed in the separate local browser session: complete saved text,
review, stream/reconnect, reload without redispatch, original-condition handoff,
explicit human limits and lost replies, owner isolation, CSRF and mobile accessibility.
The reviewed-result screenshot was inspected. This verifies the ordinary workspace
flow, **not** a real-model numerical pass or a browser reproduction of the timeout;
the latter's cancellation/cost safety is established by the SDK/service/SQL tests above.
No logged-in customer/browser session or live source was used. The verification
workflow prompted this boundary-by-boundary check rather than relying on unit tests.

The additional secret scan returned nonzero for seven pre-existing synthetic-key
flags in unchanged older SDK tests; no new file was flagged. It is not reported
as a successful security gate. Logs: `/tmp/manaai-goal-timeouts-*`; ignored browser
evidence: `output/goal-timeouts-20261014/browser/`. The production build restored
the browser-dev-generated `next-env.d.ts`; there is no committed UI change.
The original diagnostic result and SQLite hashes still match the manual review.

No public schema,
checkpoint/protocol, migration, UI, source configuration, schedule or production
environment is changed. The existing v13 closed legacy fallback boundary remains;
`a7752dc` still cannot execute v13/v4. This is not a new deployment/rollback proof.

Still required: a full independent strong-model numerical analysis and review,
broader quality coverage, fresh GA4 and deployed-browser acceptance, scalable
session context and the Retention-first governed action roadmap. A future scoped
production release needs its own approval, backup and protected-state checks.
