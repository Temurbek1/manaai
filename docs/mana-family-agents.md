# MANA family agents — implementation in progress, 2026-10-20

This replaces the application-facing agent design, not the four operational
administrative agents. It does not rename, resume or deploy the earlier broad
OPERATION workspace work. The isolated released parent chat `f2c023f`, its private
key/history/quota and main/audio services remain unchanged on production.

## Owner's requirements and confirmed choices

- **Parent-Touch is the only parent-facing speaker.** One parent has one durable
  chat, never separate chats or visible competing agents. Parent-Touch communicates
  and coordinates; it does not change limits, permissions, locations or accounts.
- **Child-Safety owns child protection and behavioral analysis.** Reuse the ten
  existing protective MANA AI contracts; Parent Copilot's conversational role moves
  to Parent-Touch. Keep the legacy inference endpoints compatible. Specialist
  results, questions and proposed actions are internal data, not direct chat sends.
- Trigger Child-Safety on **new child data or new parent messages**, not periodic
  rereads or repeated inference on an unchanged version. It reads the correct
  parent's bounded saved conversation with an explicit cutoff. Historical family
  text is not a new sensor measurement or a source/action grant.
- Specialists propose a single information need with a stable key, evidence/date,
  priority and expiry. Parent-Touch sorts, filters/coalesces duplicate information
  needs and phrases at most **one active question**, then binds one answer before
  asking the next. The API must carry the invisible question/reply identity;
  natural-language relevance must not silently attach an answer to another child.
- The owner confirmed **2000 raw input+output tokens/day for Parent-Touch only**.
  Child-Safety needs a separate explicit server-wide budget and per-job/parent
  admission limits. No hidden additional budget, auto-renewal, provider retry or
  automatic release of an unknown model charge is allowed.
- Calls are through the trusted MANA application backend using the canonical
  profile/Firebase parent ID. Derive that ID from the backend's authenticated
  session. Fresh child ownership must precede new analysis or question delivery.
  The general inference token and 360REC clients must not read family history.
- Russian/Uzbek and other reply languages follow the parent, never an arbitrary
  specialist prompt. Data/prompt text cannot change grants, recipient or language
  authority. Raw child signals must not enter operational reports or logs.

## API shape — Parent-Touch implemented locally, Child-Safety still pending

All paths are under `/api/v1/mana-ai`; this remains an independent product API.

| Path | Purpose | Provider/mutation boundary |
| --- | --- | --- |
| `GET /agents` | Registered family roles, available contracts and support status | SQL/config observation only |
| `GET /parent-touch/chat` | Single history, quota, active reply identity and queue status | No source/model call |
| `POST /parent-touch/chat` | Parent message, optional explicit reply identity | One Parent-Touch generation under existing quota/unknown holds |
| `POST /parent-touch/deliver` | Deliberately admit one queued specialist communication | No fabricated parent message; one generation, no delivery retry |
| `GET /parent-touch/requests` | Backend observation of same-family question state | SQL only; no dispatch |
| `POST /parent-touch/requests` | A registered specialist's typed communication intent | Internal backend only; fresh ownership and durable dedup |
| `POST /child-safety/safety-monitor` and capability-specific peers | New dated child observations using existing typed protective contracts | Durable content/chat-version admission, separate analysis budget |
| `GET /child-safety/assessments/{id}` | Analysis/clarification progress and result | Same-family SQL observation |

Keep one endpoint-specific request/response schema for every protective capability.
Do not introduce a capability-discriminated generic `/mana-ai/analyze`, a second
chat, a user-selectable sender, arbitrary provider payload or contact/write tool.
Existing `/chat` must remain compatible and share the same Parent-Touch history;
both paths must use the same broker once that mode is enabled, not rival writers.

The four Parent-Touch/directory paths above are now implemented behind
`MANA_PARENT_TOUCH_ENABLED=false` by default. Enabling it requires the existing
isolated `MANA_PARENT_CHAT_ENABLED` runtime and its strong backend credential.
`MANA_PARENT_TOUCH_QUESTION_LIMIT` bounds pending questions (default 100).
No Child-Safety execution endpoint or worker is advertised as implemented.

`GET /agents` deliberately reports Parent-Touch `available`, Child-Safety
`not_implemented`; the latter's definition lists its existing protective contracts,
not a running background agent. Every new route uses `ParentChatBackendToken`,
not the general inference security scheme. The existing `/chat` contract is
unchanged and uses the same runtime/history/quota when Parent-Touch is enabled.

### Mobile/backend integration

Only the trusted application backend calls these routes. It derives `parent_id`
from its authenticated MANA profile, never an arbitrary mobile-supplied family ID.
The app still shows one chat and one message input; the backend supplies hidden
correlation fields, not separate specialist chats.

1. Read `GET /parent-touch/chat?parent_id=123`. `message_questions` maps assistant
   turns in that page to the exact question/child identity. `active_question` is
   the currently awaiting question, possibly on an older page; load its turn before
   presenting a reply UI. History/quota/question metadata share one SQL snapshot.
2. Send `POST /parent-touch/chat` with `parent_id`, a UUID `request_id`, `message`
   and, for an explicit answer, `reply_to_question_id` from that displayed question.
   Missing metadata does not silently attach unrelated prose to a child/question;
   a stale, foreign or already answered question returns `409 question_reply_mismatch`.
3. `asked_question` in the response describes only the question actually published
   by **that turn**. It remains unchanged on replay after the parent answers or
   another question becomes active. Read history for the current active state.
4. Internal specialists submit their dated `AgentQuestionRequest` to
   `POST /parent-touch/requests`. This validates the registered specialist and
   fresh connected child, deduplicates and queues; it does **not** send to the chat.
   `GET /parent-touch/requests` pages that parent's internal queue only.
5. `POST /parent-touch/deliver` accepts only `parent_id` and UUID `request_id`.
   It admits one queued question and stores an **assistant-only** turn, with no fake
   parent message or push notification. It freezes the latest saved parent text as
   its language/script reference and rechecks fresh child ownership before inference.
   No earlier parent text gives `409 parent_language_not_established`; no ready
   question/another active question gives `409 no_question_ready_for_delivery`.
   These refused admissions perform no source/model call. There is no automatic
   delivery worker yet; this is an explicit backend invocation.

Reuse the same request UUID and **identical body** after transport loss. Replays
never read children, resize input, regenerate or publish a question twice. Both
message and delivery inference count raw input+output toward the **same** default
2000 daily tokens. A new nonce cannot repeat a deferred delivery for the same
question and frozen parent-language turn. A genuinely new parent message changes
that context, without refunding any earlier verified model cost.

Producer admission is persisted **before** a new ownership source call. Exact
nonce conflicts, identical-body new nonces and already answered information-key/
source-revision requests are deduplicated before I/O. Coalescing retains specialist
subscriptions and the original question/observation window; only queued priority
may increase. Rejected, failed or abandoned producer admissions do not expire into
an automatic source retry. A genuinely new observation/revision is separate work,
not permission to replay an unknown charge or relabel old data as current.

## Durable flow

```text
new child data / accepted parent message
  -> deduplicated, bounded Child-Safety job
  -> verified own-child facts + dated saved chat cutoff
  -> separately metered safety assessment
  -> internal result / information need
  -> Parent-Touch queue (priority, duplicate filtering, expiry)
  -> one admitted, own-child-validated Parent-Touch turn
  -> verified single question in the one chat
  -> explicit question-bound parent answer
  -> Child-Safety follow-up on the new version
```

Provider submission and unknown outcomes need durable claims before I/O. A lost
HTTP response observes the existing result; it cannot reread sources, regenerate,
release a hold, send the question twice or reassign its answer. Coalesced questions
retain every specialist subscription while sharing one conversation slot. An
urgent safety notice must remain distinguishable from routine clarification;
it may not gain direct-sender or automatic control authority.

Publishing a question, saving its parent-visible message, consuming verified usage
and journaling its follow-up must share a SQL transaction. Likewise, admitting a
parent reply must bind that exact stored turn to the active question atomically.
Do not deploy a sequence of independent best-effort post-response callbacks.

## Current local increment (not the complete two-agent environment)

Worktree: `/mnt/ssd2/mana-family-agents-20261020`, branch
`feat/mana-family-agents-20261020`, clean source baseline `bf1d12a` on the actual
parent-chat release, not the unrelated dirty operational tree.

Implemented so far:

- Strict family-agent/question contracts and an immutable injected registry.
  Only Parent-Touch can be a speaker. Child-Safety owns the ten existing
  non-copilot protective capability identities. New specialist identities require
  deliberate registered definitions, not model-supplied authority.
- A private opt-in SQLite v2 queue, reusing the dedicated parent-chat adapter.
  Cross-process SQL uniqueness enforces one active/offered/held question per
  parent and one open information need per child/key. Multiple agent requests
  coalesce without overwriting the original question or observation dates.
- Exact request-body conflicts, preserved intent replay, priority/FIFO selection,
  explicit queue ceiling, paged history, expiry of **unsent** questions only,
  admitted-turn binding, parent isolation and explicit answer-turn binding.
- A v1 chat/quota can migrate additively without changing its history, replay
  digest, verified usage or unknown holds. Unmodified v1 code refuses the new
  tables/version; do not present it as a working v2 rollback reader or restore an
  old database over newer history.
- `ParentTouchService` reuses the existing chat admission, fresh own-child source,
  quota, recent history and receipt handling. Its prompt contains only the frozen
  selected question and the fresh matching child's permitted name, not raw child
  IDs, other families or the entire queue. A revoked child blocks inference.
- Parent-Touch uses a strict structured reply: ordinary body plus at most one
  question bound to the admitted UUID. Explicit extra questions, wrong/missing
  identities and invalid JSON are withheld while verified raw usage is retained.
  Exact input sizing uses the same schema as generation; dropping old history
  preserves the admitted question and current facts without recapture.
- Question selection and explicit parent-answer binding now share **chat admission's
  transaction**. Verified usage, accepted answer and the question's awaiting-reply
  state share **settlement's transaction**. A simulated failing commit publishes
  neither message nor question and retains the original submitted hold. Unknown
  calls hold the question indefinitely; safe pre-inference abandonment can recover
  without letting its old process submit a model call.
- Authenticated HTTP/runtime wiring, directory, queue admission/observation, frozen
  reply identities and proactive assistant-only delivery now use that same lifecycle.
  Inactive mode remains the unchanged legacy service/store. New family metadata lives
  outside legacy response JSON. Public docs and generated TypeScript include the
  implemented routes, but do not advertise a working Child-Safety worker.
- The family schema is now **v3**, additively accepting v1/v2 histories without
  recapturing old turns. New metadata is absent on historical turns; do not invent
  question identities for them. Older v1/v2 code refuses v3; this is still **not**
  a tested rollback reader or a production release.
- Both standalone OpenAPI exporters now resolve their own source checkout before
  importing `app`. An unrelated editable Python installation must not leak its
  operational working changes into this product's generated contracts.

There is still no event worker, automatic delivery dispatch, urgent-notice delivery
policy, Child-Safety model-budget ledger or agent deployment. A queue fixture pass
and punctuation validation are not semantic language/safety acceptance or proof
of real delivery. Revoked selected children fail closed before question inference;
automatic cancellation/filtering of obsolete queue items is not implemented.

Actual checks: **82 related cases** passed (including actual SDK over MockTransport,
not a real provider). Full clean-worktree **`make verify` passed**, original session
**71187**, exit **0**: **364 backend tests**, **1 skipped**, **2 opt-in live tests
excluded**; **26 UI tests /11 suites**, Ruff/format/ESLint, mypy **217 files**,
TypeScript, production UI build and zero npm vulnerabilities. Logs are in the main
workspace's ignored `output/family-agent-*-20261020.log`, especially
`family-agent-core-verify-20261020.log` and `family-agent-parent-touch-final-20261020.log`.
That is the historical core gate, not acceptance of the subsequent HTTP increment.
The HTTP increment's related suite has **97 passing tests** (overlapping the core
suite), plus a standalone checkout-resolution regression. Its terminal full gate
`OPENAI_API_KEY=unit-synthetic-key make verify` passed in original session **28013**,
actual exit **0**, log `family-agent-parent-touch-api-final-verify-20261020.log`:
**375 backend tests**, **1 skipped**, **2 opt-in live tests excluded**; **26 UI
tests /11 suites**; Ruff/format/ESLint, mypy **220 files**, TypeScript, production
UI build and zero npm vulnerabilities. `make audit-schema` passed after the
checkout-resolution fix; standalone product docs export reports **17 paths** and
zero provider/source calls. Secret scan passed for **381** tracked/unignored files.
The first full-gate attempt without a synthetic key failed at legacy test import;
its log remains `family-agent-parent-touch-api-verify-20261020.log`, not a pass.
None of these tests calls the live model, children, Firebase/GA4 or production.
This remains an intermediate checkpoint, not completion of the user-requested
two-agent API or goal.

## Remaining acceptance — preserve the full task

1. Add transactional outbox/version jobs around the now-wired, atomic chat lifecycle:
   only new parent messages/child facts trigger safety analysis, not assistant replies,
   GET/replay or unchanged context. Bound same-parent history and avoid recursive
   self-triggered inference. Preserve the implemented producer dedup/ownership policy.
2. Add automatic communication delivery and a separate typed urgent-notice policy;
   retain Parent-Touch as the only speaker, no fake parent turns and one active
   clarification. A routine question must not masquerade as an urgent safety alert.
3. Build actual capability-specific Child-Safety routes using the existing
   deterministic validation/evidence/action-proposal pipeline, dated own-child
   facts and bounded same-parent chat. No execution of proposed controls.
4. Add the separately configured Child-Safety budget ledger, strict raw receipts,
   worker single-flight, immutable input/chat revisions, coalescing and restart
   recovery. No analysis on unchanged context or automatic Firebase/GA4 scans.
5. Complete the public API/authentication/configuration/lifespan/docs and backward
   compatibility contracts. Default-disabled migration/runtime until explicit
   activation, no accidental replacement of the deployed private parent-chat key.
6. Verify two-worker races, cross-family/child denial, stale ownership, missing
   source facts, RU/UZ phrasing, question-answer ordering, coalesced subscribers,
   lost acknowledgements, SDK failures, quota rollover and actual compatibility.
7. Run full repository gates, hermetic HTTP end-to-end examples and actual candidate
   image/rollback checks. Any paid diagnostic must be a separate bounded synthetic
   party, never a random customer's conversation. Deployment requires its own scope.

The model/queue boundary follows [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
typed decisions are validated by the host; schema adherence alone does not prove
semantic safety, consent, ownership, one-question phrasing or successful delivery.
No new source, model, production, SSH, key or schedule change has occurred here.
