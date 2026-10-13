# Exact saved-page references without duplicate evidence text

Status: **local, default disabled, not deployed**, 2026-10-14 (Asia/Samarkand).
Production remains `a7752dc`. This advances the full native workspace objective;
it is not full Codex/Claude parity, real-model analytical acceptance or business lift.

The subsequent [independent diagnostic/timeout checkpoint](operation-goal-timeout-checkpoint.md)
loaded all exact source text but stopped on an eighth-call timeout with an unknown
hold before full analysis/review. It does not convert this local fixture proof into
real-model acceptance or a production release, and the original attempt is retained.

## Contract

`OPERATION_WORKSPACE_PAGE_PROJECTION_ENABLED=false` captures a server-owned
`page_projection_enabled` bit only on new tracked native catalog Goals with
snapshot replacement and continuation enabled. It is not a `GoalCreate` option,
source grant, extra read, schedule or automatic budget extension. Creation replay
and restart retain the original bit; repository saves reject changing it.
Runtime or model-adapter disablement stops before further requests. Existing
native/source/unknown-cost guards and original objective remain authoritative.

Private checkpoint **v13** wraps the existing context and limit invariants;
continuation **v4** binds this new output representation to owner, product,
original request, quoted conditions and captured contract. Older v1/v2/v3 and
checkpoint serialization omit the new fields. No old task is upgraded and no
SQL migration/history rewrite is needed. The public read-only flag is optional
in the UI compatibility type; no new button or setup step is introduced.

## Exact proof, not a summary

The original `read_saved_report_page` result remains unchanged in SQL. Only the
model-facing copy and pending native function result may replace repeated `text`
with `text_reference`. All original non-text fields remain, including offsets,
continuation and the explicit warning that reading is not population coverage.

Projection requires a completed, unshortened, exactly typed local page receipt,
the original report/offset arguments, exactly one same-product evidence item,
validated loaded hash/offset, original total length and a verbatim matching slice
of the text **already present in that same model input**. Leading/trailing spaces,
newlines and Unicode are included. The pointer names `goal.evidence.summary`,
the range length and page/source/whole-text hashes. It is not a URL or executable
query. An unknown extra field, denied/truncated result, changed page, incomplete
span, different product or missing reading receipt refuses projection. Small
receipts/tails retain their original representation instead of larger metadata.

Successfully projected journal copies bypass only the existing 320-character
old-result projection, preserving the complete pointer. Full evidence, all
qualifications, dates, original constraints, steering, plan/draft and SQL receipts
are not shortened or modified. A pointer is neither a partial-text flag nor a
claim that a prefix sample/cohort/purchase population is complete. Original
freshness/completion checks and independent review remain unchanged.

Private `PageOutputRef` metadata records the runtime-created function-output
position/hash, exact SQL tool position/call identity and typed page proof.
Only the runtime appending the proven result creates it; provider lookalikes
are never selected by JSON shape. Domain/persistence validates ordered unique
positions and hashes, and the adapter rechecks the exact output and current
SQL/evidence proof before generation. Snapshot replacement rebinds positions,
not tool identities. The native invocation/result pairing remains intact.

If a retained projected output loses its exact source, receipt or identity,
continuation stops before model I/O. It does not guess missing text, fetch a
provider, regenerate the output or enter the local paging-correction lane.
An actual server compaction prunes/rebinds provenance only with its removed
items; opaque state is not inspected/rewritten. Independent review starts
with complete current saved evidence, not the investigator's opaque history.

The output is an application-specific string representation permitted by
[official function-calling guidance](https://developers.openai.com/api/docs/guides/function-calling).
Provider item chaining/compaction still follows the
[official stateless continuation rules](https://developers.openai.com/api/docs/guides/compaction#server-side-compaction).
This does not replace SDK validation, increase model/context/page limits,
weaken budget admission or change `gpt-6.1-sol`/medium/8,192-output-token settings.

## Verification

Thirty new tests cover Unicode/whitespace spans, all non-text fields, small-tail
fallback, exact context/SQL separation, completed native discovery/full-read/review,
idempotent old capture, v13 restart/tamper rejection, v4 pending pairing/rebinding,
compaction/review, lost sources/receipts, corrupt provenance and runtime disablement.
The fake complete task retains the original objective and entire source; it is
not a semantic/model-quality grade.

The isolated real-SDK/mock-HTTP evaluator now covers both old v11/v2 and new
v13/v4 workflows, including known incomplete usage and unknown quota holds.
Its optional `--project-saved-pages` mode changes the captured runtime only:
the full historical 800/200-parent fixture, oracle outside model input,
twelve-call/$0.49 ceiling, strong model, original criteria and no-source policy
remain. Default execution is offline and never loads credentials; paid mode
requires a fresh exclusive directory. No paid attempt was run in this checkpoint.
The previously stopped diagnostic was not resumed/recreated or relabelled a pass.

One synthetic pending-page input measured **64,483 versus 72,139 serialized bytes**
with identical original request/source, reflecting the saved function-output copy.
These are bytes, not priced tokens, invoices or a guaranteed saving. Actual service
snapshots additionally use the proved journal projection. No character/token discount
or unverified preflight was added to admission.

Final `make verify`: **1081 backend / 136 UI**, Ruff lint/format, mypy **338** files,
TypeScript, production build and zero npm audit vulnerabilities. Twenty-one skipped
PostgreSQL cases passed separately in an isolated PostgreSQL 17 migration round-trip/
drift/persistence audit. The additional case retains exact nonempty page provenance,
full source, original unprojected receipt, original request and unknown hold after
restart, with a closed legacy projection. Two live suites remain deselected.
OpenAPI/TypeScript synchronization passed. The extra secret scan still has seven
pre-existing synthetic-key flags in unchanged SDK tests; its nonzero result is
not reported as a successful security gate.

The browser → API → isolated SQL → fake-model/tool → UI story passed: scoped
handoff, stream/reconnect, inline clarification, independent review, full report
tail and catalog paging, result reload without redispatch, historical follow-up,
110-turn/105-Goal conditions, explicit limit grant/lost reply, synthetic Growth
review, owner isolation, CSRF and mobile accessibility. The reviewed mobile
result was visually inspected. There was no logged-in customer/Firebase session
or production/browser inference; this is not deployed acceptance.

Actual local image `mana-ai-operation:page-projection-v13-local-20261014`
(`f6368719d2322ea93ed0337f6d9fbf293cc0ca4c9c33849e483ec4b559df25c2`)
and supported `2ea7b9a` passed networkless read/pause/rollback. Nonempty v4
provenance, exact source whitespace, raw receipts, conditions, explicit grants,
consumed-read state and unknown holds survive. No customer configuration or
credentials were mounted. No image was deployed/published.

Ignored evidence: `output/page-projection-v13-20261014/`. The initial native
fixture left an older queued Goal, so the worker correctly claimed that task;
cancelling the synthetic old task fixed the harness without changing scheduling
or weakening the requested objective. Initial local typing/formatting issues
were corrected before final gates. The production build restored dev-generated
`next-env.d.ts`. No keys, SSH, source data, schedules or production state changed.

## Remaining work and release boundary

New v13/v4 cannot be executed by `a7752dc`, `dfe098f` or older native readers.
Only the closed `2ea7b9a` fallback is verified, with native execution disabled
and the established drain/inspect/pause procedure. Preserve private state and
unknown holds; never restore an old database over newer work. A scoped future
API/worker/UI release requires approval, backup and fresh protected-state checks.

Still needed: a new bounded independent full strong-model analysis and review,
broader quality coverage, exact input-token preflight only if price/support is
verified, corrected fresh GA4/deployed-browser acceptance, scalable session
context beyond explicit limits and the Retention-first governed action roadmap.
There were **zero paid calls or live source reads** here. The full objective is open.
