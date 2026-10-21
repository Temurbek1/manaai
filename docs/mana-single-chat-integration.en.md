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
