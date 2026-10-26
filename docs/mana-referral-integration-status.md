# Referral and loyalty integration — current evidence, 2026-10-25

## Subsequent schema-only observation — 2026-10-26

`output/parent-contract-shape-20261026/` records one new bounded schema check of
designated test parent 4: login 200 and the same filtered one-page Parent List
GET 200, two HTTP attempts total. Only field types/list lengths were retained,
not personal values, subscription booleans/dates or credentials. It confirms the
existing commercial field names and five child-profile rows in this record; no
referral or contact-preference fields were present. This does not prove absence
from other services or update October 25's historical paid/trial values below.
No grant, model, push, Firebase/GA4 or production change followed this read.

## Original October 25 evidence

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

## Supplied mobile source checked — 2026-10-26

The owner's `bosstracker_parent-develop.zip` was inspected read-only, without
executing its app or build scripts. Its archive hash is still
`5794cfce882876aaee57e163a793ec7b4d864e6c27d9fcde5eb23a9c64114036`.
This establishes the supplied revision, not current GitHub or deployed app state.

Source paths below are relative to `bosstracker_parent-develop/`:

- `lib/src/features/auth/presentation/screens/signup.dart:49` reads Android
  `utm_source`; lines 92–95 read an iOS link's `ref` parameter. Line 246 sends
  the resulting `userName` as registration `partner`. That is an incoming
  attribution path, not proof that every parent has an issued referral code,
  that the parameter is a canonical inviter ID or that a reward was earned.
- `lib/services/api/user_service.dart:230` posts `tariff`/`promo_code` to
  `/api/v1/admin-panel-payment/validate-promo/`. The payment UI at
  `lib/screens/new_settings/payment.dart:326` reads `original_price`,
  `discounted_price`, `discount_percent` on a successful validation. No agent
  call was made; this code alone does not establish an idempotent, read-only
  validation contract or permission to issue codes/rewards.
- `lib/screens/new_settings/personal_profile.dart:94` reads a profile's
  `promo_code`. That is not evidence of an API accessible to this backend for
  personal referral-code issuance or of the rules associating it with friends.
- `lib/services/api/user_service.dart:355` submits promo codes during the
  actual tariff purchase. **Do not call this purchase endpoint from an agent**:
  agents are not permitted to create payments or transactions.
- `lib/component/show_custom_review_dialog.dart:423` has an optional
  `bonusMinutes` display. Its inspected celebration constructor leaves it null;
  it does not establish a backend referral/reward receipt or approved terms.

The source search also distinguishes inviting a **child/device** from inviting
a new paying parent. Sharing an installation link, reading install attribution,
validating a discount, or seeing a bonus label cannot substitute for the missing
personal-code, qualifying-referral and reward contracts listed above. The
document's example “one month free” remains unapproved; the one-time agent trial
must not be repurposed as a recurring referral benefit.

Minimized file hashes and findings are recorded in
`output/referral-source-contract-20261026/result.json`. No credentials/source
configuration were copied, no API/model/Firebase/GA4 request or customer-data
read was made, and production was not changed. Referral remains incomplete;
source/runtime/release work that does not depend on that contract continues.

## Current GitHub source access — 2026-10-26

The supplied repository `Bosstracker-Team/bosstracker_parent` returned **404**
through the connected GitHub metadata tool and the existing local `gh` account.
The connected repository-scoped referral search returned no results. Neither
observation proves that the private repository or referral mechanism is absent;
current source access was not established. The supplied archive remains historical
evidence only. The Parent/grant/push documentation files' modification dates remain
unchanged; no fresh code/reward contract was obtained.

Minimized results: `output/referral-github-access-20261026/result.json`. No app API,
Firebase/GA4, model, contact, payment or grant request occurred. No keys were copied
or changed and no production/remote repository mutation was made. Continue other
implementable requirements rather than inventing reward terms or repeating reads.
