# MANA conversion: required backend integration

Local implementation only. These conversion endpoints are not released on
production yet. Parent-Touch is the sole speaker in the parent's single chat.
The agent never creates a payment or transaction.

## Required data

On 2026-10-22 an exact-parent Parent List GET returned `is_paid`, `created_at`
and `agent_trial_used`, alongside `payment_date` and `valid_until`, and passed the
existing strict account adapter. This supersedes the earlier missing-key checks;
see [the bounded live evidence](mana-conversion-live-account-checkpoint.md).
The owner originally clarified these fields were added to the grant POST response;
their later presence in GET is now separately verified. Never issue that grant
POST merely to inspect status.

Parent List still describes a selected current tariff record. A paid record
suppresses conversion; a non-paid record alone does not establish absence of an
overlapping paid entitlement. Confirm what `created_at` dates and whether
`agent_trial_used` includes expired grants before mapping them to free-start or
lifetime-history assertions. Adult activity and contact preferences are still
required separately. Do not infer missing facts from a tariff name or timestamps.

The subsequent [owner-authorized reset-account test](mana-conversion-grant-live-checkpoint.md)
confirmed that one new agent grant returns strict non-paid/used flags and a
creation date matching the subsequent Parent List record. This establishes a
dated new grant, not uninterrupted free usage or lifetime/overlap semantics for
arbitrary existing records. A reset account returned explicit `is_paid=null`;
automatic policy still treats that as unknown. The grant adapter validates new
metadata but retains the unchanged minimized legacy receipt in SQL.

The MANA backend needs to supply verified account events, or document an existing
read-only source from which an event producer can obtain:

| Fields | Required source |
| --- | --- |
| `parent_id` | Canonical numeric MANA parent profile ID, as a string; not Firebase Auth UID or child ID |
| `subscription` | Authoritative `free`, `paid`, `expired` or `unknown`; paid entitlement takes precedence over an overlapping free record |
| `free_started_at`, `free_access_ends_at` | Actual start/end of free access, not an assumed registration date |
| `agent_trial_given` | Lifetime agent-grant history; `false` only when its absence is verified |
| `marketing_consent`, `consent_observed_at` | Separately verified marketing consent and its observation time |
| `language`, `timezone` | Parent's verified language/script and IANA timezone |
| `last_active_at`, `active_days_7d`, `sessions_7d`, `paywall_views_7d` | Dated adult-parent activity aggregates, not child telemetry |
| `event_id`, `revision`, `observed_at` | Immutable event UUID, increasing per-parent state version, actual time the full state was verified |

Do not mix MANA with 360REC. Child GPS, conversations, safety findings and fears
must not be used for commercial targeting.

## Send an account event

Use the separate parent-chat backend bearer token, never the general inference
key or a mobile-embedded secret:

```http
POST /api/v1/mana-ai/conversion-agent/events
Authorization: Bearer <ISOLATED_MANA_PARENT_CHAT_BACKEND_TOKEN>
Content-Type: application/json
User-Agent: MANA-Backend/1.0
```

```json
{
  "product": "mana",
  "parent_id": "123",
  "event_id": "7ceea1bf-b4b4-48ac-a12b-9f7c7d6e5c11",
  "revision": 1,
  "observed_at": "2026-10-21T09:00:00Z",
  "subscription": "free",
  "free_started_at": "2026-10-14T09:00:00Z",
  "free_access_ends_at": "2026-10-22T09:00:00Z",
  "agent_trial_given": false,
  "marketing_consent": true,
  "consent_observed_at": "2026-10-21T09:00:00Z",
  "language": "uz-Latn",
  "timezone": "Asia/Samarkand",
  "last_active_at": "2026-10-21T08:50:00Z",
  "active_days_7d": 3,
  "sessions_7d": 5,
  "paywall_views_7d": 1
}
```

IDs and dates are fictional. Use real current observations; do not shift old
timestamps to make a snapshot appear fresh. Default contact freshness is 900 seconds.
No extra `is_paid`, child data, or arbitrary provider payload may be added.

`202` returns `decision` and an optional `proposal`; admission is not publication.
Only the Parent-Touch worker publishes the offer after current policy checks.
Exact event replay returns its original receipt without a new model/source/send.
A different body under the same event ID conflicts. New state requires a higher
revision and a non-decreasing observation time.

## Cover every parent without repeated database scans

The subsequent local opt-in account-verification lane can check eligible events
against the now-observed Parent List fields, under durable exact-event claims,
a six-hour parent cooldown and a rolling 100-claim/day global default ceiling.
It does not replace your authoritative full snapshot/producer, use `created_at`
as free start or treat a selected non-paid record as proof of paid precedence.
It is default disabled and unreleased. Read [the v10 checkpoint](mana-conversion-account-admission-checkpoint.md)
before enabling it. Its `GET /conversion-agent/source-observations/<event_id>?parent_id=123`
observes saved SQL only, never a provider refresh or retry.

1. Agree a bounded initial export of all MANA parent accounts, with expected and
   processed counts plus explicit missing/unknown records. No export is enabled
   by this document or by starting the AI service.
2. Persist subsequent events in the MANA backend's transactional outbox when
   subscriptions, activity or preferences change. Track acknowledgements and gaps.
3. At a time threshold, such as day seven or free-access expiry, verify the
   account again in the owning backend and send a fresh snapshot. An old event
   cannot authorize a later offer merely because a timer elapsed.
4. Send payment/consent-revocation updates promptly. AI-side checks cannot see an
   external change that the backend has not supplied.

The producer and source mapping are still external integration work. The current
AI repository does not provide an authoritative full-parent status source or
enable Firestore/GA4 bulk scans. Tracking everyone does not mean contacting
everyone: consent, safety priority, cooldown, quiet hours and caps still apply.

## Offers and payment outcomes

The real read-only `GET /api/v1/tariffs/?limit=25&offset=0` returned five plans on
2026-10-23, including tariff `3` at **60,000 UZS for 30 days**, `8` at 162,000 UZS
for 90 days, `9` at 299,000 UZS for 180 days, `7` (VIP) at 500,000 UZS for 30 days
and `4` at 599,000 UZS for 365 days. These are observed prices, not a full approved
campaign or checkout contract. The catalog adapter is local and not runtime-wired;
see [the source checkpoint](mana-conversion-catalog-source-checkpoint.md).

The owner must still approve `MANA_CONVERSION_OFFERS` and confirm renewal terms,
in-app checkout mapping and recipient applicability. A synthetic 15% test offer,
`old_price` or monthly flag is not a real available discount or renewal policy.
Do not set `auto_renew=false` or invent a checkout path merely because those fields
are absent. The existing full paid-offer schema remains unchanged.

Hot and seven-day free-use rules are deterministic. The new opt-in v9 lane can
also offer a paid plan after a freshly confirmed free-access end, within the
configured window (default seven days). It never offers another free grant for
that expiry reason. Time after the actual end does not count as additional free
days. Clock-only expiry without fresh confirmation does not qualify.

Register verified language and separate contact permissions before first contact
or push; see [the single-chat guide, section 10](mana-single-chat-integration.en.md#10-new-first-contact-and-push-notifications).
Push queueing is not phone delivery. Unknown send outcomes never auto-retry.

The free Maxsus grant API provides 1–30 non-paid days, once per parent. It does not
create a paid subscription or transaction. In the AI API, explicit backend
`POST /conversion-agent/trial-acceptances` requires the actual parent's activation
message `reply_turn_id`, exact published `proposal_id`, a new `event_id`, and
`confirmed_by_parent=true`. In v9 the reply must also have that offer frozen at
admission. Days come from the approved catalog, not the mobile client or model.
Parent-Touch explains a known terminal result in the same chat; it does not infer
success from the activation phrase. Result receipts are currently chat-only.

For actual paid conversion, the backend separately sends
`POST /conversion-agent/outcomes` with `kind="payment_confirmed"`, a unique
`payment_id`, the published `proposal_id`, exact `billing_offer_id`, amount,
currency and actual observation date. Interest, clicks and free-day grants never
count as paid conversion. The endpoint records a verified receipt; it does not
charge or create a transaction.

Read-only observation routes include:

```http
GET /api/v1/mana-ai/conversion-agent/proposals?parent_id=123&after=0&limit=20
GET /api/v1/mana-ai/conversion-agent/proposals/<proposal_id>?parent_id=123
GET /api/v1/mana-ai/conversion-agent/trial-grants?parent_id=123
```

GETs never dispatch a grant, source read, model call or push. Disabled services
currently return controlled 503s on their conversion observers; saved SQL receipts
and the single-chat history are retained, not deleted or automatically retried.

## Request to the owning backend team

Please provide the documented authoritative subscription/activity source or wire
the event producer above. Confirm field provenance, paid/free precedence, grant
history, recipient permissions, initial population coverage and gap accounting.
Also provide approved offer terms supported by checkout. Current Parent List alone
does not supply enough information. Until this integration and the release checks
are complete, full real-user tracking and production paid conversion are unproven.
