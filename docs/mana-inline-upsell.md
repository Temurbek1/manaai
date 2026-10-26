# One tariff result in the original parent turn — local checkpoint, 2026-10-27

New captured price enquiries can wait for their owning catalogue result instead
of publishing an acknowledgement and a separate quote. Parent-Touch remains the
only speaker in the same existing parent chat. The model selects the typed need;
code validates and renders exact dated prices. This is not general proactive
upsell, checkout, a tariff grant, referral integration or production activation.

## Contract and ordering

`MANA_UPSELL_INLINE_RESULTS_ENABLED=false` is the default. Its governed runtime
requires the existing currency-enquiry profile. Only new turns capture the mode.
Older pending/completed requests retain their original acknowledgement/quote
behavior, budgets, language and replay. No historical request upgrades itself.

After verified raw model usage is committed, a new tariff turn stays
`phase=responding` with `response=null` while its existing bounded source workflow
runs. The provisional acknowledgement never enters public history. The owning
quote, or a controlled unavailable result when the fresh context permits it,
completes that **same turn/request ID**. Poll the normal message-status GET and
refresh normal history; do not start another request or insert an assistant turn
in the application. No new mobile operation or wire schema is added.

For a missing currency, the initial host question remains a completed assistant
message. The exact bound UZS/USD answer becomes the waiting source turn and later
contains its own quote, with zero additional inference. A normal enquiry has two
history messages; an enquiry with a currency question has four. Source reads,
quote validation and current ownership are unchanged. Cached catalogue reuse does
not redate its original collection or create another source admission.

Parent-Touch still has **2000 raw input/output tokens per parent/day**; Child-Safety
has its separate **2000 global tokens/day**. There is no extra generation for the
final host quote and no financial action. The ordinary dialogue uses the actual
models. Fake-provider workflow evidence is not a real catalogue or business result.

## Cancellation, uncertainty and priority

An application can cancel a waiting tariff request using the existing message POST:

```json
{
  "parent_id": "123",
  "request_id": "19bfbc09-6caa-4862-a7b3-3eb777e7f6ea",
  "message": "cancel tariff request"
}
```

IDs are fictional; create one new UUID for the parent's actual cancellation.
The exact original nonce observes its result on replay. No fabricated empty
parent message, new chat, payment or grant is involved. The API cancels only that
parent's existing waiting tariff workflow. A narrow explicit cancellation that
arrives after completion returns **409 `upsell_reply_not_waiting`** without a model
fallback or reminder mutation. Generic `cancel`/`отмена` retains ordinary reminder
meaning outside a waiting tariff workflow. A lost cancellation acknowledgement
must be observed through its saved request ID, not repeated with new nonces.

Cancellation/disable/expiry/new Safety priority fences unsubmitted source work
and late quote publication. Already submitted source receipts remain metered:
known results may settle their original shared catalogue claim; lost results stay
unknown/blocked across restart and midnight. No refund, reset or automatic retry
follows. Invalid model output, a lost model receipt and staging SQL failure retain
the existing strict raw-cost/unknown-hold rules. Cancellation cannot undo a model
charge, recall a network request or create fresh source authority.

The source wait ends at the earlier of the original five-minute admission deadline
and the existing source claim window. A failed/expired ownership context closes
the parent status rather than leaving it spinning. A source refusal does not mean
no tariffs exist. Safety interrupts a price result; no active model/source work
is ignored merely to publish a commercial answer.

## Storage and compatibility

Family **v32** adds immutable admission and response-stage tables, a pending index,
and exact response/intent fingerprints. The saved public-response checkpoint
retains verified usage/model/context while the public result is pending. It
contains no raw provider reasoning or execution receipt. Binding or fingerprint
changes stop before another source read. Publication/result/status are atomic.
Sources/collection schemas and schedules do not change.

Use the current closed v32 reader to retain history and unknown holds with
execution disabled. Previous readers are not supported execution rollback targets;
their refusal is not a working rollback. Never downgrade populated state or
restore an old database over new history.

## Actual evidence so far

The pre-late-cancellation `make verify` exited **0**:
`output/inline-upsell-verify-final-20261026.log`, **1663 backend tests**, one skipped /
two opt-in live excluded, **26 admin tests/11 suites**, **15 lab checks**, mypy
**455 files**, lint/types/build and zero npm vulnerabilities. Sequential schema
sync was unchanged. The strengthened late-cancel check requires the subsequent
gate recorded below; do not present the earlier gate as covering that correction.

The focused suite now has eighteen cases: original-turn result/currency binding,
two-worker publication, in-flight cancel with known/lost catalogue receipts,
disable/expiry/Safety, restart/closed state, actual prior-v31 pending migration,
pre-model disable, atomic staging loss/unknown model holds, changed intent proof,
lost catalogue restart, stale ownership, actual runtime/validated closed config,
and late explicit cancellation without fallback. Preserve the initial test-file
assembly/import/type failures. A stale-context regression initially showed the
source had safely refused publication but left the new parent status waiting;
the subsequent owning-status fence fixes that gap without another source read.

Two new independent real-model synthetic RU/Uzbek dialogues completed the typed
manager -> tariff decision -> original-turn quote workflow: **four generations /
eight OpenAI HTTP attempts**, **1266 /1279 parent raw tokens**, zero Safety tokens
and zero unknown holds. Russian uses two history messages; Uzbek uses four with
its exact currency question. Original/answer replay triggers no generation/read.
Known standard uncached estimate **$0.0086875**, not an invoice. All families,
contact settings and catalogue data were fictional; no real Firebase/GA4/app,
push/grant or production request followed. Artifacts:
`output/inline-upsell-model-20261026/`. The subsequent late-cancel guard changes
no model input/receipt; these parties are not to be replayed.

The final late-cancel/poll `make verify` exited **0**:
`output/inline-upsell-verify-accepted-20261027.log`, **1666 backend tests**, one
skipped/two opt-in live excluded, **26 admin tests/11 suites**, **15 lab checks**,
mypy **455 files**, lint/format/types/build and zero npm vulnerabilities. The
separate 37-case focused suite overlaps these counts. The earlier full gate
failed because a lab polling test indexed a non-history HTTP response; its body
was not retained, so the precise original cause is unproven. The observer now
accepts only the exact existing 409 `lab_state_busy` during bounded SQL-only
polling and asserts every other failure. Explicit busy/unexpected-error cases
prove that distinction without another POST or source/model work. The first
helper full run then caught an untyped lab reference in mypy; it was corrected
before the final passing gate. All failure logs remain intact.

The actual browser/HTTP/SQL run and same-file server restart preserve six history
messages, **600 simulated parent tokens/zero Safety**, the complete public state
and every cell in **73 family/15 source tables**. The 390px screenshot was inspected
with no horizontal overflow. Late explicit cancellation returns 409 without
changing the saved state. Preserve the initial browser reconnect's startup
connection refusal and snapshot comparison's wrong row-order assumption: a
separate comparison matches all original hashes using their first-column order,
including both unchanged SQLite sequence values. No source row or high-water mark
was reset. Artifacts: `output/inline-upsell-browser-20261027/`.

Test-chat source cancellation is currently an API control; its composer
still disables ordinary sends while a request is pending, so an interactive Stop
affordance is not implemented or claimed here. The full original AI KOMANDA goal
remains active, including commercial/referral contracts, deeper data semantics,
broader quality/capacity and separately scoped production release. The owner has
deferred Referral work pending its backend API; continue independent requirements.

Run the model-free lab with `make chat-lab-inline-upsell CHAT_LAB_PORT=8108`.
This is an isolated fictional loopback scenario, not production data or a real offer.

## Packaged and migration acceptance

Application **`a1680e7`** was exported into the clean external build context
`/mnt/ssd2/mana-inline-upsell-source-a1680e7`. Image
`mana-ai-family:inline-upsell-local-20261027`, ID
`sha256:e997a1631cb32721296abc76e7523f9669eaa9a3cec08f87d337987d3fe25255`,
matches all **285 application Python hashes** and contains no developer `.env`
or private SQLite. Probes use Python 3.12, user 1000, a read-only root filesystem,
no network/capabilities and only private artifact/temporary writable mounts.

The actual packaged application completes the fictional currency question ->
bound answer -> original-turn quote with **four history messages/300 simulated
parent tokens/zero Safety**. Exact replay performs no inference/catalogue read.
A separate lost model submission retains a **612-token unknown hold**. A lost
catalogue receipt stays blocked. Current closed-reader initialization, restart
and midnight preserve all cells in **73 family/15 source tables**, with no
redispatch or refund. The actual prior v31 image refuses new v32 without changing
any cell/version; this is not functional execution rollback to that image.

The current product factory also upgrades the **already retained** private v6
production copy to v32 locally. All original columns/cells in **16 tables**, both
messages and exact historical request replay are preserved. Live/history/agent
directory/replay return 200; anonymous history returns 401 and lab action cards
remain absent (404). New captured workflow tables stay empty. The current closed
reader retains the exact same history, with zero new source/model/contact/grant
calls. No fresh SSH access or production copy was obtained. This small copy is
not fleet, release, live-source or broad model-quality acceptance.

Artifacts: `output/inline-upsell-candidate-20261027/`. Production, cloud data,
source schedules, quotas, customer tariffs and SSH/keys remain unchanged. The
original full agents objective remains active.
