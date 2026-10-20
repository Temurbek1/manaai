# Parent-Touch / Child-Safety: backend integration

Local implementation, **not deployed**. The current production parent chat is
still the independent `f2c023f` service. Do not direct mobile clients at these new
routes until a separately reviewed release configures their isolated ingress.
The latest model/language/quality limits are in the
[review-first checkpoint](mana-family-review-first-checkpoint.md). The coordinated
workflow is implemented locally; broader real-family/release acceptance is separate.

## Contract

All paths below start with `/api/v1/mana-ai`. The trusted MANA backend authenticates
with the **isolated parent-chat bearer credential**, derives `parent_id` from its
own authenticated session, and checks that the caller may use that family. Never
embed this credential in mobile, share it with general inference/360REC, or accept
an arbitrary parent's ID supplied by the phone. Parent IDs are canonical profile/
Firebase numeric strings, not Firebase Auth UIDs. One parent always has one chat.

| Method / path | Use |
| --- | --- |
| `GET /agents` | Actual configured support/worker status |
| `GET /parent-touch/chat?parent_id=123` | History, quota, active question and delivered notice metadata; SQL only |
| `POST /parent-touch/chat` | Parent text and optional explicit reply binding |
| `POST /parent-touch/messages` | Recommended new flow: save text, `202`, specialist review before speaking |
| `GET /parent-touch/messages/{request_id}?parent_id=123` | Private SQL status and final Parent-Touch response |
| `POST /parent-touch/deliver` | Backend-only admission of a queued assistant communication |
| `GET, POST /parent-touch/requests` | Internal registered specialist questions; never expose producer access to mobile |
| `POST /child-safety/{protective-capability}` | Admit new dated child observations, asynchronous `202` |
| `GET /child-safety/assessments?parent_id=123` | Page internal jobs/results; `after`/`limit`, no inference |
| `GET /child-safety/assessments/{job_id}?parent_id=123` | Same-family status/result; no dispatch |
| `GET /child-safety/budget?parent_id=123` | Separate server/parent analysis budget and unknown holds |

The ten endpoint suffixes are `safety-monitor`, `family-digest`,
`adaptive-screen-time`, `location-intelligence`, `smart-content-filter`,
`scam-privacy-shield`, `ai-gaming-safety`, `child-safety-assistant`,
`family-agreement`, `behaviour-anomaly`. Each has its **own** typed schema. There
is no generic `/analyze` endpoint. Existing synchronous capability endpoints and
legacy `GET,POST /chat` remain compatible; `/chat` shares history/quota but lacks
question/notice metadata. New integrations should send to `/parent-touch/messages`
and read the shared `/parent-touch/chat` history. Synchronous `/parent-touch/chat`
remains compatible but does not acquire review-first ordering.

## Recommended asynchronous message flow

Send the message JSON below to `POST /parent-touch/messages`; no `chat_id` or
sender selection is needed. The response is `202` with `phase=awaiting_review`.
Observe `GET /parent-touch/messages/{request_id}?parent_id=123` (for example once
per second while the app is waiting) or the same chat history. A completed state
contains `response.answer`, `response.asked_question` and the normal quota receipt.
Never render the internal specialist review as another sender. Stop observation
at `completed`, `failed` or `unknown`; do not create retry nonces automatically.

The backend may repeat the exact original POST after HTTP loss; it only observes
saved state. While one message waits/responds, another message returns `409`.
The existing five-minute preparation deadline also bounds review waiting. A failed
or unavailable specialist review does not fall back to independent Parent-Touch
analysis. The unchanged 2000 allowance covers the speaker; the specialist has its
separate server budget. New sensor facts use the protective endpoints, not
`child_observations` on this new message contract.

## One chat, one question at a time

Example parent message (IDs are fictional; generate a new UUID for a new intent):

```json
{
  "parent_id": "123",
  "request_id": "3a7454f8-38d2-4e8b-b251-017970f48350",
  "message": "Как помочь ребёнку?"
}
```

1. Display history `messages` in order. `message_questions` and `message_notices`
   map metadata to assistant `turn_id`; they are not extra chat messages/senders.
2. `active_question` may be on an older page. Before binding a reply, display its
   actual assistant turn. Preserve its `question_id` invisibly in the backend.
3. Add `reply_to_question_id` **only when the parent is answering that displayed
   question**. Missing binding never silently answers it. A stale/foreign/already
   answered binding gives `409 question_reply_mismatch`. Unrelated conversation
   may proceed without answering the pending question.
4. A response's `asked_question` and `delivered_notice` describe that exact turn,
   not the current queue. Replays keep those original identities. Refresh SQL
   history to observe the current active question; GET never generates a message.
5. Assistant-only specialist deliveries have **no fabricated user message**.
   Their wording follows the latest saved parent language/script. Until the parent
   has spoken, the service will not invent their language or send an unsolicited
   model-generated chat turn.

Parent-Touch alone phrases all messages. Child-Safety submits internal dated
results and at most one typed information need per analysis. The host queues by
priority/FIFO, coalesces matching needs and permits only one awaiting question.
Coalesced specialist subscribers share one answer rather than competing messages.

Validated `ALERT`/`BLOCK` assessments create a typed **urgent notice**. It can be
communicated while a question awaits an answer without opening a second question.
`WARN` and family-digest results may create ordinary notices; older unsent ordinary
results for the same child/capability are superseded. Ordinary notices wait behind
an active question and can be deferred without another immediate paid attempt.
Other results remain available as dated context without unsolicited messages.
Unsent notices expire after a day; unknown paid submissions remain held instead.

This is **not an emergency service**, push delivery, a diagnosis, proof of danger,
or permission to alter controls. Notices still require established language, fresh
ownership, a verified model receipt and remaining Parent-Touch quota. Urgent does
not bypass these conditions. The backend must provide its own suitable critical-
event handling; do not rely exclusively on a quota-limited chat for emergencies.

## Child observations and event flow

The backend pushes new observations to the appropriate typed Child-Safety route.
Do not repeatedly call the old synchronous inference endpoints for the same data.
No Firebase/GA4 scan, listener, schedule or automatic source refresh is installed.
Polling here means private SQL queue observation, not polling the child's sources.

Example new safety observation:

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
      "battery": [{
        "evidence_id": "battery-001",
        "observed_at": "2026-10-20T08:59:00Z",
        "percent": 15
      }]
    }
  }
}
```

`child_id` must match `analysis.subject.subject_id`. Supply real observation dates,
not the time the request happened to be sent. `202 queued` is not ownership proof,
a finished assessment or a chat send. The worker verifies a fresh filtered MANA
profile before model work and refuses revoked/foreign children. Child chat
observations on the message endpoint remain conversational context; send the
appropriate typed protective request when a new sensor analysis is required.

New parent messages atomically enqueue a separate Child-Safety review of bounded,
dated saved chat/results. Assistant-only sends and history reads do not trigger it.
Unchanged normalized child observations coalesce even if a nonce, revision label,
locale, evaluation time or equivalent UTC offset changes. A new parent message
does not repay for old sensor data: it has its own review event. Parent text is
not a sensor measurement or source/tool authority.

Parent-Touch freezes one minimized validated assessment at synchronous admission
(or at the new review-first communication claim), including
all quality notes and distinct observation/evaluation/processing dates. Its total
report count and supplied-report limit are explicit. This bounded context is not
complete/current coverage or all children's history. Saved results never authorize
control changes, provider calls, new recipients or direct specialist speech.

## Errors, idempotency and budgets

A trusted backend may explicitly continue a previous assistant-only delivery
after a pure pre-generation quota refusal on an earlier local day:

```json
{
  "parent_id": "123",
  "request_id": "d339e77e-0dc3-45c2-84e2-909919c42475",
  "resume_deferred_request_id": "e8aa6fc5-0722-44ea-a3d4-91832f658284"
}
```

The original request must have no raw receipt or reserved cost; the same current
primary communication choice and parent-language turn must still qualify. This is
one explicit new intent per local day, with normal ownership/expiry/quota checks,
not an automatic worker retry. The original refusal/replay stays unchanged. Paid,
invalid, unknown, same-day and changed-context requests cannot be continued this
way. GET, polling and midnight do not dispatch it.

- Reuse the **identical UUID and body** after HTTP loss. Replays return saved state
  without another source read or inference. A conflicting body gives `409`.
- `failed`/`unknown` jobs and their error codes are durable. Do not implement a
  loop that creates new nonces after errors. Unknown submitted usage retains its
  hold across restart/midnight; status reads do not clear or retry it.
- Parent-Touch counts raw **input + output** against 2000 tokens/day by default,
  including prompt/schema/history and assistant-only deliveries. This is not 2000
  output tokens, messages or a guaranteed number of answers. Day boundaries use
  configured `MANA_PARENT_CHAT_TIMEZONE`. A small remaining quota may not fit even
  a short reply's input. `429` is a controlled quota/attempt/pending-cap refusal.
- New Parent-Touch turns reserve room for structured output (normally at least
  128 tokens; 256 with a selected question/notice, capped by the configured output
  ceiling). Older history may be removed after one verified alternate input count,
  never current facts, dates or quality notes. Insufficient space refuses **before
  generation**. A floor cannot guarantee semantic quality or that every answer fits.
- Child-Safety separately enforces explicit server/day, parent/day and per-job
  token ceilings, pending/attempt limits and one active job per family. No shared
  chat allowance, hidden renewal or transport/model retry. Verified invalid model
  decisions still cost tokens; unknown costs must not be treated as zero.
- `401`: backend credential missing/invalid. `403`: fresh ownership refused where
  applicable. `404`: no same-family job. `422`: invalid typed data. `502/503`:
  controlled model/source/runtime failure. Public errors do not expose providers,
  prompts, keys or family records. Responses have `Cache-Control: no-store`.

## Activation and compatibility

All new flags default off. A reviewed configuration must enable
`MANA_PARENT_CHAT_ENABLED`, `MANA_PARENT_TOUCH_ENABLED`, `MANA_CHILD_SAFETY_ENABLED`,
`MANA_PARENT_TOUCH_REVIEW_FIRST_ENABLED` for the new message workflow,
and explicitly set `MANA_CHILD_SAFETY_LIMITS` (`server_daily_tokens`,
`parent_daily_tokens`, `job_tokens`, with `job <= parent <= server`). These are
token ceilings, not an approved production spend. Use one dedicated private volume,
the existing isolated backend credential and `APP_ENV=production`.

New-role model defaults are `MANA_PARENT_TOUCH_MODEL=gpt-5.4` and
`MANA_CHILD_SAFETY_MODEL=gpt-5.4-mini`. They do not change `OPENAI_MODEL`, legacy
chat mode, audio or the old stateless endpoints. Both are configurable; programmatic
`None` explicitly inherits `OPENAI_MODEL`, not a provider fallback/retry. There is
no automatic model escalation. Model changes need their own quality/cost evaluation.
The explicit Child-Safety server budget is still mandatory before activation.

Review-first uses additive private SQLite v6. Its same-candidate safety-off broker
retains message observation/exact replay without a safety model/worker; new review
admissions refuse. Disable both safety and the review-first flag for that profile.
Old v5/production readers refuse v6, not a working rollback. See the review-first
checkpoint before any release; the older v5 compatibility description below is
historical, not permission to downgrade v6.

Technical UUIDs never enter the new model publication schema. The model writes
one optional question and a `notice_communicated` boolean; the host binds them to
the frozen SQL choices, revalidates them and publishes atomically. The public
request/response/reply UUIDs stay unchanged. A notice with known signal dates must
include those **UTC calendar dates** as `YYYY-MM-DD`; collection time cannot stand
in for observation time. Invalid output retains verified charges and publishes
no text, rather than silently correcting/retrying a paid answer.

Language hints conservatively recognize RU, Uzbek Latin/Cyrillic and English; they
are not a universal detector. A neutral reply (`да`, `Ha`, `7:00`) inherits the
previous same-family frozen parent reference. New substantive prose does not
silently inherit another language. Unknown languages stay model-directed using
the parent's text. Clear recognized output mismatches are withheld after accounting.
Hints affect presentation only, never ownership, sources, tools or budgets.

V5 is additive: old chat responses/digests/usage/unknown holds stay intact; historical
turns are never recaptured as new events. Disabling only Child-Safety selects the
same-candidate broker-only reader without a safety provider/worker. Disabling
Parent-Touch selects history/exact-replay-only mode, refusing new inference. Neither
mode downgrades schema or erases data. **Old production/v1–v4 images refuse v5**;
do not claim they can roll back populated history or restore an old backup over it.

New safety snapshots use private context v2, with pending conversation needs and
recent explicitly bound answers frozen in the chat-admission transaction. The
typed parent-review bit is captured only in new snapshots: its schema permits
`analysis=null`, a historical summary and an optional information need, never a
fresh sensor analysis. Historical v1 and earlier v2 snapshots retain their original
protocol; initialization/replay does not recapture or upgrade them. The old `1bea31c`
reader cannot execute new contexts even though the outer SQLite version stays 5.
Use the **new same-candidate closed profiles**, not an old worker, for deactivation.

Hermetic local/candidate smoke (synthetic profiles and SDK MockTransport only):
`python -m scripts.mana_family_agents_smoke`. This is not a live provider or
real-family quality test. Actual gates and remaining acceptance are recorded in
[the checkpoint](mana-family-agents.md).
