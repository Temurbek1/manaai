# Native family source transport — local checkpoint, 2026-10-24

This increment implements the provider protocol needed for model-selected reads,
not a source dispatcher or a completed autonomous agent. The active objective is
still the entire single-chat system in `mana-autonomous-agents-plan.md`.
`OpenAIChildSourceModel` is not installed in the worker/runtime; no source read,
model generation, SQL upgrade, contact, refresh or production change is activated.
The actual server source runtime from `6fe9db3` remains separately available.

## Implemented contracts

`domain/source_tools.py` defines a private host-bound family scope, child aliases,
one strict `read_child_battery` call and an exact encrypted continuation. The
provider can choose only an advertised `child-N` alias. Parent/child IDs and an
invocation UUID stay in the host scope; they are not function parameters. Both
ID and alias mappings must be unique. Extra or duplicate JSON arguments, foreign
aliases, unsupported functions, multiple calls and provisional items fail closed.

`application/source_tool_ports.py` keeps the model interface independent of the
SDK, SQLite and HTTP. These private prompt/receipt objects are not public API
schemas, permission grants or an alternative parent chat.

`services/child_source_model.py` extends the existing specialist transport using
the pinned OpenAI 2.53.0 SDK and its raw response boundary. New explicit methods
send a strict function schema with parallel calls disabled, `store=false`,
standard tier and truncation disabled. The count request carries the same input,
schema, tools, reasoning and tool-choice settings as generation. Ordinary
`count_input`/`respond` remain the old tool-free specialist protocol.

Strict raw terminal usage was extracted without changing its validation into
`services/chat_usage_receipt.py`, shared with ordinary chat. Numeric strings,
booleans, negatives, mismatched totals and nonterminal receipts do not create
usage. Verified terminal usage survives all subsequent native-output failures.
There is no transport retry, fallback model or second hidden request.

Native calls take priority over accompanying assistant text. That text is neither
published nor retained in the continuation. Only the exact validated call and
bounded encrypted reasoning items survive, in their original order. Raw reasoning,
summaries, provider-supplied tool outputs and arbitrary execution receipts are
refused. Function `status=completed` is argument completion, not source execution.
The caller still must settle the raw receipt in SQL before dispatching anything.

An input digest binds the original objective/messages, schema, family mapping,
invocation, configured model and reasoning effort. The server derives a source
request UUID from that invocation and the exact original call, including its IDs
and unmodified argument string. Follow-up inference requires an actual completed
source receipt matching parent, child and that request UUID. Another call ID,
argument representation, invocation or old same-child receipt cannot substitute
for it. Hashes ensure fidelity; they do not replace host authorization or a
durable SQL claim.

The tool result hides parent/child/request/snapshot IDs and retains measurement,
server-write and collection dates with their original quality. An unknown
measurement date remains unknown. The final model call is bound to the original
call ID with `tool_choice=none`; a new native call is rejected with verified usage,
not dispatched. The final text still needs existing owning-domain validation and
Parent-Touch publication, rather than being sent to a parent by this transport.

Official OpenAI documentation checked before this work:
[function-call handling](https://developers.openai.com/api/docs/guides/function-calling#handling-function-calls),
[strict schemas](https://developers.openai.com/api/docs/guides/function-calling#strict-mode).
The installed SDK count signature was also inspected. Model defaults/pins remain
unchanged; newer models in documentation examples were not substituted.

## Required next integration

The next step is a captured, new-turn-only Child-Safety SQL workflow, not merely
enabling this adapter. Existing synchronous/review/source histories must keep
their original protocol. No automatic upgrade or retry of old tasks is allowed.

1. Capture native eligibility only on new admitted review turns outside legacy
   JSON, with an explicit private schema/profile and current-code closed reader.
   Preserve existing v1–v10 data, source-cache v2 and every unknown hold. The
   established v10 commercial base can supply a future private v11 adapter with
   its other capability flags disabled unless independently enabled. This is a
   design option, not an implemented migration or permission to force commercial
   actions onto safety-only installations.
2. Keep the same safety job and its shared **2000 global tokens/day** ledger for
   both model calls. Reserve once under existing ceilings. Atomically append each
   verified raw receipt, partial input/output totals and remaining hold before
   validating/dispatching its choice. A lost second receipt must retain the
   first known cost plus the remaining unknown hold; no refund, new-day reset or
   job/token expansion. Existing one-call `record_usage` is insufficient.
3. Freeze the exact host scope, input, native choice and continuation before one
   `FamilySourceService` read. Bind its existing source ledger/request before
   I/O. Reconcile only exact SQL observations; lost preparation/dispatch/result
   acknowledgements must never trigger a new source/model request automatically.
4. Continue the same review after a completed source receipt, with fresh complete
   child ownership and unchanged parent intent/history/language. Preserve
   encrypted input/call pairing, current lease/publication fences and all costs.
   Code must enforce the count/output remainder before each model call. Do not
   narrow the request or silently enlarge budgets to obtain a final answer.
5. Use a captured compact host prompt for native turns while retaining every
   admitted parent word, dated fact and qualification. Existing verbose review
   prompts plus repeated context may not fit two actual calls inside 2000 tokens;
   exact real count/model acceptance is required. A fake count of 100 is not
   evidence of production budget capacity. Old turns retain their old prompt.
6. Feed a validated specialist result through the existing review-first broker;
   only Parent-Touch may communicate. Coordinate a consumed source change with
   the source-to-safety consumer so the same analytical context is not paid for
   repeatedly. Preserve independent legitimate consumers without granting push,
   tariff or device-control authority.
7. Extend fictional lab and restart/stop/unknown tests, then run bounded real
   source/model acceptance and packaged closed-reader checks. Do not replay
   earlier real source/model parties. GA4/admin aggregate tools, other telemetry,
   09:00/15:00 collection and the other specialists remain separate obligations.

## Evidence

The tests exercise the actual pinned SDK via MockTransport. They cover exact
schema/count/creation parameters, both reasoning/call orders, faithful original
arguments, alias/receipt/call pairing, unknown measurement time, priced invalid
outputs, unsupported calls, forged outputs, raw/summary reasoning refusal,
unknown usage, lost receipts, provider errors and no transport retry. They also
check that ordinary specialist requests retain their old tool-free protocol.
No test executes a source/tool, grants a tariff or calls a real model.

The initial static check found three model-name narrowing errors, corrected
before final checks. The final focused suite passed **105 cases** (native SDK,
existing chat adapters and source-cache tests; overlapping other suites) in
`output/native-source-transport-focused-final.log`.

Full `make verify` process **7988** finished with terminal exit **0**:
**1138 backend tests passed**, one skipped and two opt-in live tests excluded;
**26 admin tests /11 suites** and **seven lab controller tests** passed.
Formatting/Ruff/ESLint (including its 34 compatibility cases), strict mypy
**308 files**, TypeScript, Next production build and npm audit (zero
vulnerabilities) passed. See `output/native-source-transport-verify.log`.
The security scan passed **535 tracked/unignored files** and diff checks passed.
No source dependency/model version was changed. No real model/Firebase/GA4 call,
browser run, candidate-image test, schema upgrade or production action occurred
in this increment; prior parties/real source receipts were not replayed.

These checks do not prove the not-yet-integrated SQL workflow, real model
quality, live source selection, production capacity or full business readiness.
