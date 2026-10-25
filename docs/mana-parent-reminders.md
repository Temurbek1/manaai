# Parent assistant reminders — local checkpoint, 2026-10-25

Parent-Touch now supports parent-owned reminders inside the existing single chat.
The parent proposes a task and time, sees an explicit preview, and confirms it.
A local worker later publishes one durable assistant message; a separately allowed
push is considered only afterwards. There is no additional parent chat or public
reminder-creation endpoint. Orders, calls, payments and transactions are not implemented.

`MANA_PARENT_REMINDERS_ENABLED=false` remains the default. This local increment
changes no production service, schedule, key, tariff, Firebase or GA4 data. It
requires the complete existing native/source-review family profile; independent
activation on earlier family profiles is not implemented. The administrative
OPERATION agents and their private SQL history are separate.

## Contract and ownership

Continue using message POST, message-status GET and single-chat history GET.
When history contains `active_confirmation`, send its exact `confirmation_id` as
`reply_to_confirmation_id` with the parent's real answer. This is independent of
`reply_to_question_id`, whose child-bound meaning does not change. An active child
question takes priority; do not submit both bindings.

A new eligible Parent-Touch turn captures its own immutable assistant scope.
The model can return one typed draft containing an exact quote from the latest
parent request, a nullable date and an IANA timezone. IDs, action authority and
execution receipts are not model-selected. A draft with a date must use that
zone's actual UTC offset and fall between one minute and 366 days ahead.
The model cannot schedule it or claim an action has succeeded. The host validates
and renders the preview atomically with the original priced response.

The preview shows the date, time, timezone and exact task quote. Missing time
produces a date question. The timezone is verified contact metadata when present;
otherwise the application default is explicitly a proposal for confirmation.
A frozen clarification recognizes precise ISO dates and limited RU/UZ/EN
relative-date answers; it is not a general language parser. Ambiguous/nonexistent
DST times are rejected. Free-form replies continue through the existing model.

Only a real parent affirmative reply to that active, parent-bound preview can
schedule it. Expired, foreign, stale or conflicting confirmations fail closed.
Exact request replay observes its original SQL result; it does not approve again.
RU, Uzbek Latin/Cyrillic and English templates preserve known presentation language.
Language is not consent or source authority.

Confirmation, supported date clarification, listing and cancellation are host
controls and need no new inference. They work after the model quota is exhausted.
Examples: `мои напоминания`, `отмени последнее напоминание`, `eslatmalarim`,
`oxirgi eslatmani bekor qil`, `my reminders`, `cancel my last reminder`.
A human can cancel an unknown reminder; that does not refund or repeat its read.

## Delivery, races and limits

The SQL scheduler does not scan Firebase. Before one due delivery it commits a
nonreclaimable claim, then makes one fresh exact-parent profile/ownership lookup
through the existing MANA adapter. Its profile receipt must match that parent and
be no more than 180 seconds old. Auth denial closes further reminder ownership
reads; timeout, cancellation, lost acknowledgement and expired claims stop unknown.
There is no transport retry, reclaim, replacement nonce or historical recapture.

A verified profile can wait in `ready` while a parent message or priority safety
notice is in flight. Publication rechecks those conditions and current consent
in the same SQL transaction. Continuation observes SQL only, without a second
profile read or model call; an expired verification stops rather than rereading.
A parent cancellation fences late callbacks. A known late auth failure still
closes future ownership reads even if that reminder was cancelled meanwhile.

A specifically confirmed reminder permits its own chat message; it does not grant
broad proactive messaging. Explicit current `assistant_chat_consent=false` vetoes
delivery. Push additionally requires fresh `assistant_push_consent=true`; safety
and marketing permission do not substitute. Quiet hours apply before a send claim;
changed/expired consent or outbox age suppresses the push. No lab has a push gateway.

The immutable default reminder policy allows 10 active reminders per parent,
1000 globally, 20 host commands per parent/rolling day, 500 globally and 100 due
ownership claims per rolling day. Confirmation expires after 30 minutes; the due
window is one hour and ownership lease 120 seconds. Unknown attempts remain
consumed. Policy changes cannot silently reopen existing actions or raise ceilings.
Parent-Touch keeps 2000 raw tokens/parent/day; Child-Safety keeps 2000 globally/day.
No reminder budget increase, source scan or extra model process is introduced.

## Storage and compatibility

Private family schema **14** adds assistant scope, policy, reminders, audit and
one-shot delivery tables. Source-cache schema remains **4**. Old turns do not
acquire reminder scope. Host-only messages carry a host template model marker,
zero inference usage and no invented child-context collection date; raw model
usage is still recorded before validating draft arguments or final prose.

Upgrade is additive. Current closed v14 readers retain history without execution.
The actual previous v13 image refuses v14 unchanged: it is **not a working
rollback**. Never downgrade a populated schema, discard unknown holds or restore
an old database over new chat history. Back up live SQLite using its backup API
or another consistent WAL-aware method, not by copying a live main file alone.
A deployment needs its own approved scope and compatible closed-reader plan.

## Evidence and remaining work

The lifecycle tests exercise actual admission, safety review, Parent-Touch, SQL,
confirmation, date clarification, quota exhaustion, cancellation, foreign/stale
binding, in-flight chat/cancel races, one-shot claims, unknown restart and separate
push consent/quiet hours. SDK MockTransport checks preserve priced invalid-zone
receipts without creating drafts. Runtime checks cover enabled/disabled profiles
and lazy startup. None calls a live provider.

One independent real-model party is retained in `output/reminder-model-20261025`.
It made four OpenAI HTTP attempts (two counts, two generations), settled **777**
safety and **1055** speaker tokens, and left **zero** unknown holds. The date/time
was correct; the model quoted the entire request rather than the short task.
The original strict harness consequently did not confirm it. Its result is retained.
A separately admitted, zero-inference host continuation of that same SQL draft
confirmed it before the due time, waited on the real clock, delivered it once and
observed no duplicate. It read only fictional profiles and contacted no parent.
This is qualified evidence, not a clean language-quality or whole-goal pass.
The instruction now asks for the shortest exact task phrase; no new paid party
has verified that subsequent wording change.

Using the actual returned mini/strong model rates, standard uncached generation
is estimated at **$0.004359**. This is not an invoice or proof of counting cost.
Rates were checked in the [official OpenAI pricing](https://developers.openai.com/api/docs/pricing).
Typed draft output follows [official Structured Outputs guidance](https://developers.openai.com/api/docs/guides/structured-outputs);
application policy and human confirmation remain separate from schema adherence.

Image and browser evidence is recorded with the final checkpoint below. GA4/admin
aggregate wiring, GPS ownership mapping, other specialists, whole-population
capacity, real consent/channel acceptance, broader language/model quality and the
full [autonomous objective](mana-autonomous-agents-plan.md) remain unfinished.

Final checkpoint checks:

- `make verify`, session **20576**, exited **0**: **1235 backend tests**, one skip,
  two live opt-ins excluded, **26 admin tests /11 suites**, **9 lab controller
  tests**, Ruff/mypy **369 files**, TypeScript, production UI build and zero npm
  vulnerabilities. API synchronization and final secret/quality scans also pass.
- Dedicated reminder lifecycle suite: **10 passed**. A deliberately lost speaker
  receipt stays reserved in its original SQL turn and blocks future inference
  across midnight, while host controls still work. Current-day displayed counters
  reset normally; this does not release the older unknown hold.
- Owned loopback browser: RU missing-date request -> ISO date reply -> confirmation
  -> one real-clock delivery, all after the initial 150/150 simulated tokens with
  no extra inference. UZ request -> confirmation -> cancellation also passed.
  Restart/fresh navigation retained the exact seven SQL turns/thirteen displayed
  messages, three reminder records, one delivery, 15 audit events and 300 simulated
  speaker tokens. No push existed, no source provider was read, and no horizontal
  overflow appeared at 390px. Scheduled/delivered screenshots were visually checked.
  The owned browser and both server processes are stopped.
- Current image `mana-ai-family:reminders-v14-20261025-checkpoint`,
  `sha256:b14af3564999f8f5dddad3bfd45241bcf2ec793b956f56c6095372c4eaab5aaf`,
  passed networkless v13 -> v14 initialization with all old table fingerprints,
  **150 known /1850 unknown safety tokens**, and no recaptured reminder. Its closed
  reader retained all five messages from the qualified paid party unchanged.
  Actual previous `fbe6b567300e` refused v14 with identical database bytes.
  This is current-image closure plus old-image refusal, not production rollback.
- Image probes consume closed snapshots made with the host SQLite backup API.
  Initial raw-copy/read-only fixture failures are retained separately and are not
  passing compatibility evidence. The first full gate lacked a dummy model key;
  another found the assistant helper's forbidden `.state` name. That helper was
  renamed without weakening the architecture test. Early extra regression failures
  were harness attribute/ledger-column/day-counter assumptions; corrected checks
  now inspect the actual durable unknown turn. Original negative logs remain.

The final short-task prompt wording and mixed source-report/reminder requests still
need broader real-model acceptance. A source-backed answer's date obligations must
not be discarded to produce a reminder preview. Do not infer whole-agent readiness
from this bounded local increment or activate a production schedule from it.
