# Trial confirmation buttons — local integration

New trial offers can now attach a confirmation card to their existing Parent-Touch
message. Pressing the button follows the existing one-time grant lifecycle and
publishes its dated result into the same chat. This increment is **lab-only**:
the executor uses `LabTrialGrantGateway` for fictional parent `900001`, with one
fictional free day. No production factory, live grant endpoint, source refresh,
model allowance or tariff is activated.

```sh
make chat-lab-trial-actions CHAT_LAB_PORT=8099
```

Open <http://127.0.0.1:8099>, select **7 дней бесплатного доступа**, then press
**Активировать бесплатно** or **Не сейчас** under the offer. The scenario describes
seven days of previous fictional use; the frozen lab offer grants **one** day.
Existing quiet hours and the priority/idle rules apply. The generic card editor
and demo scenario still execute only `sandbox_demo`.

## Request and chat contract

The recommended three chat operations remain unchanged. Use the lab's existing
card GET/list and POST `/{card_id}/click` endpoints described in
[the test card API guide](mana-chat-action-cards.en.md). This increment adds no
client-selected trial creation payload, arbitrary callback or separate chat.

Only the owning Conversion publication can create a `free_trial_days` card.
Its text, labels, language, parent, proposal, duration, original offer and expiry
are server-owned. It shares the **same `turn_id`** as the already published
assistant offer; do not duplicate that message in the application. A card includes:

```json
{
  "action_type": "free_trial_days",
  "mode": "simulation",
  "trial": {
    "proposal_id": "e4bda84e-e375-4e55-8c2c-bba5b7d2d25d",
    "grant_days": 1
  },
  "status": "pending"
}
```

IDs above are fictional. The full GET response supplies the actual card ID,
definition hash, dates and buttons. Submit its exact `definition_hash` and the
chosen stable button ID with the parent's authenticated click. Display text is
not authority. Plain chat replies do not confirm a pending card. Do not fabricate
a parent message, activation phrase or `reply_turn_id` to bridge this flow.

Confirmation atomically stores the selected card choice, an internal typed
`TrialButtonAcceptance`, the existing owning `conversion_trial_grants` claim and
a single dispatch claim. The original text-based `TrialAcceptance` endpoint and
its stored JSON/digests remain unchanged. Button acceptance is internal and is
not accepted by that legacy public endpoint.

The owning policy rechecks current non-paid eligibility, source verification,
opt-out, approved exact offer/expiry, global daily grant ceiling and one-time
parent limit. Button proof additionally checks the current independent recipient
language/timezone, exact displayed terms, validity and safety/chat priority.
These checks repeat before the one provider dispatch. The fake gateway verifies
its fixed fictional parent and requested one-day duration; no real adapter is
mounted. A pre-dispatch definitive refusal retains a dated rejected receipt
without a provider request. A lost provider result remains unknown and is never
resubmitted automatically.

The card result uses `outcome: trial_granted`, `trial_rejected` or `trial_unknown`
plus the original typed owning grant receipt. `completed` means a known result,
including rejection; it does **not** universally mean that access was granted.
The web UI labels rejection separately. Unknown results remain `unknown`. A
process death may leave `executing`/`submitting` even after expiry or midnight.
GET/reload/restart/new click nonces never repeat execution. If the owning receipt
is already terminal but the card's result acknowledgement was lost, GET derives
the known status from its exact bound SQL receipt without redispatching or
rewriting the stored card. A second confirmed receipt cannot replace the first.

Cancellation makes no grant claim. An explicit existing “stop offers” preference
cancels only unclaimed pending trial cards and continues through normal chat
admission; it does not undo or repeat a consumed action. A new known refusal with
a still-unclaimed SQL card permits another explicit human choice. Transport loss
retains the original click nonce and never automatically changes the decision.

The existing dated trial-result publisher saves one assistant receipt. Confirmed
period capture then uses the existing v22 companion, permitting a later reminder
only with its independent current tariff, consent, quiet hours and caps. No model
call is needed to confirm, grant or render this host-owned result. Subsequent
dialogue keeps 2000 raw Parent-Touch tokens per parent/day and the separate global
2000 Child-Safety tokens/day; holds and existing financial ceilings are unchanged.

## Capture and compatibility

The dedicated local profile uses family schema **v25**. New proposal admission
freezes an enabled bit, exact offer digest and snapshot revision in
`trial_card_admissions`. Publication creates `trial_card_bindings` and its same-chat
card/message in one transaction. An explicit click creates
`trial_button_dispatches`; only that original call can consume its `ready` claim.
Worker startup, observer GETs and replay never drain ready dispatches.

Old proposals, disabled captures and exact event replays never acquire a new card
when the feature is enabled. Existing v24 demo history/claims retain every cell
on additive migration; no old acceptance, receipt or provider call is recaptured.
`SqliteClosedLabTrialActionStore` supports v25 history with action execution absent.
The former v23/v24 readers reject its extra tables; this is not working old-image
rollback or permission to downgrade/restore an old database over new history.

RU, Uzbek Latin, Uzbek Cyrillic and English card templates and result languages
are covered. Source dates, exact original conditions and unknown holds remain.
English integration section 31 describes this local extension. Real owning-domain
mobile/production wiring, broader agent quality and the original goal remain open.

## Verified checkpoint — 2026-10-26

The final `make verify` process exited **0**: **1527 backend tests**, **26 admin
tests /11 suites**, **15 chat-lab tests**, mypy **432 files**, formatting/lint/
typecheck, production UI build and zero npm vulnerabilities. One skip and two
excluded live tests are not passes. `make audit-schema` passed with unchanged
production OpenAPI/TypeScript files. Both commands used an explicit dummy
inference key; no real provider was called. Logs:
`output/trial-action-cards-20261026/{verify,schema}.log`.

The **117** focused cases overlap that gate. Dedicated new cases exercise the
guarded HTTP flow, concurrent clicks, exact replay/restart, zero fabricated user
turns, cancellation, expiry, proof/language/account changes, opt-out, revoked or
disabled offers, pre-dispatch refusal, unknown acknowledgement, lost card result,
ready claims across midnight, four presentation languages and the actual factory.
Old demo rows/claims survive additive v24 -> v25 migration exactly; no historical
card admission is backfilled. The current closed v25 history reader preserves
that populated demo fixture; the prior v23 class refuses it unchanged. This is
local class/SQL evidence, not a packaged candidate or working old-image rollback.

Actual Chromium pressed the new trial button before any parent message. A
deliberately lost successful HTTP acknowledgement produced one fake grant, one
card and two assistant-only messages. Refresh recovered the owning receipt with
no new POST or model call. A later supported fictional 90-day enquiry used the
same chat and returned **162 000.00 UZS** as a full-term fake catalog price.
The final seven messages contain two actual user enquiries and five assistant
messages; **600 simulated parent tokens**, **zero safety tokens**, zero holds.
Reload and actual server restart preserved every row across **66 tables**, one
grant and the original dispatch/card event history with an identical fingerprint.
The inspected 390px mobile screenshots have no document overflow or script error.
Evidence is under `output/trial-action-cards-20261026/`, private and uncommitted.

Keep the qualifications: an initial readiness probe/navigation raced startup;
the already-starting server was not restarted. A 30-day browser follow-up was
outside the deterministic model's tariff fixture and returned its labeled generic
simulation reply. It is not successful 30-day model-quality acceptance. A distinct
90-day question then exercised the supported fixture. Browser waits expected
unformatted amounts and timed out; SQL retained the original responses and the
formatted price was independently checked. No failed party was rewritten or
nonce replayed to replace those outcomes. No real-model quality check was added
by this deterministic confirmation increment, and no live tariff was issued.

The test server may remain on loopback for the owner. Production, real family
data, Firebase/GA4, schedules, existing services, SSH and keys remain unchanged.
