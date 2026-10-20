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

## Intended API shape — not yet all implemented

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

## Current local increment (not a working full API yet)

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

These services/transitions are **not yet wired into a public API or runtime
activation**. There is no event worker, automatic delivery admission, Child-Safety
model-budget ledger or agent deployment yet. A queue fixture pass and punctuation
validation are not semantic language/safety acceptance or proof of real delivery.

Actual checks: **82 related cases** passed (including actual SDK over MockTransport,
not a real provider). Full clean-worktree **`make verify` passed**, original session
**71187**, exit **0**: **364 backend tests**, **1 skipped**, **2 opt-in live tests
excluded**; **26 UI tests /11 suites**, Ruff/format/ESLint, mypy **217 files**,
TypeScript, production UI build and zero npm vulnerabilities. Logs are in the main
workspace's ignored `output/family-agent-*-20261020.log`, especially
`family-agent-core-verify-20261020.log` and `family-agent-parent-touch-final-20261020.log`.
Generated OpenAPI/TypeScript contracts remain unchanged: no unsupported endpoint is
being advertised yet. This is an intermediate local code checkpoint, not completion
of the user-requested two-agent API or the goal.

## Remaining acceptance — preserve the full task

1. Wire the now-tested Parent-Touch persona/one-question service into the runtime
   and HTTP contract; preserve existing model, old request digests and chat path.
   Add explicit parent-visible metadata and proactive delivery without a fabricated
   user message. Freeze the reply language for delivery without a new parent text.
2. Add durable specialist-intent admission/ownership checks and outbox/version jobs
   around the now-atomic chat lifecycle. Repeated nonce-independent identical intents
   and already-answered information need stronger terminal-state filtering; current
   request replay and open-question coalescing are not that complete policy.
   Replay and GETs observe only; unknown calls never redispatch.
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
