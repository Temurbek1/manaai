# Managed parent support questions — local checkpoint, 2026-10-26

This extends the existing single family chat, not the four operational identities.
Retention can now request a useful support answer from the parent without attaching
an arbitrary child. Parent-Touch is still the only speaker. **Not released.**

## Contract and ownership

Default-disabled `MANA_PARENT_SUPPORT_QUESTIONS_ENABLED` requires the complete
governed manager/Retention profile. Only a newly admitted Retention speaker turn
captures the parent question, in the same SQL transaction as its owning intent,
turn metadata and private `retention_parent_question_captures` row. Disabled/old
turns and exact request replay never backfill the capture. No generic question
issuer, external parent-question endpoint or new source/action permission is added.

The existing `family_questions` queue now permits a typed parent target:
`child_id=null, scope="parent"`. Child questions retain their numeric ID and omit
the new scope field. Validators reject mixed/missing targets. External
`AgentQuestionRequest` still requires an authorized child; clients cannot use it
to impersonate Retention or create a parent question.

History and result projections use the existing `active_question`,
`message_questions` and `asked_question`. The mobile client replies with the same
`reply_to_question_id`; it must not invent a child or a second chat. SQL binds the
answer to the exact same-parent awaiting question. Concurrent/new-nonce replies
cannot consume it again. The server preserves the exact previously published
assistant text in the answered turn's prompt even with a short history window.
This is historical dialogue, never evidence of device state or action authority.

The single active-question index covers both targets. Ordinary child questions,
reminder confirmations and commercial contact wait; validated urgent Safety
notices can interrupt without replacing the active parent question. Parent
support needs are excluded from typed child assessment needs. A bound support
answer goes through the manager, which can still select Child-Safety if its actual
content needs an assessment; it is not automatically charged to Safety merely
because `reply_to_question_id` exists. Original child answers keep their protocol.

## Communication and model boundaries

Existing inactivity/anchor, independent Retention consent, frozen recipient
language/timezone, quiet hours, current-state validation and daily outreach limits
remain. Chat inactivity does not prove app churn, uninstall, child risk or paid
status. The model adapts one useful check-in/question to the actual dated history;
there is no static replacement for neural conversation.

This owning publication requires one question. Its slot schema requests a bounded
non-null string with exactly one final question mark; ordinary child questions can
still defer with null. Native IDs remain host-bound, outside model text/schema.
After the first paid diagnostic, instructions clarify notification permissions
versus background/battery restrictions and prohibit promised timely delivery.

The unchanged 2000 raw tokens per parent/day pay for the initial question and
subsequent replies. Safety retains its separate global allowance. Verified invalid
usage is charged; lost submissions retain holds and block new work across midnight.
A rejected support question is cancelled, not requeued through generic Safety
delivery or paid retry. Unknown questions remain held. A saved message precedes a
separately permitted neutral Retention push; this adds no real push permission.

An explicit RU/UZ opt-out cancels only Retention's already published support
question, so it cannot leave the child's queue permanently blocked. The opt-out
acknowledgement/replay adds no inference charge. Child questions and uncertain
in-flight questions/holds remain unchanged.

Disabling the flag stops new captures and new explicitly bound parent-support
answers while retaining history. Already admitted turns are not recaptured or
redispatched. Source schedules, provider activation and budgets are unchanged.

## Migration and closure

Private family schema **28** changes only the shared queue's child-column
nullability and adds the capture table. The existing queue is reconstructed inside
the owning `BEGIN IMMEDIATE`, preserving every row value, payload, question/turn ID,
answer binding, all three named indexes and the AUTOINCREMENT high-water mark,
including an empty queue. No historical question or chat payload is rewritten.
Unknown custom queue indexes/triggers/views refuse migration before reconstruction.

Use the current v28 closed reader to retain history and unknown holds. Actual
older-reader refusal is not functional execution rollback; never restore an old
database or downgrade this queue over new history. Existing v27 profiles are not
upgraded unless the new profile is selected or the file is already v28.

## Evidence

Sixteen meaningful local cases cover parent question/answer/replay, independent
consent, priced invalid cancellation, cross-day unknown holds/current closure,
v27 cell/index/sequence preservation with populated, used-empty and unused-empty queues, parent-vs-child
priority/urgent interruption, exact question context with a short history window,
atomic capture failure/disabled no-backfill, in-flight consent revocation,
cross-parent/concurrent answers, the actual SDK slot and idle runtime selection.
RU/UZ opt-out cases also prove exact replay and the next Child-Safety delivery.
Final `make verify` exited 0: **1584 backend tests**, one skipped/two opt-in live
cases excluded, **26 admin tests/11 suites**, **15 lab tests**, mypy **441 files**,
format/lint/types/build and npm audit with zero vulnerabilities. Evidence:
`output/parent-support-verify-empty-queue-final-20261026.log`. Earlier full gates
at 1580/1581 predate the final opt-out increment; 1583 predates unused-queue preservation.
The initial full gate stopped on
test-only typing mistakes; schema audit initially found the expected new public
type drift, then generated OpenAPI/TypeScript were synchronized. Those failures
are retained, not relabelled as passes.

The first packaged production-copy check of `8d77def` found an added
`sqlite_sequence('family_questions',0)` row for a never-used empty queue, without
losing original rows/history. That prototype evidence remains under
`output/parent-support-candidate-prototype-8d77def-20261026/`. The final migration
preserves absence of that counter as well as existing high-water values; it does
not silently clean or recapture already admitted prototype v28 histories.

Browser -> actual local HTTP -> SQL -> UI exercised proactive Retention question,
urgent Safety interruption, exact parent answer, next child question and its answer:
nine history messages, 750 simulated parent/300 Safety tokens. Reload/restart
preserved every cell in 66 family/15 source tables. The 390px viewport was inspected
without horizontal overflow or page errors. Evidence:
`output/parent-support-browser-20261026/`. The initial standalone JS capture had a
syntax error; the subsequent explicit async capture succeeded. The first server
handle later returned terminal 143 and its PID/port were absent before restart;
the preservation check is not proof of why that process received termination.

A separate fresh fake browser exercised the existing mobile submit operation
with its automatic active-question binding: Retention question -> queued child
question -> explicit stop/ack -> next Child-Safety question. Six history messages,
300 simulated parent tokens, active child 900002, no parent question left blocking
the queue. Evidence: `output/parent-support-optout-browser-20261026/`.

Paid diagnostics are separate fresh synthetic parties, never tests, live-family
contacts or replays. Preserve all SQL, receipts and negative reviews:

| Party under `output/` | Actual evidence |
| --- | --- |
| `parent-support-model-20261026` | Four GPT-5.4 generations/eight HTTP attempts. RU/UZ full question-answer bindings/replay completed at 1193/1302 parent tokens, zero Safety/unknown holds. $0.0106625 uncached generation estimate. **Qualified semantics:** Uzbek promised timely notification delivery and subsequent settings wording was ambiguous. |
| `parent-support-model-postfix-20261026` | One generation/two HTTP attempts, 520 input +93 output tokens, $0.002695 estimate. Model decision not accepted; no message/question published, no unknown hold/retry. Raw response/classified adapter failure were not captured, so exact cause is unproved. |
| `parent-support-model-inspect-20261026` | One generation/two HTTP attempts, 620 parent tokens, $0.0028 estimate. Captured allowlisted synthetic terminal/visible text, no reasoning. One natural Uzbek question, qualified settings help without promised delivery. **First-contact inspection only**, not full follow-up acceptance. |
| `parent-support-model-required-question-20261026` | Two generations/four HTTP attempts under the explicit non-null question schema. Full Uzbek support question -> exact answer -> useful Android notification guidance; the OS is parent-supplied, not telemetry. 1380 parent tokens, zero Safety/unknown holds; exact replay performs no HTTP. $0.0062125 estimate. One local synthetic pass, not a causal diagnosis of the rejected party or broader quality proof. |

All four independent parties total **eight generations/16 OpenAI HTTP attempts**
and **$0.02237** in known uncached generation estimates. They were not rerun and
the earlier negative qualification/refusal remain. Final synthetic visible text
is retained without provider reasoning, request headers or credentials.

Prices are estimates using [standard GPT-5.4 pricing](https://developers.openai.com/api/docs/pricing),
$2.50 input/$15 output per million tokens, not invoices. None of these parties
proves the rejected party's cause, broad dialogue quality, retention improvement,
fleet capacity, source completeness or production readiness. No Firebase/GA4,
real app grant/payment/push, SSH/key or production change was performed here.

## Try locally

`make chat-lab-parent-support CHAT_LAB_PORT=8103` uses fictional sources, family,
model and push. Start with “Возврат после паузы” in an empty lab, answer the support
question, optionally interrupt with “Тестовый тревожный сигнал”, then request/answer
a Child-Safety question. It is not a production integration endpoint.

The full goal remains active: broader real source/model/channel acceptance,
unsupported commercial/referral contracts, scoped release and administrative
owning-domain work remain; Technical is last.

## Final packaged checkpoint — application `7c136bd`

Clean image `mana-ai-family:parent-support-final-local-20261026`, ID
`sha256:3ae88ad3ae27ba2ae92df70f0af4b21b146424fc20f1af4bcf0f26fd4d3e7fbb`,
matches all **276 app Python files**, with no `.env` or private SQL. The actual
Python 3.12, networkless, nonroot, read-only-root package passed one parent
question/answer/exact replay at 300 simulated tokens, then retained a separate
612-token unknown submission across current closed observation, reconstruction
and midnight. Every cell in 66 tables survived; unknown work was not repeated.

The same image's actual production factory passed the retained October 25 private
copy **6 -> 28**, all original cells/columns/rows in 16 tables, two history
messages and exact old-request replay. Authenticated history/directory/replay and
liveness returned 200; unauthenticated history 401; lab action-card path 404 and
absent from OpenAPI. No external request or historical capture occurred. Current
closed v28 retained the complete upgraded state. This is a local copy, not a new
production read, live release or complete channel/fleet acceptance.

The actual preceding `a6f5153` image refuses populated v28 without changing a cell;
this is **not** functional execution rollback. Final evidence is under
`output/parent-support-candidate-20261026/`, protected 0700/0600. Source archive:
`/mnt/ssd2/mana-parent-support-source-7c136bd`. Initial prototype harnesses omitted
PYTHONPATH, then the fake helper's production Telegram-auth override; both failed
before the workflow. Those logs remain alongside the separate unused-queue
comparison failure, not relabelled as passes. Final SDK/application checks retain
the same production safeguards; only the hermetic fake profile disables Telegram.

Final schema synchronization passed after the terminal full gate. The primary
fake browser lab at **http://127.0.0.1:8103** was restarted from final code and
retains every cell in 66 family/15 source tables; its automation browser is closed.
The temporary opt-out server was stopped. Existing 8098–8102 labs and production,
source settings/schedules, SSH/keys, real grants/payments/push are untouched.
