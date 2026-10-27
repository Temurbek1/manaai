# Request-bound tariff cancellation — local, 2026-10-27

The test chat can cancel a confirmed catalogue wait through the existing message
API. Its button appears only when SQL message status advertises
`can_cancel_tariff=true`. Parent-Touch remains the only speaker; no model is called
for cancellation. The daily parent/Safety quotas and source meters stay unchanged.

## API and durable binding

Send a new control UUID and the original pending request UUID to the same
`POST /api/v1/mana-ai/parent-touch/messages`:

```json
{
  "parent_id": "123",
  "request_id": "979d7ae8-a404-4ff8-8b3f-e353ed55a1cb",
  "message": "отмени подбор",
  "cancel_tariff_request_id": "dfeb2df1-de6a-45d1-b3a5-dcb0459a7ff4"
}
```

IDs are fictional. Only one of the explicit RU/Uzbek Latin/English cancellation
phrases is accepted with this field, without question/confirmation bindings or a
self target. A fresh control checks the exact same-parent waiting request in its
own SQL transaction. A late, foreign or nonwaiting target returns controlled 409
`upsell_reply_not_waiting`; it cannot cancel a newer enquiry or fall back to a
model/reminder operation. Missing compatible execution returns controlled
`targeted_tariff_cancellation_unavailable`. Old text-only cancellation remains
available under its original rules.

Cancellation, its ordinary readable chat acknowledgement, target/audit binding
and canonical request digest commit atomically. The private target stays outside
legacy request/result JSON. Replaying the exact control UUID/body returns the
saved result, including after owning execution is disabled. A changed target,
message or omitted binding conflicts. Command-frequency limits still apply to new
controls. No empty parent message or second chat is inserted.

Poll the control's existing status GET and the original request. A current closed
reader exposes their saved status/history; closed execution refuses new control
POSTs. No quote remains publishable after cancellation. An already submitted
catalogue response can settle its original known source claim; a lost response
remains unknown/blocked. Neither is retried or refunded. A submitted model review
has no cancellation affordance from this contract.

## Browser recovery

The button preserves the exact target/control UUID in same-tab session storage
**before** POST. One click is one submission. Ticks, refresh and reload only read
SQL status; an unknown result disables another cancellation and new sends.
Definitive HTTP admission refusal plus an absent control status unlocks the UI
without resending. Denied storage stops before POST. A foreign-family saved record
is never observed/dispatched. A normal completion racing the click leaves its
quote/history intact, and a later enquiry cannot inherit the old control.

Use the v34 `make chat-lab-tariff-handoff` profile; default v32 labs/history retain
their previous profile and do not advertise the new button. The interface adds one
contextual button, without exposing UUIDs or raw source/provider details.

## Storage and acceptance scope

Family v34 adds `tariff_reply_cancellations` with exact parent/control/target-turn/
target-request/digest pairing. Existing v33 native call captures and old request
digests are not upgraded. Current closed readers take explicit v33/v34 storage
versions and never migrate a closed v33 file; v34 needs its current closed reader.
Previous-image refusal is not functional execution rollback. Source/collection
schemas, cloud settings, schedules and budgets are unchanged. No live source,
contact, tariff grant/payment or production activation follows.

Focused backend cases cover typed validation, real HTTP admission/status/replay,
cross-parent/wrong/late target, changed nonce payload, in-flight known/lost source
receipts, atomic publication rollback, concurrency, closed status and restart.
Controller cases cover committed/unknown lost acknowledgements, reload, ordinary
noncancellable work, late refusal, denied storage and foreign saved records.
Preserve the initial HTTP-test `usage.total_tokens` expectation error and helper
mypy error. The actual contract has raw `input_tokens`/`output_tokens`; validation
and billing rules were not weakened. No paid model call is needed for this
host-owned operation.

Final `make verify` exited **0**: **1705 backend tests**, one skipped/two opt-in
live tests excluded, **26 admin tests/11 suites**, **23 lab controller checks**,
mypy **460 files**, formatting/lint/type checks, production UI build and zero npm
vulnerabilities (`output/tariff-cancel-verify-release-20261027.log`). Earlier passing
gates predate the final explicit closed-v33 check/sparse API flag; only this run
covers the final implementation. OpenAPI/TypeScript were regenerated: the flag is
optional `true | null`, matching its actual sparse HTTP serialization. Focused
counts overlap this gate.

## Packaged and browser acceptance

Application **`1078106`** was exported into the clean external context
`/mnt/ssd2/mana-tariff-cancel-source-1078106`. Image
`mana-ai-family:tariff-cancel-local-20261027`, ID
`sha256:5ba3da00779785202e7fbfc35762f8158f28a6081982f8c41a616c336a2781b3`,
matches **287 application Python hashes**, without developer `.env` or private
SQL. Probes use Python 3.12/user 1000, no network/capabilities, read-only root and
private temporary/artifact mounts. The actual package exercises currency question,
exact answer/quote, a subsequent request-bound cancellation and exact replay.
Its **300 simulated parent tokens**, **612-token unknown model hold** and blocked
lost catalogue claim survive closure, restart and midnight with every cell in
**76 family/27 source tables** unchanged. Prior v33's actual closed reader refuses
v34 unchanged; that is not functional execution rollback.

The actual retained v33 fixture first stays v33 under explicit current closure,
then migrates locally to v34 with all **75 original tables/27 source tables** and
unknown holds retained. The new control table stays empty. The initial harness
installed SQL before its lab marker and was correctly refused; marking the empty
fictional fixture directory before installing its known files fixed only the
harness. No guard, quota or original artifact was weakened/reset.

The actual product factory also upgrades the retained private v6 production copy
locally, preserving every original column/cell in **16 tables**, both messages
and exact legacy replay. Authenticated history/directory/replay/live return 200,
anonymous history 401 and lab-only cards 404. Current closed v34 retains the same
history. No fresh production copy, SSH, provider/contact/grant request followed.
Artifacts: `output/tariff-cancel-candidate-20261027/`.

Actual 390px browser sequence: Uzbek price enquiry -> currency question -> bound
UZS answer -> SQL-confirmed wait -> Stop -> intentionally lost committed HTTP
acknowledgement -> SQL-only recovery -> known late source receipt. Exactly **one
cancellation POST**, **five history messages/150 simulated parent tokens/zero
Safety**, no late quote, reserve, push or grant. Both mobile screenshots were
visually inspected, without horizontal document overflow or page errors. After
guarded SIGINT and confirmed process termination, same-file restart/fresh page
retains the complete public state and every cell in 76/27 tables. The initial
fixture tried to instrument a catalogue before lifespan initialization and failed
before serving; its failure/connection-refusal evidence remains separate. The
corrected wrapper instruments after initialization. Browser and fixture server
are closed. Artifacts: `output/tariff-cancel-browser-20261027/`.

The normal loopback **8110** lab is updated to current code after its old port was
authoritatively closed. A private backup preceded its v33->v34 migration. All old
75/27 table cells and its **eight messages/600 simulated parent/300 Safety tokens**
remain, with no new source/model call. `http://127.0.0.1:8110/` returns 200. Artifacts:
`output/tariff-cancel-local-lab-upgrade-20261027/`. No paid-model party was repeated.
These fictional engineering checks are not real family/source quality, business
lift, production budget throughput or production release acceptance.

Referral remains deferred pending its real API. This local increment does not
complete the full AI KOMANDA, source/business-quality or production release scope.
