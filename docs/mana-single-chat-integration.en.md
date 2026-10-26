# Connecting MANA agents to a single chat

Integration guide for backend and mobile developers. Sections 1–9 describe the
released Parent-Touch and Child-Safety API, application version `f8d095e`. The
conversion agent under development is not part of this production contract.

First contact before the parent's first message and push notifications have been
implemented locally. Their new contract is described separately in section 10:
**these additions are not enabled in production yet**.

**API:** `https://ai.360rec.uz/api/v1/mana-ai`

**Swagger:** <https://ai.360rec.uz/docs#/mana-ai>

## 1. How it works

```text
Parent → MANA backend → Parent-Touch → the parent's single chat
                             ↑
                        Child-Safety
                             ↑
               new child data from the MANA backend
```

The parent communicates only with Parent-Touch. Child-Safety analyzes data and
passes internal results and questions to Parent-Touch. The parent does not need
to select an agent, open additional chats, or see Child-Safety's internal response.

One `parent_id` = one history. Do not create or pass a `chat_id`.
History is stored by the AI service, not by the mobile application or Firebase.

This integration is for **MANA**, even though the API domain contains `360rec.uz`.
Do not submit 360REC families. `parent_id` is a string containing the numeric MANA
parent profile/Firebase ID, not a Firebase Auth UID or a child's ID.

## 2. Authentication and backend responsibilities

The phone calls your backend; your backend calls the AI API:

```http
Authorization: Bearer <ISOLATED_MANA_PARENT_CHAT_BACKEND_TOKEN>
Content-Type: application/json
User-Agent: MANA-Backend/1.0
```

Use the **separate parent-chat backend token**. The general inference key does not
grant access. Never include this token in the mobile application or public JavaScript.

The backend must derive `parent_id` from the authenticated user's session. Do not
proxy an arbitrary ID supplied by the phone. Submit only children belonging to
that parent; the AI service additionally verifies the relationship.

Check the configured agents:

```bash
curl --fail-with-body --silent --show-error \
  'https://ai.360rec.uz/api/v1/mana-ai/agents' \
  -H "Authorization: Bearer ${MANA_AI_BACKEND_TOKEN}" \
  -H 'User-Agent: MANA-Backend/1.0'
```

`MANA_AI_BACKEND_TOKEN` is an environment variable in your backend or terminal,
not a JSON field. The examples below use fictional IDs; replace them.

## 3. Opening the chat: retrieve history

```http
GET /api/v1/mana-ai/parent-touch/chat?parent_id=123&limit=30
```

```bash
curl --fail-with-body --silent --show-error \
  'https://ai.360rec.uz/api/v1/mana-ai/parent-touch/chat?parent_id=123&limit=30' \
  -H "Authorization: Bearer ${MANA_AI_BACKEND_TOKEN}" \
  -H 'User-Agent: MANA-Backend/1.0'
```

Display the `messages` array in order. Each message contains `turn_id`, `role`,
`content`, `created_at`, and `status`. Always display `role=assistant` as
Parent-Touch, regardless of which internal agent initiated the message.

For older history, use `next_before_turn_id` from the response:

```http
GET /api/v1/mana-ai/parent-touch/chat?parent_id=123&limit=30&before_turn_id=100
```

Deduplicate visible messages by `(turn_id, role)`. A turn can contain both the
parent's text and an assistant response; a proactive turn may contain only an
assistant message.

## 4. Sending a message: recommended flow

### Step A. Save the message

```http
POST /api/v1/mana-ai/parent-touch/messages
```

```json
{
  "parent_id": "123",
  "request_id": "3a7454f8-38d2-4e8b-b251-017970f48350",
  "message": "My child goes to bed late. What would you suggest?"
}
```

Generate a new UUID for each **new** message. Persist the UUID and original body
before sending. If the HTTP response is lost, repeat the **same UUID and identical
body**, rather than creating a new message.

`message` has a maximum length of 2000 characters. Do not add `agent_id`, `chat_id`,
`locale`, or sensor data to this request. The response language follows the parent's
message; short neutral replies also use the conversation's established language.

The service returns `202` with the message state, not the completed AI response.

### Step B. Wait for the result

```http
GET /api/v1/mana-ai/parent-touch/messages/3a7454f8-38d2-4e8b-b251-017970f48350?parent_id=123
```

Handle `phase` as follows:

| Value | Application behavior |
| --- | --- |
| `awaiting_review` | The message is saved; Child-Safety is reviewing the context |
| `responding` | Parent-Touch is preparing the response |
| `completed` | Read `response.answer` and refresh the shared chat history |
| `failed` | Show the controlled `error_code` and stop waiting |
| `unknown` | The call outcome is unknown; stop waiting and do not automatically resubmit |

For example, poll every two seconds only while the user is waiting for this
response. Handle `429` and `Retry-After`; do not poll indefinitely for all parents.
The preparation window is limited to five minutes.

On `completed`, you may display `response.answer` immediately, but merge it by ID
when history refreshes rather than displaying it twice. When reopening the screen,
restore the known `request_id` and read its state/history. Do not submit a new
message to recover an existing one.

A second request for the same parent may receive `409` while a message is being
processed. Disable duplicate submission while waiting.

## 5. Answering an agent's question

History includes `active_question` and `message_questions`, which associate a
question with its visible Parent-Touch message. Do not render these metadata as
separate messages or show technical UUIDs to the parent.

When the parent specifically answers the displayed question, the backend includes
its ID:

```json
{
  "parent_id": "123",
  "request_id": "6dc4604e-ff09-49fb-873c-45ff3fbcf6ad",
  "message": "He usually goes to bed around ten in the evening.",
  "reply_to_question_id": "2a4fecb8-12d8-4709-bbf2-a54a0be5f774"
}
```

Send this to the same `POST /parent-touch/messages` endpoint. Take the question ID
from the actual API response, not this example. Without `reply_to_question_id`,
the message is not automatically treated as an answer to the open question.

Do not blindly bind every subsequent message to that question: the parent may
change the subject. An expired, foreign, or already consumed binding returns `409`.

Parent-Touch asks one awaiting question at a time. Other questions remain queued.
An urgent Child-Safety notice may appear between a question and its answer, but
does not open a second question.

## 6. Submitting new child data to Child-Safety

The backend submits new facts to the appropriate endpoint. For example:

```http
POST /api/v1/mana-ai/child-safety/safety-monitor
```

```json
{
  "parent_id": "123",
  "child_id": 124,
  "request_id": "7af34c56-f70c-43ef-b774-e38d41ccabdd",
  "source_revision": "device-observation-001",
  "analysis": {
    "request_id": "device-observation-001",
    "occurred_at": "2026-10-20T09:00:00Z",
    "locale": "uz",
    "data_minimized": true,
    "subject": {
      "subject_id": "124",
      "age_band": "age_7_12",
      "timezone": "Asia/Samarkand"
    },
    "input": {
      "battery": [
        {
          "evidence_id": "battery-001",
          "observed_at": "2026-10-20T08:59:00Z",
          "percent": 15
        }
      ]
    }
  }
}
```

This illustrates the structure, not current data. Supply actual observation dates,
not the submission time. `subject_id` must match `child_id`. Do not generate new
UUIDs in a loop for an unchanged observation.

Other available `/child-safety/` suffixes:

- `family-digest`
- `adaptive-screen-time`
- `location-intelligence`
- `smart-content-filter`
- `scam-privacy-shield`
- `ai-gaming-safety`
- `child-safety-assistant`
- `family-agreement`
- `behaviour-anomaly`

Each has its own JSON contract in Swagger. Do not send a `safety-monitor` body to
all other endpoints. There is no generic `/analyze` endpoint.

`202` means the task was admitted, not that analysis is complete. For backend
diagnostics:

```http
GET /api/v1/mana-ai/child-safety/assessments?parent_id=123&limit=20
GET /api/v1/mana-ai/child-safety/assessments/<job_id>?parent_id=123
```

Do not display the internal analysis as a second chat speaker. If clarification
or an allowed notice is needed, the worker routes it through Parent-Touch.
The application sees it in the normal `/parent-touch/chat` history.

Do not schedule repeated analysis of the same data. This flow does not enable
bulk Firebase/GA4 loading: the backend supplies new facts.

## 7. Internal question queue

For the normal Child-Safety flow, you **do not need** to manually create a question
and trigger delivery after each analysis. The worker already handles this.

To explicitly submit a question from the registered Child-Safety agent:

```http
POST /api/v1/mana-ai/parent-touch/requests
```

```json
{
  "parent_id": "123",
  "child_id": 124,
  "agent_id": "child-safety",
  "request_id": "be653861-85f8-47eb-a05c-7ebcc0228759",
  "information_key": "sleep.schedule",
  "question": "What time does your child usually go to bed?",
  "reason": "Clarify the usual routine before assessing a behavioral change.",
  "source_revision": "sleep-observation-001",
  "priority": 1,
  "observed_at": "2026-10-20T09:00:00Z",
  "expires_at": "2026-10-21T09:00:00Z"
}
```

`201` means the question was queued, not yet sent to the parent. Supply real dates;
the validity window cannot exceed seven days. Priority ranges from 0 to 3: higher
first, then queue order for equal priority. Matching needs may be coalesced.

Read the queue: `GET /parent-touch/requests?parent_id=123&limit=20`.

For a separate explicit backend delivery, use `POST /parent-touch/deliver`:

```json
{
  "parent_id": "123",
  "request_id": "ef93781d-60e0-4e5a-9e2b-c92ae801d454"
}
```

This may call the model and consumes the Parent-Touch allowance. Do not call it in
a loop in addition to automatic delivery, or generate new nonces after errors.
Proactive model delivery requires an established parent language. In the current
production release, this comes from a previous parent message; section 10 describes
the new way to supply a verified language before the first message.

An arbitrary new `agent_id` cannot register an agent through this request. Current
production supports Parent-Touch and Child-Safety. Future agents require server-side
typed contracts and policies, not impersonation of Child-Safety or a fictional
`child_id`.

## 8. Limits and errors

Current production limits:

- Parent-Touch: **2000 input + output tokens per parent per day**, including system
  context and assistant deliveries, not only visible text.
- Child-Safety: **2000 tokens per day across all parents combined**. With a
  2000-token reservation per task, this generally permits about one short analysis
  per day.
- The daily boundary is midnight in `Asia/Tashkent`, Uzbekistan local time.

The small shared Child-Safety budget may prevent a new response even when
Parent-Touch has remaining tokens. Review-first does not bypass a refused review
or start an independent analysis through another agent. These limits do not
support a promise of chat availability for all users.

Chat quota is included in the history response. Read the analysis budget with:

```http
GET /api/v1/mana-ai/child-safety/budget?parent_id=123
```

| HTTP | Handling |
| --- | --- |
| `401` | Check the separate backend token |
| `403` | Stop: child/data access has not been confirmed |
| `404` | No such task exists in this parent's scope |
| `409` | Conflicting UUID, in-flight task, or invalid answer binding |
| `422` | Correct fields according to the endpoint's Swagger schema |
| `429` | Respect quotas and `Retry-After`; do not bypass with a new UUID |
| `502/503` | Controlled model/source failure or disabled feature |

History/status GETs do not call the model or repeat the original task. A lost model
response is not assumed free: `unknown` remains recorded without automatic retry.
The current production chat does not send push notifications or child-device
control commands, and does not guarantee emergency delivery.

## 9. Application integration checklist

1. One chat screen: history, input, send, and waiting state.
2. A protected backend proxy deriving `parent_id` from the session.
3. Submit through `/parent-touch/messages`; observe the result by `request_id`.
4. Bind actual answers with `reply_to_question_id`, without exposing UUIDs in the UI.
5. Submit only new child events to the corresponding Child-Safety endpoints.
6. Refresh history when opening or returning to the chat, with bounded observation
   while it is open. This API does not yet provide parent-facing SSE/WebSocket.
7. Deduplicate by `(turn_id, role)`, handle quotas, and never automatically repeat
   paid or unknown tasks.

The conversion agent is being developed separately. Do not integrate its new
`/conversion-agent/...` routes, free-day grants, or tariff offers as released
endpoints until a separate release is confirmed.

## 10. New: first contact and push notifications

**Implemented locally and tested with fake providers; not released yet.** Do not
call the new production paths until the release is confirmed. Each parent still
has one chat, and Parent-Touch remains the only speaker.

First, the backend supplies the parent's verified language, timezone, and contact
permissions:

```http
POST /api/v1/mana-ai/parent-touch/contact-context
Authorization: Bearer <ISOLATED_MANA_PARENT_CHAT_BACKEND_TOKEN>
Content-Type: application/json
```

```json
{
  "parent_id": "123",
  "event_id": "87f2fb03-56c4-4996-94a5-2512f99a8e40",
  "revision": 1,
  "observed_at": "2026-10-21T09:00:00Z",
  "valid_until": "2026-10-22T09:00:00Z",
  "language": "uz-Latn",
  "timezone": "Asia/Samarkand",
  "safety_chat_consent": true,
  "safety_push_consent": true,
  "marketing_push_consent": false
}
```

IDs and dates are fictional. Do not copy the consent flags as a real parent's
settings. The backend verifies permissions independently; having a tariff does
not imply consent. Supported languages are `ru`, `uz-Latn`, `uz-Cyrl`, and `en`.
Settings are valid for at most seven days. Changes require an increased `revision`
and a new UUID `event_id`. Exact event replay neither sends a message nor restores
old permissions.

Next, the backend submits new child data to the appropriate `/child-safety/...`
endpoint, as in section 6. If an agent needs to contact the parent, the worker:

1. Prepares the text through Parent-Touch in the verified language.
2. Saves **only an assistant message** in the existing chat history.
3. Calls the existing push API if separately permitted.

The parent no longer needs to write first. Do not submit an empty user message,
create another chat, or insert a duplicate message in the application. Questions
keep the sequence “question — answer — question”; urgent safety notices may
interrupt waiting without opening a second question.

The push is neutral, for example: “You have a new message in MANA. Open the app.”
Child names, GPS, and conversation content are not exposed on the lock screen.
A push failure neither deletes the saved message nor triggers another model call.

The phone retrieves the full text through the existing `GET /parent-touch/chat`.
Tapping the notification should open that same chat and refresh history. The
existing push API body has no `chat_id` or deeplink field; the mobile application
must implement its notification-opening handler.

The backend can observe state without sending:

```http
GET /api/v1/mana-ai/parent-touch/contact-context?parent_id=123
GET /api/v1/mana-ai/parent-touch/notifications?parent_id=123&after=0&limit=20
GET /api/v1/mana-ai/parent-touch/notifications/<push_id>?parent_id=123
```

Each push record contains the message's `turn_id`. `queued_by_provider` means
queueing for a positive number of devices, not delivery or reading. Zero devices
means `not_queued`. Never automatically retry `unknown` or a lost `submitting`
attempt: the external API has no idempotency key. Chat history is preserved.

Existing token limits have not increased. First-contact and push flags are disabled
by default. This flow does not enable bulk Firebase/GA4 reads, payments,
transactions, unrestricted messaging, or new operational agents.

## 11. Autonomous source-to-chat processing — local, not released

The October 24 objective removes a mandatory new-backend-webhook dependency for
facts already available through authorized Firebase/GA4/application sources.
Existing section 6 submissions remain compatible. Sources must eventually be
registered as bounded server tools; the model/browser never receives credentials
or arbitrary query/collection access.

The initial **local** battery path now runs:

```text
authorized source read -> shared private snapshot -> admitted change receipt
  -> frozen Child-Safety request -> separately budgeted specialist assessment
  -> existing Parent-Touch notice -> the same durable chat -> optional permitted push
```

Source-change admission is captured atomically with the saved change. An event
collected while the consumer is disabled, or before its activation epoch, cannot
be upgraded into automatic inference later. Snapshot identity, facts, policy and
the exact specialist request survive restart. A lost admission acknowledgement
is reconciled through the existing exact SQL request, never another source read
or blind redispatch. An absent unknown result remains unresolved.

Fresh connected-child ownership is checked before preparation and again by the
existing safety workflow before inference. Undated/ambiguous/stale observations
do not become current alerts. Battery writes do not prove connectivity:
`BatterySignal.online` now explicitly accepts `null` for unknown. Existing boolean
values and the old default remain compatible; unknown does not mean offline.
The additional source-cache schema v2 is separate from family-chat schema v9.
Old v1 source readers refuse it; no historical source or model hold is erased.

**Mobile integration is unchanged:** continue the three recommended operations
in sections 3–4 and merge assistant messages from the single history. Do not send
fake parent text, create a second chat, insert an extra copy of the agent answer,
or let the phone choose another family's identity.

The isolated lab's `/lab/child-battery` is fictional, session/CSRF-protected and
not mounted on the product API. It is not a production integration endpoint.
The lab uses the real application/store/worker but fake family/source data in
both modes; actual models are separately opt-in. See [the lab guide](mana-chat-lab.md)
and [the implementation checkpoint](mana-source-safety-checkpoint.md).

The subsequent [server runtime increment](mana-family-source-runtime.md) adds
explicit server credential wiring and `ParentTouchService.sources` for internal
typed reads. Its factory performs no HTTP at startup. An optional independently
enabled source consumer connects new captured changes to the existing safety
worker. One actual bounded test-family read passed; its undated measurement
cannot be used as a current alert, and no model/message/push/grant was launched.
Keys remain server-only. A source authorization failure closes its durable lane;
exact replays and unknown outcomes do not repeat reads.

The subsequent native workflow below implements model-selected battery reads.
Bulk-window collection, remaining specialists and broader real-model/source/channel
acceptance are still required. None of these local increments updates production.

## 12. Model-selected sources — local, default disabled

The same three chat operations now support an explicitly enabled native
Child-Safety source review. No mobile integration change or extra chat is needed:

```text
POST parent-touch/messages -> captured Child-Safety review
  -> model selects an own-child battery alias -> shared scoped source cache
  -> same specialist receives the exact result -> Parent-Touch communicates
GET message status / chat history -> observe the saved answer without redispatch
```

`MANA_CHILD_SAFETY_SOURCE_TOOLS_ENABLED` requires the existing source runtime,
review-first configuration and explicit safety ceilings. It remains false by
default. Keys remain server-only; the model cannot choose arbitrary queries,
another parent, a URL, source permissions or an increased budget. Old messages
never acquire the new protocol on migration. Family history advances additively
to private schema 11; source-cache schema stays 2.

Both specialist generations use the original global 2000-token safety ledger;
Parent-Touch retains its separate per-parent allowance. Raw receipts are recorded
before selecting/executing tools. Lost continuations retain partial known costs
and unknown reserves. Neither a refreshed page nor a repeated request may restart
them. Reply facts preserve measurement dates and unknown data; a collected record
does not establish current connectivity or a full protective assessment.

For fictional browser testing, use `make chat-lab-native`, or explicitly opt into
paid models with `make chat-lab-native-live CHAT_LAB_ENV_FILE=/path/to/server.env`.
These modes still have no live family sources, push or free-tariff adapters.
See [the workflow evidence and limits](mana-native-source-workflow.md) and
[lab instructions](mana-chat-lab.md). The settled real RU tool-loop diagnostic
has presentation caveats and does not establish production capacity or broad
model quality. Candidate closure is same-code only; never downgrade populated v11.

## 13. Own-child app counters through the same chat — local

`MANA_FAMILY_APP_USAGE_ENABLED=false` is an additional explicit server opt-in.
When enabled with the existing native/source runtime, new turns capture family
v12/observation-v2. Child-Safety may call
`read_child_observation(child_alias, kind)` for `battery` or `app_usage`.
The backend calls the existing exact-child Manakids API and shared source cache;
the phone still uses only the three recommended message/status/history operations.
No new webhook or per-read confirmation is required within admitted scope/limits.

App counters are one bounded provider page with explicit coverage and unknown
measurement period/timezone. Do not display them as today's screen time, sum
overlapping counters or infer a full app ranking. Backend dates/collection dates
are not interchangeable. The existing source request ceiling is shared across
both sources; caches, cooldowns, unknown locks and auth circuits are source-scoped.

Queued v11 turns keep battery-only tools and digests. Use current v12 closed
profiles/source v3 for retained history; old v11/v2 images refuse these schemas.
The source consumer must include the source-kind filter from this increment:
an app event is not a battery event. Unknown outcomes never auto-retry.

The developer lab is `make chat-lab-observations`, or explicitly paid
`make chat-lab-observations-live CHAT_LAB_ENV_FILE=/path/to/server.env`.
It remains fictional, loopback-only and unable to push/grant/read live sources.
See [actual API/model/browser/image evidence and limits](mana-child-app-usage-source.md).
This increment is not production activation, complete GPS/GA4 collection or the
entire multi-agent objective.

## 14. Shared scheduled family collection (local, default disabled)

The server can discover MANA parents with connected children even before their
first chat. `MANA_FAMILY_COLLECTION_ENABLED` separately wires bounded collection
at 09:00/15:00 Asia/Tashkent through the existing ownership/cache/source meters.
No new mobile request or backend webhook is required for already supported facts.
The same three chat operations receive eventual Parent-Touch messages; collection
is not consent, a push request or an inference-budget increase.

See [the collection checkpoint](mana-family-collection.md) for configuration,
durable unknown/no-retry behavior, manifest dates, illustrative daily/monthly/
annual costs and the demonstrated fleet-capacity gap. Defaults do not provide
whole-population refresh. GA4/shared administrative aggregates and broader source
consumers remain unfinished. For fictional first-contact testing, run
`make chat-lab-collection`; it cannot use paid models or real family data.

## 15. Coalesced source reviews (local, default disabled)

With `MANA_FAMILY_SOURCE_REVIEWS_ENABLED`, admitted battery/app-counter changes can
be combined into one bounded Child-Safety review and routed through Parent-Touch,
even before the parent writes. Native source requests carry host attribution to
avoid a duplicate background review; their existing tool scope is unchanged.

No new phone operation, additional chat or backend webhook is needed. Continue
using the three recommended chat operations. Own-child access, observation dates,
partial/unknown app-counter periods, consent, raw token limits, idempotency and
unknown holds remain enforced. Ordinary source-review pushes respect quiet hours.
See [the source-review checkpoint](mana-source-reviews.md) for private v13/v4
storage, real-model receipts, corrected cost calculation and remaining acceptance.

## 16. Parent assistant reminders (local, default disabled)

With the complete family profile and `MANA_PARENT_REMINDERS_ENABLED`, the same
chat supports reminder drafts, date clarification, explicit confirmation,
cancellation and a later agent message. No new public endpoint or second chat
is needed. This has not been released to production.

When history exposes `active_confirmation`, bind the parent's real answer:

```json
{
  "parent_id": "900001",
  "request_id": "a65dc5a1-30c3-4c2a-bf53-06ee8eb79ae7",
  "message": "Да",
  "reply_to_confirmation_id": "4c20aabf-a16b-4ca0-b790-b8ef2e98ede7"
}
```

Use the actual active ID from that parent's history, not these fictional values.
Keep `reply_to_question_id` for child questions; an active child question has
priority and the two bindings must not be combined. The host preview displays the
exact task, date/time and timezone. A model draft alone schedules nothing.
Only an affirmative reply to that exact active preview schedules the reminder.
History also exposes bounded active `reminders` with explicit lifecycle status.

Supported confirmation/date/list/cancel controls need no additional model call,
including after chat quota exhaustion. The later message uses the same history;
observe it through the existing history GET. A host-only response has zero model
usage and may omit `child_context_collected_at`; do not invent a source date.

Push permission is separate: backend-verified contact context adds optional
`assistant_chat_consent` and default-false `assistant_push_consent`. Do not infer
these from safety/marketing settings or from the AI's text. A confirmed timer
permits its specific chat reminder; an explicit current chat veto cancels delivery.
See [ownership, limits, storage and actual evidence](mana-parent-reminders.md).

## 17. Retention / Win-back through Parent-Touch (local, not released)

`MANA_CLIENT_RETENTION_ENABLED` adds one supported proactive scenario: a check-in
after a verified gap in the parent's own chat. Parent-Touch remains the only
speaker; no new phone endpoint, second chat or backend webhook is required.
It must not be interpreted as per-parent app-churn prediction.

Optional backend-verified `retention_chat_consent` and `retention_push_consent`
default to false. Supply them through the existing contact-context contract only
when actually verified. Safety, marketing and assistant permissions do not imply
Retention permission. Quiet hours, current consent and specialist priorities are
checked before generating/publishing. Push follows durable chat storage separately.

The parent simply replies through the standard message POST. A returned-to-chat
observation is recorded once; normal Child-Safety review and Parent-Touch continue.
`не пиши первым`, `birinchi bo‘lib yozmang`, and `stop check-ins` are supported
persistent opt-outs, acknowledged without inference even after quota exhaustion.
They do not change safety permissions or revoke an already dispatched push.

See [implementation, exact limits and real-model evidence](mana-client-retention.md).
The workflow is local, private schema v15, and default disabled. Do not call these
additions on production until an explicit release is confirmed.

## 18. Upsell price enquiries in the same chat (local, not released)

The default-disabled `MANA_CLIENT_UPSELL_ENABLED` adds no mobile route or chat.
Post the parent's ordinary message, observe its existing message status, then keep
refreshing the same single history. For an explicit price/duration request,
Parent-Touch acknowledges it and later publishes the exact dated catalog quote
as another assistant message with its own `turn_id`. Do not insert a second copy
in the application or treat original-message completion as the final history head.

For example: `Покажи самый дешёвый тариф на 90 дней в UZS`.
The model extracts the request; code selects a real observed tariff by exact
currency, term and total price. Catalog prices do not establish feature upgrades,
recipient eligibility, checkout or renewal. Nothing is purchased or granted.
This path sends no push and requires no new backend event. One shared catalog
cache/read ledger bounds acquisition across parents; failures are not retried.
Existing 2000 speaker/2000 global safety limits remain. Old captured turns do not
upgrade. See [the implementation/evidence](mana-client-upsell.md) and run
`make chat-lab-upsell` for fictional UI tests. These new paths are not released.

## 19. Parent account context (local, not released)

The same ownership-filtered Parent List response can now supply Parent-Touch with
its selected current tariff, paid flag and expiration. The phone uses the existing
message/status/history API; there is no new account-chat endpoint or extra billing
read. Ask the agent which tariff the app shows or when it expires.

A display name is not a feature entitlement, full payment history or renewal
contract. Missing/malformed fields stay unknown and do not discard valid child
profiles. Child-Safety receives no new profile billing fields. Existing chat/safety
limits and action policies remain; nothing is purchased, granted or renewed.
Use `make chat-lab-profile` for fictional RU/UZ tests. Evidence and the qualified
real-parent/model checks are in [the account context checkpoint](mana-parent-account-context.md).
These local changes are not a production release.

## 20. Source-driven expiry reminder (local, not released)

With the explicit server expiry profile enabled, a new ordinary MANA profile
observation can produce one Parent-Touch reminder before the parent has written.
The profile's selected paid term must end within 72 hours, evidence/contact settings
must be fresh, and independent Retention chat consent/quiet hours/opt-out/priority
must pass. There is no extra required webhook, mobile endpoint or expiry scan.

The phone keeps observing the existing single history: it receives an assistant-only
message with a new `turn_id`, then submits the parent's ordinary reply. Do not
insert a duplicate message or manufacture a user question/confirmation. Exact date
rendering makes zero model calls; the subsequent reply uses existing models/limits.
There is no renewal, payment, trial reward or loss-of-protection claim.

An independently allowed push remains neutral and references that same saved chat.
Queueing is not delivery; unknown sends never retry automatically. Use
`make chat-lab-expiry` for fictional checks. See [policy/evidence and partial coverage](mana-retention-expiry.md).
Turning only `MANA_RETENTION_EXPIRY_ENABLED` off on a v17 store stops expiry
observation, publication and pending expiry pushes while retaining the compatible
core chat services and all history, quotas and deduplication. It never resets a
source circuit or permits an older image to execute that schema.

## 21. Reuse bulk Parent List tariffs (local, not released)

With explicit `MANA_COLLECTION_TARIFFS_ENABLED` and its collector/expiry profile,
the existing 09:00/15:00 collection shares selected paid/end-time facts with Retention.
It adds no mobile operation or required backend event, and makes no second read for
each recipient or agent. Known page completion and a minimized batch commit together;
the local receiver is one-shot. Old/disabled/unknown/late claims never upgrade.
Parents without queued child-source targets can qualify through the same verified
contact policy; inventory membership or a tariff never supplies consent.

The application still retrieves the assistant message through the same chat history.
Source ages, safety priority, opt-out, outreach caps, neutral push policy and token
limits are unchanged. Default is off; production has not been activated. Use
`make chat-lab-inventory-tariffs` for fictional windows and
[the source/compatibility evidence](mana-inventory-tariffs.md) for the precise limits.

## 22. Date-filtered family usage source (adapter only)

This heading describes the original source-port checkpoint. The subsequent local
integration in section 23 connects it to the existing chat without a new mobile route.

A local typed adapter can obtain one completed calendar day's labeled app counters
for a verified family through the existing bulk Manakids API. It reuses one fresh
ownership lookup/authentication and preserves partial/missing data. This is **not
yet an agent tool, scheduled producer or mobile endpoint**; keep the existing three
chat operations and do not invent a new production path. Old app-counter calls keep
their original contract. Calendar labels do not establish screen time or timezone.
See [source evidence and required integration](mana-family-day-usage-source.md).
These additions are not enabled or released on production.

## 23. Dated child app questions in the same chat (local, not released)

With the complete v18 profile and `MANA_FAMILY_DAY_USAGE_ENABLED`, new reviewed
messages let Child-Safety select a completed query day using its typed source tool.
Continue using the same message POST, message-status GET and history GET. The mobile
client passes no username, Firestore query or tool call and opens no additional chat.

One family/day page is cached for siblings; each selected child still needs fresh
ownership. Missing child rows and incomplete app pages remain explicitly unknown.
Parent-Touch displays the requested YYYY-MM-DD label without equating it with a
verified screen-time measurement period or timezone. Language follows the parent.
Existing 2000-token speaker/global safety budgets, raw usage/unknown holds and
one-shot source limits remain. The collector's schedules are unchanged.

`make chat-lab-day-usage` exercises this with fictional providers. Read the
[complete implementation, negative diagnostics and acceptance limits](mana-dated-source-workflow.md)
before enabling it anywhere. A narrow actual Uzbek model case passed after several
retained budget failures; broader quality/capacity and production release remain open.

## 24. Shared dated collection and proactive reports (local, not released)

With the complete v19/source-v6/collection-v3 profile and explicit
`MANA_FAMILY_DAY_REVIEWS_ENABLED` / `MANA_COLLECTION_DAY_USAGE_ENABLED`, newly
captured 09:00/15:00 Asia/Tashkent windows read one preceding-day family app page
and share it with sibling/native consumers. Existing battery collection remains.
Only changed child/day facts reach the existing Child-Safety review queue;
Parent-Touch can publish one assistant-only report before the parent writes.

Use the same message POST, message-status GET and single history GET. No new
phone route, username, cloud query, model tool payload or fabricated user message
is needed. Continue observing history for later specialist messages and separately
permitted neutral notifications. The query date is not a verified measurement
period or timezone; missing child data never means zero activity.

All flags default off, budgets/consent/quiet hours remain unchanged, and old
windows/claims/turns never upgrade. No ordinary customer tariff is granted.
`make chat-lab-day-collection` exercises fictional fixed-clock windows and cache
reuse, not live cloud acquisition or model quality. Read
[the implementation, exact engineering/model/browser evidence and limits](mana-dated-collection.md).
These additions have not been deployed. Keep using the released API until its
separate scoped rollout is confirmed.

## 25. Shared profile changes can stop commercial contact (local, not released)

With the explicit family-v20 `MANA_CONVERSION_SHARED_PROFILE_ENABLED` profile,
existing profile reads and known inventory tariff batches also check newly
captured conversion events. No additional phone operation, backend event or
source query is needed to stop an offer after a paid/unknown/changed tariff is
observed. Missing/stale/closed source evidence also refuses captured work.

Only Parent-Touch publishes. A saved chat message stays in history; an unsubmitted
marketing push is checked separately against the original proposal and current
permissions. The original conversion-event replay returns its original receipt,
so use the existing proposal GET for current lifecycle status. Replay must not
reopen a cancelled offer or trigger another read/send.

This shared cache is a veto, not proof of free use, consent, activity, all active
entitlements or payment. The existing authoritative eligibility and approved
billing terms are still required. A paid source record is not a measured payment
outcome. Defaults/budgets remain unchanged; old events never acquire new checks.
Run `make chat-lab-shared-conversion` for fictional profile/offer/paid-veto examples.
Read [the exact implementation, compatibility and acceptance limits](mana-shared-conversion-profile.md).
This increment has not been deployed.

## 26. Parent-Touch chooses the specialist (local, not released)

The default-disabled family-v21 `MANA_PARENT_TOUCH_MANAGER_ENABLED` profile keeps
the same message POST, status GET and history GET. The phone never selects an
agent, submits another chat ID or inserts a placeholder assistant message.

New eligible messages start in the existing `responding` phase while Parent-Touch
either replies normally or chooses one existing owner. Greetings/general app
conversation use only the parent's chat budget. A child request transitions to
`awaiting_review` under the same `request_id`/`turn_id`; Child-Safety reviews it,
then Parent-Touch publishes the final response. Tariff/reminder requests remain
`responding` through their selected typed preparation. A reminder still requires
the existing separate confirmation; a tariff enquiry creates no payment or grant.
Replies to an admitted specialist question retain the original review-first path.

Observe the existing status/history APIs until completion or a terminal error.
GET, refresh, a dropped connection or exact POST replay never starts another
generation. Unknown receipts retain quota holds. The final usage includes both
Parent-Touch decisions under the original **2000 raw tokens/parent/day**;
Child-Safety keeps its separate **2000 global/day**. Budget exhaustion still stops
child analysis and does not silently enlarge either allowance.

The server freezes language/model/scope at admission. Historical messages never
upgrade on flag changes. A late/disabled/changed decision is refused after known
usage is accounted. This profile does not activate source refresh or contact
permissions. Try `make chat-lab-manager` with fictional providers and explicitly
simulated models. Read [the implementation, retained negative diagnostic and
actual acceptance limits](mana-parent-touch-manager.md). Production remains on
the earlier release until a separately scoped rollout is confirmed.

## 27. Production migration rehearsal (not a release)

The actual deployed v6 history was copied consistently in read-only mode and
upgraded to v21 **locally** in the exact current image, without networking or real
keys. History and exact old-request replay passed through the production HTTP
factory; all sixteen original tables retained every original cell. The current
closed reader returned the same history. Production remains `f8d095e`; do not
assume the local sections above are enabled there.

For a future full dated-source profile the default SDK/read bounds require an
explicit 360-second native SQL lease; token limits remain unchanged. Do not use
old images against a migrated v21 file, restore stale backups over newer chats,
or interpret this rehearsal as working execution rollback. Read
[the exact evidence, selected profile and outstanding release requirements](mana-production-upgrade-rehearsal.md).

## 28. Confirmed free-access reminder (local, not released)

New complete known free-day grant receipts can support a single pre-expiry
Parent-Touch message. The phone continues to use the same message POST, status
GET and history GET. It must not insert another assistant message, create a chat
or activate a tariff itself. Existing trusted-backend trial acceptance remains
the only grant path; an ordinary chat reply does not yet invoke that action.

The worker requires the recorded new grant period, independently fresh matching
nonpaid tariff facts and current Retention contact permissions. It respects quiet
hours, conversation idle, safety priority, opt-out and outreach caps. Missing or
historical metadata is not reconstructed. The message names the confirmed days
and local deadline, without claiming renewal, payment or protection loss. A
permitted neutral push follows the persisted message through the existing outbox.

The reminder uses no additional model tokens or source reads. A parent's following
price question uses the existing scoped catalog workflow and the original daily
chat budget. Language, timezone and permission remain independently verified.
No new payload or public API schema is required by the application.

Try `make chat-lab-trial-periods` for an explicitly fictional one-day grant history
and same-chat price enquiry. This is a local default-disabled family-v22 feature,
not confirmation of production activation. Read
[implementation, test evidence, model diagnostics and rollback limits](mana-confirmed-trial-periods.md).

## 29. Last-point GPS context (local, not released)

The phone still uses the same message POST, message-status GET and history GET.
The trusted server can now provide Child-Safety with the exact owned child's
last-point metadata through its existing native tool and shared cache. No mobile
Firebase credential, document path, new chat or client-selected agent is required.

Parent-Touch preserves the observation date and uncertainty. A stored point,
server update or recent collection is not the child's confirmed current position.
The model receives no coordinates/address/route. If useful, the parent can open
the application's existing map; this update does not add a new map/deeplink action.

New source changes can reach the existing coalesced review and first-contact flow
without waiting for a parent message. Current independent contact consent,
language/timezone, quiet hours, safety priority and outreach caps remain mandatory.
The persisted assistant message precedes any separately permitted neutral push.
Reading GPS never grants contact permission. Existing collector occurrences stay
09:00/15:00 Asia/Tashkent; this feature creates no refresh timer or listener.

Try `make chat-lab-location`: the declared fictional source scenario first writes
into the empty chat, then an ordinary location question uses its cache. The lab
uses a running clock and respects quiet hours. It has no live Firebase, push,
payment or grant adapter. Read
[implementation, actual source/model checks and capacity limits](mana-family-location-source.md).
This local family-v23 profile is default disabled and has not been released.

## 30. Test action confirmation buttons

The local web chat now accepts caller-defined action text and confirmation/cancel
button labels. Run `make chat-lab-actions CHAT_LAB_PORT=8098`, then open
<http://127.0.0.1:8098>. The action is attached to one assistant message in the
same chat. Explicit button clicks have durable, definition-bound decisions;
refresh, duplicate clicks and restart never repeat the simulated execution.

The test-only API and examples are documented in
[Confirmation cards](mana-chat-action-cards.en.md). Only `sandbox_demo` is wired.
This is not a production path, actual trial activation, payment or push. Real
action kinds must use their owning domain lifecycle and separately scoped release.

## 31. Trial offers with confirmation buttons (local lab only)

`make chat-lab-trial-actions CHAT_LAB_PORT=8099` demonstrates a newly admitted
trial offer, explicit parent button confirmation, the existing owning one-time
grant lifecycle and a dated Parent-Touch result in the same chat. It uses a
fictional one-day gateway; no real tariffs or customers are changed. Generic
card payloads cannot choose grant days or create trial actions.

Use the same card list/GET/click endpoints from section 30 and render the card
beside its existing offer `turn_id`. `trial_granted`, `trial_rejected` and
`trial_unknown` outcomes are distinct. Do not turn a click into a fabricated parent
message or call the legacy text-based acceptance endpoint. Replays, new nonces,
restart and unknown outcomes never redispatch. Existing quotas remain unchanged.
Read [the typed lifecycle and compatibility details](mana-trial-action-cards.en.md).

## 32. Confirmed free-period end (local, not released)

The phone continues to retrieve the same chat history. A new confirmed free-period
grant may now produce one assistant message after a fresh source observation
confirms the known period ended and the selected tariff is nonpaid. No synthetic
user message or client-side timer should insert it. The parent may then ask about
tariffs through the ordinary message endpoint; the existing catalog workflow
returns supported prices without creating a payment.

Current independent Retention permissions, language/timezone, quiet hours,
priority, opt-out and frequency limits remain mandatory. Merely reaching an end
date is insufficient. The initial notice needs no model/source call; subsequent
dialogue keeps the original daily token limit. A separately allowed neutral push
follows the saved message and never contains family details.

Try `make chat-lab-trial-end CHAT_LAB_PORT=8100` for the explicitly fictional
October 26–28 scenario. This default-disabled family-v26 feature has not been
released. Read [evidence, costs and remaining limits](mana-confirmed-trial-end.md).

## 33. Independent processing (local, not released)

The mobile chat contract is unchanged. The server can run bounded independent
Child-Safety, Parent-Touch, reminder, tariff and notification workflows: a slow
analysis for another family no longer delays an ordinary reply or an allowed
push for an already saved message. A family awaiting its own safety review still
waits; question order, ownership, quiet hours, permissions and token limits remain.

Do not duplicate a pending request or open another chat because analysis takes
time. Continue observing its existing message-status GET and history GET. Neither
read redispatches work, and an unknown submitted model/source/push is not retried.

The new server flag is explicit and defaults off. Try the fake single-chat lab
with `make chat-lab-parallel CHAT_LAB_PORT=8101`. Read
[processing, failure and compatibility details](mana-parallel-family-worker.md).

## 34. Safety allowance reuse (local, not released)

The phone still sends one parent message and observes its existing result/history.
The server may now analyse multiple distinct new child observations within its
original daily Safety allowance, using verified usage left after earlier work.
This does not increase the parent's chat budget or guarantee a fixed number of
real analyses per day. Old/unknown requests are never repeated to fill the budget.

If the complete analysis cannot fit, the server keeps the original context and
returns/records the existing budget failure rather than substituting a smaller
question. The app must not automatically retry it with a new ID or reduced data.
Try `make chat-lab-remainder CHAT_LAB_PORT=8102`; read
[accounting, migration and evidence limits](mana-safety-remainder.md).
