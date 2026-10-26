# Confirmation cards in the test web chat

This is a local, simulation-only prototype. Parent-Touch publishes one assistant
message in the existing parent's chat and attaches a durable confirmation card.
The caller supplies its title, text and the labels of two buttons. A click is a
separate request, bound to the exact displayed definition. Plain chat text never
confirms this action. The prototype cannot grant tariffs, create payments, send
push notifications or invoke arbitrary URLs.

Start from this checkout:

```sh
make chat-lab-actions CHAT_LAB_PORT=8098
```

Open <http://127.0.0.1:8098>. Select **Действие с кнопками**. To change the text and
button labels, open **Под капотом → Карточка действия**. This factory always uses
fictional sources and models, one fictional parent `900001`, a private local
SQLite database and no paid/provider calls. Other lab profiles keep cards disabled.

The following paths are present only in the test server, not the production API.
OpenAPI is at `/openapi.json`. Existing production chat contracts are unchanged.
The lab requires its HttpOnly session cookie, matching `Origin` and `X-Lab-CSRF`
header on every POST. The CSRF value is supplied by the lab HTML's `lab-csrf` meta
tag. Do not move this local session mechanism or credentials into a mobile app.

## Create a card

`POST /api/v1/mana-ai/parent-touch/action-cards`

```json
{
  "parent_id": "900001",
  "request_id": "62aeecb7-adc3-4f65-91ac-f8e052f0f3d7",
  "action_type": "sandbox_demo",
  "title": "Confirm the test action",
  "text": "Check the confirmation flow. No real customer data will change.",
  "buttons": [
    {"id": "confirm", "label": "Confirm"},
    {"id": "cancel", "label": "Cancel"}
  ],
  "expires_in_seconds": 900
}
```

Response `200` includes `card_id`, `turn_id`, `definition_hash`, the supplied text
and buttons, server dates, `mode: "simulation"` and `status: "pending"`.
Render it beside the assistant history message with the same `turn_id`; do not
insert a second copy of that message or create a new chat. Treat all labels and
text as plain text. Button IDs have fixed semantics, independent of their labels.

Exactly two distinct button labels are required, one `confirm` and one `cancel`.
Title/text/labels are limited to 120/1000/80 characters. Expiry is 60–3600 seconds.
The same parent/request UUID and body observe the original card/message; changing
the body with that UUID returns `409`. Only one unresolved action is admitted per
parent. The prototype retains at most 20 new cards per parent per rolling day and
500 total; it refuses further admission rather than deleting audit/history.

## Submit a decision

`POST /api/v1/mana-ai/parent-touch/action-cards/{card_id}/click`

```json
{
  "parent_id": "900001",
  "request_id": "81a21d71-b3b0-4c54-8cb9-58faf45bb250",
  "button_id": "confirm",
  "definition_hash": "COPY_THE_64_CHARACTER_HASH_FROM_THE_CARD"
}
```

Generate a new UUID for the first explicit click. Persist its exact body before
POST. A repeated identical click, including after restart, only observes its
existing decision. A new nonce cannot repeat an execution; an opposite choice
after a committed decision returns `409`. A mismatched definition or expired card
also returns `409`. A cancel decision never invokes the executor.

Confirmation atomically saves an `executing` claim before calling the typed fake
executor. A known simulated result changes status to `completed` and includes:

```json
{
  "mode": "simulation",
  "execution_id": "b137bc17-d888-44d8-803b-a6ec450234ba",
  "outcome": "simulated_success"
}
```

This is a UI/workflow receipt, not a successful real business action. Raw model
quotas remain unchanged because this prototype makes no model calls. Errors or
cancellation after claim produce `unknown`; a process crash may leave `executing`.
Neither is retried automatically. The chat message remains in history.

## Observe only

```text
GET /api/v1/mana-ai/parent-touch/action-cards?parent_id=900001&after=0&limit=20
GET /api/v1/mana-ai/parent-touch/action-cards/{card_id}?parent_id=900001
```

The list returns `cards` and nullable `next_after`. Follow that cursor until null;
the maximum page is 100. GET, refresh, reload and server reconstruction never
execute actions. The test UI polls local SQL state, including card statuses, and
does not resend a click on a lost response. If SQL still reports `pending`, the
user may explicitly retry the **same stored choice and nonce**. The alternative
button stays disabled. `expired` is an observation of server expiry, not a source
read or background job.

Unauthenticated access returns `401`, wrong session origin/CSRF/family returns
`403`, an absent family-owned card returns `404`, invalid schema returns `422`,
capacity returns `429`, and a disabled lab profile returns `503`.

Safety questions/notices and in-flight chat work gate new confirmation cards and
confirm decisions; cancellation remains available. The prototype requires the
button while a card is pending. Urgent bound safety replies remain admissible.
An unknown action retains its hold and is never automatically retried.

## Storage and future integration

The dedicated lab profile adds private family schema v24 with `lab_action_cards`
and append-only `lab_action_events`. Creation and its assistant message share one
SQLite transaction. Claims/results are separate audited transactions; no user
message is forged. The previous v23 reader refuses these added tables; this is
not an execution rollback or a production migration. Keep the lab's private
directory and use this current prototype reader to observe its unresolved claims.

Real action kinds must delegate to their existing owning domain policies and
executors with fresh entitlement/ownership/consent checks, verified terms and
unknown-outcome recovery. A generic confirmation button is not permission to
grant a tariff, perform payments or execute an arbitrary provider payload. That
integration and mobile/production release remain separate work.

## Verification — 2026-10-26

`make verify` passed with an explicit dummy inference key: Ruff/format/lint,
mypy (428 files), TypeScript, 1507 backend tests, 26 admin UI tests, 13 chat-lab
tests, production UI build and npm audit (zero vulnerabilities). The one skip and
two excluded live tests are not passes. The first gate attempt stopped during
collection because this clean worktree had no required dummy key; it was not a
passing gate or a real inference request. Logs remain separate under
`output/action-cards-20261026/verify*.log`.

The six dedicated HTTP/SQLite tests cover concurrent duplicate confirmation,
replay/restart, cancellation/expiry, authentication/CSRF/family/definition binding,
unknown and lost execution claims, task cancellation, atomic message/card rollback,
urgent-question admission and disabled profiles. The focused 29-test run includes
these and existing chat/location cases; counts overlap with the full gate.

Actual Chromium exercised default confirmation, custom Uzbek button labels,
cancellation and a deliberately lost successful click acknowledgement. Three
assistant-only messages produced two simulated executions and one cancellation,
with zero model tokens. Text containing an HTML image/onerror string remained
literal text with zero injected images. Reload and an actual server restart
preserved all rows in 63 SQLite tables with an identical fingerprint and no new
execution. Initial restart navigation raced server readiness and failed; explicit
navigation after startup passed without another POST. The inspected 390px mobile
screenshot has no document overflow or browser script errors. Evidence is in
`output/action-cards-20261026/{before-restart,browser-restart}.json`, server logs
and `mobile.png` (local, not committed).

These are fake-executor/workflow checks, not model quality, real action delivery,
mobile integration, production release or acceptance of the remaining agent goal.
