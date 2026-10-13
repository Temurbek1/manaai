# Native catalog quality diagnostic and exact saved-text preservation

Status: **local checkpoint, not deployed**, 2026-10-14 (Asia/Samarkand).
Production remains the independently approved `a7752dc` operational sidecar.
The broader Codex/Claude-style workspace objective remains open. A completed
source read is not a completed analysis or a measured business improvement.

## One independent real-model attempt

`scripts/operation_catalog_goal_evaluate.py` is offline by default. Explicit paid
execution creates one exclusive local SQLite attempt with the actual saved-report
repository, Goal service, native SDK boundary and SQL cost ledger. It uses
`gpt-6.1-sol`/medium, at most twelve calls, 8,192 output tokens per call and a shared
$0.49 admission ceiling. There is no application factory, source adapter,
domain executor, production connection, scheduler or automatic retry. Existing
attempt directories cannot be reopened. The pre-dispatch numerical oracle stays
outside model input; runtime completion would still require semantic review.

The new fixed fixture is distinct from the earlier successful 900/100 case:
800 parents in cohort A, 200 different parents in B, all observation windows
mature at 2026-09-25 UTC. D1 is [24h,48h), D7 [168h,192h) since registration;
the ordered funnel covers each parent's first fourteen fully observed days.
Confirmed fictional payers, misleading tariffs, child counts, activity geography
and DAU/WAU are supplied to test the necessary evidence distinctions. Twenty-three
newer invalid source bindings bury the actual complete report in SQL. Retention
counts are after character 5,000, requiring genuine saved-text paging.

**The one paid attempt did not pass full analytical acceptance.** It discovered
the source and read all 7,607 exact characters, then stopped at conservative
budget admission before producing/reviewing the complete numerical analysis.
Its original full objective, success criteria and constraints remain unchanged.
It was not continued, recreated, refunded, narrowed or given a larger budget.

- Goal `d593d34b-6f68-4c3b-8263-a36e2e58fa43` is waiting in investigation,
  seven steps, `limit_stop=budget`; unknown holds are zero.
- Seven verified calls cost **estimated 259,170 microusd = $0.259170** using
  the configured rate card. This is ledger pricing, not a downloaded billing invoice.
- Trace: initial plan, `inspect_sources`, two `find_saved_reports`,
  `read_saved_report`, two contiguous page reads at offsets 0/4,000.
- Loaded/full hashes match; `shortened=false`, complete quality notes, offset 7,607.
  The final retention observations and exact newline were retained.
- No numerical final answer or independent review exists. The original plan/draft
  remains unfinished; obtaining data alone cannot pass the original success criteria.
- No unknown receipt, source request, grant, action, limit extension or production
  operation was introduced. The terminal diagnostic leaves its SQL Goal waiting;
  there is no worker running that local database.

Ignored original evidence: `output/catalog-quality-20261014/independent-01/`.
The separate main-agent `review.md` records failure/incomplete criteria honestly;
the runner's `semantic_review=pending` receipt is not rewritten as a pass.
This evaluates decisions, tool boundaries and completion together, following
[official trace-grading guidance](https://developers.openai.com/api/docs/guides/trace-grading).

## Exact whitespace bug fixed before paid dispatch

The new mock-SDK workflow initially exposed an existing `ChatModel` inheritance
issue: `str_strip_whitespace=True` stripped leading/trailing characters from
`GoalEvidence.summary`. A contiguous page's newline/space could then disagree with
its saved-text hash/offset. Trimming the fixture or source would hide that defect.

The summary field now explicitly opts out of whitespace stripping. All exact
source characters are preserved, including beginning, page boundaries and tail;
other chat/domain strings retain their existing normalization. Maximum size,
hash validation, freshness, population qualifications and permission checks are
unchanged. No public JSON schema, checkpoint version or migration is changed.
An application/SQL restart regression verifies the complete original text.

The compatibility probe now includes a trailing tab/newline in its exact footer.
The current local image `mana-ai-operation:catalog-whitespace-local-20261014`
(`ddba43a6f0a325e999d03499e8d753ff1f9810bbd7437969251705c3c4eecfbc`)
and actual supported `2ea7b9a` passed networkless synthetic read/pause/rollback
checks before and after pausing. Full private text, captured v11/v2 state,
constraints, consumed reads, unknown holds and grants survive. No customer
configuration or credentials were mounted. Earlier native readers, including
`c59b89c`, are not verified execution fallbacks for these exact-whitespace receipts;
`a7752dc` cannot execute catalog v11/v2 at all. The closed legacy fallback still
requires disabled native execution; never restore an older database over history.

## Context/budget findings, not an implemented optimization

Verified input grew across the seven calls despite four observed provider
compaction events. The final continuation holds 40,326 characters, mostly opaque
compaction content. Its semantics are not readable and must not be guessed.

| Call | Reserved microusd | Known microusd | Input tokens | Output tokens |
| --- | ---: | ---: | ---: | ---: |
| 1 | 129240 | 11351 | 3305 | 309 |
| 2 | 146670 | 9936 | 4609 | 14 |
| 3 | 165213 | 6818 | 6407 | 182 |
| 4 | 187773 | 35579 | 9488 | 1436 |
| 5 | 225188 | 47744 | 14119 | 1350 |
| 6 | 238018 | 64055 | 19402 | 1658 |
| 7 | 273468 | 83687 | 27104 | 1764 |

Reservation is an admission ceiling, not an extra charge. After the last verified
settlement, the next conservative reservation cannot fit the remaining $0.49
budget. Do not claim the actual spend reached $0.49 or weaken safety with a
characters/4 token guess, refunds, a smaller objective or unverified input discount.

Code inspection establishes two avoidable duplication candidates: every
continuation appends a fresh full authoritative Goal snapshot; the latest two tool
records and their provider outputs can repeat page text already present verbatim
in current evidence. This does not establish which part dominates encrypted
provider state, nor permission to prune that state. The current implementation
only prunes before the latest actual server compaction, consistent with
[official server-side compaction guidance](https://developers.openai.com/api/docs/guides/compaction#server-side-compaction).

Next implementation must preserve the same full objective and strong-model
analysis/review, not shorten the supplied report or remove inconvenient criteria:

1. Capture any changed continuation contract only on new opt-in Goals, with a
   private version/scope binding and verified closed legacy rollback. Existing
   tasks, unknown holds, permissions and original conditions remain unchanged.
2. Track exact runtime-owned snapshot provenance/digests. Replace only proven
   superseded runtime snapshots after retaining all authoritative user conditions,
   plan, draft, steering, historical context and full evidence. Never infer provenance
   from an item role/JSON shape, discard provider/user text or inspect opaque reasoning.
3. Avoid duplicate saved-page text only when the exact fingerprint/offset/hash
   proves it already exists verbatim in the authoritative full evidence sent in
   the same request. Keep typed observation receipts and paired tool calls/results;
   do not lose text, quality notes or silently mark a partial source complete.
4. Preserve crash/restart, independent review, control fencing, tool/result pairing,
   compaction-boundary markers and old-version validation. A reconnect must never
   repeat inference or an external read. Fakes and a single real case remain
   different levels of evidence.

An additional possible admission improvement is the documented exact
[`/v1/responses/input_tokens` preflight](https://developers.openai.com/api/docs/guides/token-counting).
The installed SDK has no dedicated helper. Price, opaque-state support and required
request-accounting behavior have not been established for this deployment; **no
token-count endpoint was called**. It is not implemented, a promised free operation
or authority to resume this stopped attempt. Any future integration needs a typed,
bounded receipt tied to the exact unchanged request, conservative failures and no retry.

## Verification and production boundary

Six evaluator tests use the real SDK with mock HTTP plus actual isolated SQL,
covering offline/no-credential behavior, exclusive attempts, full scope, native
catalog/paging/review, known incomplete usage and unknown quota holds. The exact
whitespace restart test adds a seventh new case. No real provider is called by tests;
fake completion is not a semantic-quality grade.

Final `make verify`: **1024 backend / 136 UI**, Ruff lint/format, mypy **333**
tracked source files, TypeScript, production build and zero npm audit vulnerabilities.
Nineteen PostgreSQL tests are skipped in that suite and passed separately in an
isolated PostgreSQL 17 migration round-trip/drift/persistence audit. Two live suites
remain deliberately deselected. OpenAPI/TypeScript synchronization is unchanged.
The extra secret scan retains seven pre-existing fake-key flags in unchanged older
SDK tests, with no new file flagged; its nonzero command is not reported as green.
Browser checks in the prior v11 checkpoint remain historical; no newly authenticated
production-browser analytical flow is claimed here.

A fresh read-only server inventory on this checkpoint confirmed healthy operational
`a7752dc`, main/audio `e73c10a`, UI `0d27000`, scheduler `2ea7b9a` and PostgreSQL.
It did not redeploy/restart anything or change SSH. The separately approved
[a7752dc release](operation-cohort-quality-checkpoint.md#scoped-production-release)
already has backup, rollback and protected-state checks. This local catalog/exact-text
checkpoint is outside that production authorization; no new source, refresh,
schedule, key change, inference or Goal command was sent to production.
