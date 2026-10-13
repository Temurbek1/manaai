# Saved-report discovery: bounded native tool and SQL catalog

Status: **local native integration, default disabled; not deployed**.
Production remains `a7752dc`. The broad Codex/Claude workspace objective remains
open; this checkpoint does not activate the deployed catalog or prove live model quality.

## Observed gap

The pre-discovery `GoalEvidenceTools.reports()` fetches twenty latest reports per agent,
then checks verified application scope. `inspect_sources` returns at most twelve
references and has no continuation tool. Recent unverified/other-app reports can
bury a valid source. Absence in that bounded preview must never be taken as proof
that the database is empty or as a reason to repeat an external collection.

The interaction target follows the separation in the official
[Codex App Server thread documentation](https://learn.chatgpt.com/docs/app-server#threads):
paginated observation is distinct from starting/resuming work. Our application
uses its existing FastAPI/SQL ports, not Codex shell commands or a new framework.

## SQL foundation

- A typed frozen query binds the Goal ID, product, owning/allowed agent identifiers,
  exact literal search, optional capability and a timezone-aware creation cutoff.
- One SQL call returns at most ten candidates plus one look-ahead row. Continuation
  adds one exact-anchor lookup; ordering is `(created_at DESC, report_id DESC)`.
  There is no total-count query, growing offset, automatic page loop or retry.
- Product/capability and literal search prefilters are applied before paging.
  SQL JSON product is **only a coarse filter**: the application rechecks the
  complete existing product/binding contracts, capability, date, agent scope and
  exact substring. SQLite's case-insensitive ASCII `LIKE` cannot broaden results.
- Cursor metadata is closed and bounded to 1,024 characters. Its query digest
  binds every search constraint; SQL also rechecks the exact row and timestamp.
  This is an observation position, **not a signed authorization grant**. It cannot
  grant a source read, inherit a budget or establish full catalog/population coverage.
- Alias-aware candidate discovery retains the existing four-room scope/sharing
  rules. Invalid saved bindings can produce an empty page with a non-null cursor;
  callers must not describe that page as an empty database.
- Results expose only report references, bounded titles, collection dates and
  freshness labels. They contain no report body, contact/child list, raw telemetry
  or grant. Original reports must be separately loaded and revalidated before
  citation or current-data completion. The Goal and its cost/evidence/grants are
  unchanged by the foundation lookup.
- SQL column/payload disagreement fails closed with a controlled integrity error.
  Catalog errors are not added to the existing two-step paging-recovery lane.

The ten-row output bound is **not** a bound on physical SQL rows examined. Literal
text search can scan the local report partitions; this checkpoint adds no full-text
index or migration and does not prove performance on arbitrarily large databases.
The cutoff is a creation-time boundary, not a materialized transaction snapshot.
Cursor replay observes saved SQL, not an external provider or a resumed Goal.

The original foundation checkpoint changed no native function/API/checkpoint or
source configuration. The subsequently implemented native integration is below.

## Captured native integration

- `OPERATION_WORKSPACE_REPORT_DISCOVERY_ENABLED=false` is explicit configuration.
  The server captures it only when creating a new native Goal. Idempotent creation,
  restart, source approvals and limit grants never upgrade an older tool set.
  Repository saves reject changing the captured bit. Runtime disabling stops a
  captured discovery Goal before any generation or approved provider read.
- Strict `find_saved_reports` accepts only `query`, nullable `cursor` and nullable
  `catalog_capability`. The last is a search filter, never `requested_capability`,
  a source approval or a delegation. Native advertisement, parsing, private-window
  validation and dispatch all use the captured setting. Legacy task cursors stay
  limited to 36 characters despite the separate 1,024-character catalog cursor.
- Discovery-enabled `inspect_sources` returns the first scoped catalog page and its
  cursor. Instructions distinguish empty pages, references and loaded evidence;
  the model may page or start a new literal search without collecting a provider.
  SQL scope/binding checks and existing full saved-text reads remain authoritative.
- Private checkpoint **v11** binds the captured tool contract and immutable analysis
  scope, wrapping the existing context/limit invariants. The continuation digest
  includes the captured bit only when enabled, preserving old digests. Legacy-readable
  JSON excludes new fields/tools and is closed for execution. Pre-discovery private
  checkpoints omit the new flag/filter, including pending-call metadata.
- Continuation protocol **v2** is bound exclusively to captured v11 Goals. Its
  pending-tool positions reach 119, under the existing 120-record bound and confirmed
  limits. Protocol v1 retains its twelve-tool bound; old Goals are not converted.
  This fixes a separately found continuation-position ceiling, not automatic budget
  renewal, unlimited history, a larger context window or additional recovery steps.
- Public progress uses only the new static tool name/status and normal plan/result
  events. The UI shows “Поиск сохранённых отчётов” in existing collapsed details;
  no new button or source-refresh control is added. Stream reconnection and reload
  remain observation only. Runtime logs are kept out of Git/build contexts.

The model-tool contract follows the official
[strict function-calling requirements](https://developers.openai.com/api/docs/guides/function-calling#strict-mode).
Capturing it on the task follows the persisted dynamic-tool behavior in
[Codex thread resume](https://learn.chatgpt.com/docs/app-server#start-or-resume-a-thread);
this is an application-specific implementation, not proprietary Codex/Claude parity.

## Release boundary and remaining acceptance

`a7752dc` and earlier native images cannot execute v11/v2 and are **not** a native
rollback target after such a Goal exists. The supported `2ea7b9a` fallback retains
the closed projection/private state with native execution disabled and the established
drain/inspect/pause procedure. Never restore an old database backup over newer work.
The backend and compatible UI must be released together: an old stream parser does
not recognize the new tool name. No production migration is required.

Still required: bounded real-model discovery/analytical-quality acceptance, a scoped
API/Goals-worker/UI production approval, fresh backup/protected-state checks and
authenticated deployed-browser acceptance. No schedule/source activation or refresh
is part of this feature. Fresh GA4 publication and the broader context/action/domain
acceptance remain separate requirements; fake completion is not a quality grade.

## Foundation verification (historical checkpoint)

The new catalog tests cover tied timestamps, stable continuation, post-cutoff
insertion, literal SQL wildcards, product/capability/agent/Goal/cutoff/query binding,
malformed/extra-field/version-coerced cursors, exact anchor revalidation, bounded
SELECTs without COUNT, row/payload integrity, discussion-mode refusal and defensive
adapter-page checks. Application tests find a verified report on the third page
after 22 invalid-binding candidates without changing the Goal or dispatching a source.
They also check exact case, MANA/360REC separation, original room-sharing rules,
reference-only results and the absent native function advertisement.

Final focused catalog/Goals/workspace/report-page regression: **85 passed**, including
**27 new catalog cases**. Isolated PostgreSQL 17 migration round-trip/drift and
**18 persistence/concurrency cases** passed; the new PostgreSQL case exercises JSON
prefilters, literal `%_`, tied keyset pages, replay and scope/anchor refusal on the
actual dialect. These databases are local disposable fixtures, not production.

Final `make verify`: **1006 backend / 135 UI** tests, Ruff lint/format, mypy
**330** tracked source files, TypeScript, production build and zero npm audit
vulnerabilities. Eighteen PostgreSQL tests are skipped in that ordinary suite and
verified separately above; two live suites are deliberately deselected.
OpenAPI/TypeScript generation synchronization passed with no public schema changes.
The extra secret scan retains seven pre-existing fake-key false positives in unchanged
older SDK tests; no new file is flagged. Its nonzero exit is not called a green gate.

Exact ignored evidence: `output/report-catalog-foundation-20261014/`, including
`verify-final.log`, `focused-final.log`, `postgres-final.log`, `schema.log` and
`secret-scan.log`. No paid model call, Firebase/GA4/Manakids/Meta collection,
production operation, new schedule or source activation was performed. A native
discovery/review/browser workflow and actual-image rollback proof for the future
checkpoint are still required; these foundation tests do not establish them.

## Native integration verification

The captured local workflow finds the verified report behind 22 invalid bindings,
reads all 8,000+ characters including the exact tail, then plans/investigates/reviews
the same original objective. It completes in ten fake decisions without source/grant
creation. A separate 103-report fixture stops at the original twelve-step limit;
one exact human-style grant continues the **same** Goal to completion in eighteen
decisions, including fifteen tool records and v2 positions beyond eleven. Budgets,
constraints, unknown holds, original request and consumed-read state are retained.

Further checks cover scoped HTTP/history reads, SQL restart, byte-equivalent older
checkpoint/digest serialization, idempotent create after flag enablement, immutable
capture, altered v11 scope/version/flag, strict schemas, legacy cursor/protocol bounds,
runtime disablement and unknown holds stopping before generation. Real-SDK mocked
responses advertise the new function only for a captured task and retain verified
usage when an unadvertised function is refused. Tests do not call the real provider.

The native browser flow passed: normal chat handoff, three explicit bounded catalog
pages, complete saved text, independent review, SSE observation and result reload
without redispatch. Existing private-task, historical, long transcript/archive,
mobile confirmation, CSRF, owner isolation, sandbox-review and accessibility
regressions also passed. The mobile reviewed-result screenshot was visually inspected.

The final local image `mana-ai-operation:catalog-v11-final-local-20261014`
(`7e9afd91993f943c36ede1b765ed37a9a5dfff9a41f9ac391e006eb6f95f6e3d`),
built on the unchanged `a7752dc` local dependency base, and actual `2ea7b9a` passed
networkless synthetic read/pause/rollback checks. V11/v2 tool metadata, full private
text, grants, unknown holds, consumed reads and constraints are retained. No customer
database, configuration or credentials were mounted; the image was not published.

Final `make verify`: **1017 backend / 136 UI** tests, Ruff lint/format, mypy
**331** tracked source files, TypeScript, production build and zero npm audit
vulnerabilities. Nineteen PostgreSQL cases are skipped in that ordinary run and
verified separately in an isolated PostgreSQL 17 migration round-trip/drift audit;
two live suites remain deselected. The new PostgreSQL case retains v11 capture,
the long cursor, unknown costs and closed legacy projection across restart, and
refuses changing the captured bit. OpenAPI/TypeScript synchronization passed.
Eleven new native cases include the extended eighteen-decision workflow and v1/v2
bounds; the focused Goals/continuation regression passed with 53 cases before the
last protocol-bound case, which also passed in the final full suite.
The extra secret scanner retains the same seven pre-existing fake-key flags in
unchanged older SDK tests; its nonzero exit is not a green security gate.

Initial failures were test-harness admission/typing/header/fixed-price and fixture
ordering mistakes, corrected before final gates. A first audit launch failed to
open its log directory before executing anything; the subsequent isolated audit
passed. No production attempt, provider retry, ledger refund or old Goal replay
resulted from those local setup failures.
Ignored evidence: `output/report-discovery-v11-20261014/`. There were no paid model
calls, new Firebase/GA4/Manakids/Meta reads, production operations or key/SSH changes.
