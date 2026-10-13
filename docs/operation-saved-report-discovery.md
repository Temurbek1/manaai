# Saved-report discovery: bounded SQL foundation

Status: **local foundation only; not advertised to the model or deployed**.
Production remains `a7752dc`. The broad Codex/Claude workspace objective remains
open; this checkpoint does not fix the deployed catalog by itself.

## Observed gap

`GoalEvidenceTools.reports()` currently fetches twenty latest reports per agent,
then checks verified application scope. `inspect_sources` returns at most twelve
references and has no continuation tool. Recent unverified/other-app reports can
bury a valid source. Absence in that bounded preview must never be taken as proof
that the database is empty or as a reason to repeat an external collection.

The interaction target follows the separation in the official
[Codex App Server thread documentation](https://learn.chatgpt.com/docs/app-server#threads):
paginated observation is distinct from starting/resuming work. Our application
uses its existing FastAPI/SQL ports, not Codex shell commands or a new framework.

## Implemented foundation

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

No native function name/schema, public API/UI, checkpoint version, configuration,
schedule, source binding or production state changes in this checkpoint.
`find_reports()` is callable by the application/tests but is deliberately not
exposed to a model until the compatibility work below is implemented and verified.

## Required next integration (not completed)

1. Add a default-disabled discovery setting and capture it only on new native
   Goals; do not silently upgrade existing v10 histories or their model tool sets.
2. Add strict `find_saved_reports` native schemas and dispatch, exact bounded
   query/cursor/capability arguments, contextual instructions and generic progress.
   An empty preview/page must guide paging/search, not collect new provider data.
3. Introduce an explicit private checkpoint version for the new tool/state (v11),
   retaining original immutable scope, all grants/unknown holds and closed legacy
   projection. `a7752dc` cannot be assumed to execute that new state. Verify the
   actual `2ea7b9a` fallback with native execution disabled, or establish a separately
   tested bridge before choosing a native rollback target.
4. Exercise discovery → reading full saved text → investigation → independent
   review with unchanged original request, parent/child/payment distinctions,
   owner/product isolation, SQL restart, denied/altered cursors, exhausted limits
   and no external read/grant inheritance. Fake completion is not a quality grade.
5. Run full code, PostgreSQL, browser and actual-image compatibility gates. Paid
   model checks remain separately bounded; production release needs scoped approval
   and a fresh backup/drain/protected-state audit. No source refresh is implied.

## Verification

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
