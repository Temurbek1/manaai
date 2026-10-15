# Contact tool result continuation — local, default disabled

This advances the full agent workspace objective, not a production release or full
Codex/Claude parity. Production remains the separately documented RU/UZ release.
There is no new migration, source read, real contact, paid inference, schedule change,
SSH access or deployment in this increment. Goals tools remain read-only.

## Contract and original context

`OPERATION_WORKSPACE_CONTACT_TOOL_CONTINUATIONS_ENABLED=false` is the default. It
also requires the existing native/contact/proposal prerequisites. Only new eligible
MANA Retention/Orchestrator turns may capture `native_contact_preparation_v2`.
Old v1 requests remain request-only: their missing call identifiers/history are
never reconstructed or silently upgraded. The four-agent architecture is unchanged.

The v2 request retains the actual original function call and complete runtime-owned
instructions/context in private chat workspace metadata. Exact digests and the
owner/topic/turn-bound selection connect the pending invocation to its later SQL
result. Raw terminal usage is verified before arguments or window validation.
Malformed accompanying prose cannot hide a valid call and is not retained.

Only opaque encrypted reasoning items needed for stateless Responses continuation
are permitted in this new private protocol. Raw reasoning, nonempty reasoning
summaries and provider-supplied execution outputs are rejected, not shortened or
treated as receipts. This does not change v1 storage. Opaque continuation and raw
call identifiers are absent from public response fields and SSE; they grant no
source/action authority. Bounds stop oversized histories without truncating them.

This follows the actual call-ID/output pairing and reasoning-item requirements in
[OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling).
It is an explicit human-deferred host execution/result path, not an invented tool
result generated from prose or a provider-created SQL receipt.

## Human execution and one consumer

The owning Retention lifecycle still performs explicit human-confirmed preparation,
separate approval/peer review, fresh target checks, fake dispatch and verification.
Only two fictional adults and immutable RU/UZ templates are supported. V2 derives
one preparation request ID from the original invocation, not each UI nonce: repeated
preparation clicks cannot create multiple proposals for the same native call.
V1/manual behavior remains unchanged. There is no automatic sharing, approval or send.

A separate human `POST .../retention-contacts/continue` identifies the saved action,
fingerprint and observed revision with literal confirmation. It accepts no provider
output, instructions, recipient override or model window. Access, product, original
selection and current SQL action binding are checked before admission. The result
is an explicitly dated SQL observation, including fake acceptance or uncertainty,
never proof of real delivery, current customer eligibility or business improvement.

The existing cross-process chat fence atomically creates one continuation turn and
claims the originating invocation before inference I/O. A new nonce, concurrent
request, lost response or process replacement observes that same SQL turn; it does
not reissue the model, preparation, source read or send. A failed/unknown continuation
does not free the original call for another attempt. Model reservations remain under
the shared ledger; unknown usage is not refunded or retried.

Before generation, the continuation freezes complete bounded same-topic user
conditions and closed-Goal context through the existing session reader. Conditions
added while waiting for the human step are preserved, not replaced by the original
model snapshot. These quotes/history inherit neither budgets nor grants. Original
context/evidence is retained exactly and labeled historical; the continuation time
does not renew original report freshness. SQL state observation is not a source refresh.

The Responses input contains the original context, retained pending invocation and
opaque items, the exact runtime-owned function output, and the frozen updated session
context. One final model call uses `tool_choice=none`; another tool/action card is
rejected after usage accounting. The original configured model/reasoning and response
language must be preserved. Recipient language and UI language cannot change them.
Conservative admission includes the actual item window/schema, without exact-token
preflight or a cost-reduction claim. Existing SDK and 180-second chat wall limits
remain; this is not an unbounded action loop or Goal budget renewal.

## Interface and history correction

The local v2 card adds one explicit “continue with agent” control. The resulting
answer is an ordinary saved turn in the same chat. Lost answers offer SQL observation,
not another mutation. Refresh/reload uses the authoritative first-page transcript;
RU/UZ labels are localized without rewriting historical messages or template text.

The previous recent-conversation projection omitted the saved native choice, despite
the prompt including a history slot for it. The bounded six-turn SQL read now selects
that exact private choice without fetching entire model windows/session blobs. This
corrects the earlier behavior; the previous checkpoint's passing tests did not prove
that specific history path. Selected parameters remain historical, not approvals.

## Verification scope and open acceptance

Pinned-SDK mock HTTP/application tests cover the actual native call → human fake
preparation/action → paired SQL result → final model response. They include new user
conditions, one preparation per invocation, concurrent continuation, scope/role/revision
denials, malformed/pending/missing/timeout usage, injected new calls and restart with
no redispatch. Raw/summary reasoning, missing opaque state and provider receipts fail
after verified pricing. These are synthetic wire/application tests, not real-model
semantic quality or real customer-contact acceptance.

Separate local PostgreSQL and actual closed-old-image compatibility checks are
required for the new consumed-pair state. Only closed `2ea7b9a` with native execution
disabled is a proposed fallback; previous native readers cannot execute this metadata.
Never downgrade populated private tables or restore an old database over new history.
Actual results are recorded below only after their processes finish.

The private fake browser covers two personal reviewer logins, one fake acceptance,
owner-only continuation, response-language preservation across an Uzbek UI switch,
reload, 320px layout and accessibility. The independent ordinary-answer stream belongs
in Growth, where contact tools are unavailable; eligible contact turns are deliberately
nonstreamed. This is not authenticated production-browser acceptance.

Remaining acceptance includes broader real-model/source quality, owning capability/
admin-control registration, bounded multi-action planning, live individual billing/
consent/channel authority, measurable outcomes and candidate-image/scoped release/
rollback. This increment does not establish full workspace readiness or permission
to deploy the contact migrations/features. The overall goal remains active.

## Measured engineering evidence

- Focused SDK/application/session/peer suite: 58 passed before the later stop-fence
  case (`output/contact-loop-final-focused.log`). This is mock HTTP, not paid inference.
- Focused UI: 41 passed, including lost continuation answer and SQL observation
  (`output/contact-loop-ui.log`). The new stop-fence case is included in the full suite.
- PostgreSQL: 28 passed with migration/drift checks, including the two-connection
  single-consumer fixture (`output/contact-loop-postgres-fixed.log`). That fixture
  tests SQL pairing, not real receiver or full production-load behavior.
- Actual networkless closed `2ea7b9a` read/pause/reconstruction passed with the retained
  v2 opaque window, consumed result/failed child and v15/v14 Goal state
  (`output/contact-loop-compat.log`). This is not a candidate-image or production rollback.
- Complete private fake browser passed with the new contact/result flow and the
  independent streaming regression in Growth (`output/contact-loop-browser-final.log`).
  The final current-harness serial run also passed after the full gate
  (`output/contact-loop-browser-serial.log`). Its 320px continued-answer screenshot
  was visually inspected: Uzbek interface, original Russian answer, no overflow
  (`output/contact-loop-browser-serial/contact-tool-continuation-mobile.png`). These
  are fake-model/local-browser checks, not semantic or deployed acceptance.
- Schema sync, secret/quality-marker scans and Compose passed on SSD
  (`output/contact-loop-schema-security-ssd.log`); mypy passed for 381 files.
- Complete `make verify` passed: 1335 backend tests passed, 28 skipped and two live
  tests deselected; 188 UI tests passed. Formatting, lint, mypy (381 files), TypeScript,
  production UI build and npm audit (zero vulnerabilities) also passed
  (`output/contact-loop-verify-formatted.log`). Skipped/live tests are not acceptance
  of real providers or production. The original process exited successfully; it was
  not restarted because observation crossed a conversation turn.

Failed attempts remain separate evidence: an initial test-factory return-placement
mistake, an already-valid revision used as a denial fixture, a malformed synthetic
account ref, and an invalid SessionMemory attribute caught by type checking were
corrected before final verification. Browser attempts first exceeded Chromium's Unix
socket path limit, then exposed a future-noon fake clock and an incompatible streaming
test room. The real clock/policy were not changed. An unformatted UI test stopped the
initial full gate before tests. Subsequent visual reruns exposed a fake OTP-harness
race on the owner's second login: it selected the previously consumed code before
the new input rendered. The harness now waits for a new sink row and the OTP field;
real authentication is unchanged. A later harness readiness check initially looked
for an ARIA attribute instead of the existing associated label; it now waits for the
actual enabled composer after availability resolves. A parallel browser attempt also
hit a local SQLite authentication lock under the full-suite disk load. These are not
successful browser runs; the final successful browser run was serial after the full
gate. Jest/schema staging also hit an explicit `/tmp` disk quota; SSD reruns do not
delete unrelated files or weaken SQL durability. These failed attempts are not
rewritten as passes.
