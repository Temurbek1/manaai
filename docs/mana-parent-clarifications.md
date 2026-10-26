# Parent-Touch reactive clarifications — local checkpoint, 2026-10-26

This is the next increment after the completed v28 parent-support checkpoint.
It is **not released**. The full AI KOMANDA goal stays active.

Default-disabled `MANA_PARENT_TOUCH_CLARIFICATIONS_ENABLED` captures only newly
admitted manager turns in private family v29. It uses the existing message,
status/history and shared parent/child question queue. Parent-Touch can ask one
necessary clarification of a parent-initiated app-help request, then interpret its
explicitly bound answer. There is no new speaker, mobile operation, push, source
permission, payment/grant authority or token allowance. Child assessments,
tariffs and reminders retain their owning native handoffs.

Private admission and publication tables keep the new protocol outside legacy
request/result JSON. The server creates the question atomically with its verified
assistant response after raw accounting and current priority checks. Native
handoffs are handled before accompanying prose. Unknown/invalid/late decisions
cannot publish a question or cause automatic paid replay. The current v29 closed
reader retains history; old-reader refusal is not functional execution rollback.

Explicit neutral answers such as `Android` inherit the originating question's
frozen language/reference, independently of current contact preferences. On new
captured turns only, uncertain heuristic language uses the exact frozen parent
reference as model-directed presentation instead of forcing the contact language.
This affects presentation only; it supplies no source/action/contact grant. Old
admissions remain on their original protocol. Broader multilingual/host-template
acceptance remains required; no general language-detection claim is made.

The new manager reply schema has statements plus one nullable bounded question;
the server accepts it only for the exact privately admitted root manager stage.
Native owner handoffs precede accompanying prose. A late higher-priority child
question suppresses the candidate after verified usage is accounted. Publication
is one SQL transaction with the turn result, common question row and private
origin binding. A failed publication keeps the unknown hold and does not retry.

The original child-question reply protocol remains unchanged. Reactive questions
need no unsolicited Retention/marketing permission, but do not create any such
permission or a push. A completed message may contain another necessary question;
it does not prove the parent's entire task is finished. History's active question
remains authoritative; original completed response metadata is historical.

## Verification

Final `make verify`, actual exit 0: **1598 backend tests**, one skipped/two opt-in
live cases excluded, **26 admin tests/11 suites**, **15 lab tests**, mypy **443
files**, lint/format/types/build and npm audit zero vulnerabilities. Final schema
synchronization passed, with no new mobile request/response field or operation.
Evidence: `output/parent-clarification-verify-final-20261026.log` and final schema log.

Fourteen new cases cover RU/UZ exact neutral answers and replay, old/disabled
no-backfill, original child-answer review, current closure/unknown holds across
midnight, v28 pending-turn preservation, the actual SDK's scoped schema and raw
usage on rejection, native-before-prose handoff, late child priority, publication
failure, cross-parent/concurrent answers and lazy idle runtime without HTTP.
The overlapping focused party is 60 cases. Early test failures found the neutral
language issue and an incorrect expectation that failed user text disappeared;
user text remains. A subsequent prompt-only full gate stopped at a long literal;
the format-only correction preserves the measured model input.

The actual browser -> HTTP -> SQL -> UI flow exercised a parent clarification,
urgent Safety interruption, exact Android answer, child question/answer, then a
switch to Uzbek and another Android answer in the same chat. Twelve messages,
**1050 simulated parent/300 Safety tokens**, no active question or unknown hold.
The 390px screenshot was inspected, with no horizontal overflow/page errors.
Evidence: `output/parent-clarification-browser-20261026/`.

Two distinct new synthetic model parties used GPT-5.4, fake family/source/contact
providers, no worker or real source/grant/push. Original receipts are immutable:

| Party under `output/` | Result and limits |
| --- | --- |
| `parent-clarification-model-20261026` | RU/UZ message workflows completed at 1568/1918 parent tokens, four generations/nine HTTP attempts, $0.01709 known uncached generation estimate. Uzbek over-explained both platforms before its question. Russian opened a separate legitimate brand question after Android; that task remains unfinished, despite the message's completed phase. One extra successful input count used the existing history projection, not a transport/generation retry. |
| `parent-clarification-model-concise-20261026` | Independent OS-specific tasks after concise-first guidance: one OS question -> Android -> useful focused answer in RU/UZ, 1676/1694 parent tokens, no next active question, four generations/eight HTTP attempts, $0.01335 estimate. Exact answer binding and replay with no HTTP passed. Contact language was Russian in both cases; the Uzbek frozen reference governed that dialogue. |

Total **eight generations/17 OpenAI HTTP attempts**, **$0.03044** estimated known
generation cost, not an invoice; all Safety usage/unknown holds zero. Rates:
[standard GPT-5.4 pricing](https://developers.openai.com/api/docs/pricing),
$2.50 input/$15 output per million tokens. Preserve the first party's qualification;
these are different tasks, not a causal cost study or broad model/fleet/business
acceptance. General Android menu labels vary; no device settings were inspected
or changed. Broader language and host-rendered offer/template acceptance remain
open; the uncertain-reference behavior is new-protocol model presentation, not a
general deterministic language detector or new source/action grant.

Packaged candidate and migration acceptance are recorded after the clean build.

The proposed lab is `make chat-lab-clarification CHAT_LAB_PORT=8104`, using only
fictional providers and a separate private directory. Try “Как настроить MANA?”
or “MANA qanday sozlanadi?”, then answer the question through the same chat.

## Calls source investigation

The supplied mobile archive defines `ChildPath.getChildCalls` as
`/api/v1/child/call/` in `lib/src/constants/request_path.dart:15`. The current
`CallRemoteDataSourceImpl.getCalls` appends the child ID and `page`; generated
models expose `child`, `call_type`, `duration`, `timestamp`, name/number/SIM fields.
The view parses the timestamp as epoch milliseconds and duration as seconds.
That is a supplied-client contract, not proof of current server behavior.

Exactly one bounded read-only party performed login 200, fresh designated test
parent 4 ownership GET 200 (six connected child links), and one page-1 GET on the
first freshly owned child at that source-backed path. The latter returned **404**,
179 bytes; no call rows were obtained. The body was not retained, so it does not
prove whether this is a missing route, unavailable resource or access behavior.
No fallback/retry/route crawl, audio, Firebase/GA4/model/contact/grant or production
change occurred. Only types/counts/status metadata were retained; no child IDs,
names or phone numbers. Keep the terminal admission/receipt at
`output/child-calls-contract-20261026/`; do not replay it. The historical plural
path in `lib/repository/call_repository.dart` was observed but not requested.
