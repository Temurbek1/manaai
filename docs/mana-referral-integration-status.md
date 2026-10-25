# Referral and loyalty integration — current evidence, 2026-10-25

The owner confirms that MANA already has a referral mechanism and will supply its
contract. Do not invent a replacement program or treat the lack of documentation
below as proof that the mechanism does not exist. Parent-Touch remains the only
speaker; referral/loyalty remains within the Retention administrative owner.

The two supplied files were read again on October 25:

| File | SHA-256 | What it establishes |
| --- | --- | --- |
| `agent-tariff-api.md` | `439bf211676077844e62a1bac51a1c112b555e45049989cc174c88ca0c425bfb` | One non-paid Maxsus grant of 1–30 days, once per parent's lifetime; no payment/transaction |
| `parent-api.md` | `eda5c1f8a7c2e33dcf69c6a52b58d09034a60f463a5830e9b181d3a55280e623` | Filtered MANA parent/child list and selected current tariff record |

Neither file describes code issuance, attribution of an invited parent, referral
status, reward eligibility, reward amounts/limits, or a verified reward execution
receipt. The agent tariff's `trial_already_given` rule explicitly prevents using it
as a repeatable reward for each invited friend. `agent_trial_used` is not a referral
counter. Do not rename the already consumed test-parent grant or call it again to
simulate a referral. An existing paid catalog price is not reward approval.

## Fresh bounded source observation

`output/referral-parent-contract-20261025` contains the original one-shot admission,
HTTP metadata and minimized response shape. Exactly two attempts completed:

1. `POST /api/v1/admin-panel-auth/login/` — 200.
2. `GET /api/v1/admin-panel-parent/parent-list/?parent_id=4&limit=1&offset=0` — 200.

This is the owner's designated test parent, not a scan or another selected family.
The URL in the supplied Parent List markdown repeats `/api/v1`; the existing
working adapter correctly uses the single prefix shown above. No fallback route,
transport retry, grant, contact, model call, Firebase/GA4 read or production change
was performed. Credentials, tokens, phone, child identifiers and names were not
saved in the result. The known HTTP responses are not to be replayed automatically.

The live response includes strict booleans `is_paid` and `agent_trial_used`, and
explicit zoned `created_at`, `payment_date`, `valid_until`, plus `tariff_name`.
All six commercial fields exist in that observed record. The older markdown omits
three of them. This is fresh confirmation of the existing strict account adapter's
contract, not a new connection or universal coverage guarantee. The selected test
record is paid and its one-time trial is consumed; no write is appropriate.

No referral/reward/invite/promo field was present in this single response. That
does not establish absence from other services. The bounded unauthenticated
contract-discovery GETs to `/api/schema/`, `/swagger/?format=openapi` and
`/openapi.json` each returned 404; there was no hidden endpoint crawl.

Dates and a selected current tariff do not prove lifetime payment history, every
active entitlement, renewal, account creation versus trial-start semantics, contact
consent, parent activity, referral eligibility or attribution. Keep these separate.

## Remaining exact integration inputs

Use the existing referral mechanism once its actual contract is available:

- Obtain or issue the canonical parent's personal code/link, including whether
  obtaining it is a read or an idempotent mutation.
- Read attributed invitation states and the qualifying event, with stable IDs,
  observation dates and exact inviter/invitee scope.
- Validate approved reward terms, limits, eligibility and consumed reward history.
- Execute/reconcile the supported reward with a durable claim, no unknown-result
  replay and verification through the owning service.

Then complete the existing single-chat flow: verified eligibility -> queued
Parent-Touch invitation -> actual parent response -> supported code/link ->
verified referral progress/reward -> one chat receipt and separately allowed push.
There is no deployed referral feature or newly implemented reward API in this
investigation. The full agents goal remains active; other available work continues.
