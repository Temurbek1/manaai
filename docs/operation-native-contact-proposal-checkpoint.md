# Native contact preparation request — local, default disabled

This advances the full workspace objective, not a production release or a live contact
executor. It builds on the [frozen contact lane](operation-retention-contact-chat-checkpoint.md)
and [personal-session peer review](operation-retention-peer-review-checkpoint.md).
Production, main/audio, SSH, keys, Firebase/GA4, sources and schedules are not changed.

## What the native tool actually does

`OPERATION_WORKSPACE_CONTACT_TOOL_PROPOSALS_ENABLED=false` is the default. It also
requires the existing contact/native prerequisites. Only new native MANA Retention or
Orchestrator turns may capture `native_contact_preparation_v1`; old turns are not upgraded.
Growth, Technical, 360REC and ordinary discussion cannot use it. There is still exactly
four top-level agents. Goals tools remain read-only and receive no contact mutation tool.

The actual Responses function `request_retention_contact_preparation` accepts exactly
two fixed fictional-recipient aliases and two fixed templates. It cannot set an account,
message body, locale override, reviewer, consent, source grant or provider payload.
Strict schema/closed enums, one call and `parallel_tool_calls=false` are enforced. Multiple
calls, extra/duplicate arguments, unknown functions or provider-supplied function outputs
fail closed. The function saves a request for human-confirmed preparation in the turn;
it does not read the contact target, prepare a domain action, share, approve or send.

Raw terminal usage is settled before validating this call. Native calls are handled before
parsing any accompanying structured text, so malformed prose cannot hide a valid request.
Unverifiable/nonterminal usage retains its reservation and creates no request. Valid priced
invalid arguments keep their cost; no parser correction, fallback API call or retry is added.
The conservative admission includes the exact configured tool definitions in its existing
byte/schema bound. This is not exact token preflight or a new provider-price claim.

Eligible turns use one nonstreamed Responses call, including ordinary replies where the
model chooses no function. Existing SQL observation/progress remains; token streaming for
this native selection profile is not implemented. No second request is started to obtain
prose after a native call. The public explanation is server-owned RU/UZ text and does not
reuse unvalidated provider prose or claim that a message has been sent.

## Frozen choice and human lifecycle

The runtime captures the native profile before generation and binds the selected parameters
and hashed provider call identifier to owner/topic/turn with a server fingerprint. A request
is a pending choice, not a SQL execution receipt, approval, evidence or grant. The raw call
identifier, provider reasoning and accompanying invalid text are not persisted. New fields
stay only in private workspace chat metadata, outside both legacy-readable JSON projections.
There is no new physical migration or Goal checkpoint version; existing contact-bearing
Goals remain v15 and do not inherit this pending request as authority.

The UI displays the agent's fixed choice instead of asking the user to repeat both selectors.
Human preparation sends that fingerprint and the same parameters. A mismatch is denied before
the owning service reads a target. The ordinary typed contact policy/lifecycle then applies;
the separately chosen reviewer and exact approval still require their own confirmations.
Request replay, reload and restart keep the same choice and never invoke the model again.
Old manual turns remain manual; setting the new flag cannot change their original contract.

The bounded recent six-turn conversational history may quote the selected aliases/template
as historical requests, explicitly not approvals or delivery. This is not unlimited history,
fresh evidence, a resumed provider reasoning session or inherited permissions. Older missing
choices must not be reconstructed. Completed contact outcomes retain the existing minimized
SQL history/unknown-hold rules.

This follows the native call/host-execution distinction in
[OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling).
**It is a deferred, request-only function checkpoint, not the complete generic
function-call/output/model-continuation loop.** Supplying a native tool result back to the
model after human execution, durable pairing/continuation for that lane and broader owning
capability registration remain open. Do not relabel this as full Codex/Claude parity.

## Evidence boundary and remaining acceptance

Actual pinned-SDK tests use only mock HTTP. They exercise a real `function_call` accompanied
by invalid private text, verified pricing before argument failure, unknown usage holds,
parallel/unknown/spoofed calls, parameter scoping and the budget-schema bound. Application/
SQL tests exercise no target read before confirmation, no parameter replacement, replay/
restart, private projection and refusal of a text-only imitation of the native call. The
native path does not open a model stream or a fallback request.

The actual fake browser exercises selected parameters → explicit preparation → personal
two-account peer review → one fake acceptance → reload and RU/UZ/mobile/accessibility.
Its model port is fake, not a real-model quality test. SDK/native-wire acceptance is tested
separately above. The actual closed `2ea7b9a` image is checked against the new private chat
selection plus existing v15/v14 context in a networkless synthetic database. Only that
closed fallback with execution disabled is eligible for this local compatibility claim;
`e413696`, `38cdac4` and intermediate native readers do not understand the new metadata.
This is not a candidate-image/production rollback. Never downgrade or restore private history.

An initial `/tmp` full-suite attempt and its focused recheck failed with SQLite disk I/O
errors. That temporary filesystem held approximately 3 GB of local files; the exact
quota/filesystem cause was not established. Their logs remain negative evidence. The
unmodified suite passed in a new SSD temporary directory, without deleting unrelated
files, reducing tests or weakening SQL durability. The failed attempts remain in
`output/native-contact-verify.log` and `output/native-contact-runtime-final.log`;
the successful complete run is `output/native-contact-verify-ssd.log`.

Measured local checks (overlapping suites, not additive coverage):

- Pinned SDK/native HTTP and inference-receipt regression: 73 passed, mock HTTP only
  (`output/native-contact-sdk-cases.log`).
- Native/application/session/peer regression on SSD: 46 passed
  (`output/native-contact-runtime-ssd.log`).
- Personal two-user browser, selected native request and explicit preparation/review:
  passed (`output/native-contact-browser.log`). The Uzbek mobile result screenshot
  was visually inspected; this is a local fake environment, not production-browser acceptance.
- Actual closed `2ea7b9a` application compatibility, including pause/reconstruction and
  retained v15/v14 state: passed (`output/native-contact-compat.log`).
- Separate local PostgreSQL migration drift and existing contact/peer locking suite:
  27 passed (`output/native-contact-postgres.log`). No new native-specific PostgreSQL
  execution flow is claimed.
- OpenAPI/client sync, secret/quality-marker scans and Compose validation passed
  (`output/native-contact-schema-security.log`); mypy passed for 377 source files.
- Complete `make verify` passed: 1322 backend tests, 27 expected PostgreSQL skips
  covered by the separate run above, two opt-in live cases deselected; 186 UI tests,
  formatting/lint/type checks and production Next.js build passed. npm audit reported
  zero vulnerabilities. The generated Next type references returned to their committed
  production paths after the build; no development-only generated-file change is included.

Full real-model semantic evaluation, the complete post-execution tool-result loop, candidate
release/rollback, live individual billing/consent/channel authority and measured business
outcomes remain unaccepted. There was no paid model call, live source read, customer contact,
production migration/deployment or source/schedule activation in this checkpoint.
