# Commercial conversation and trial-expiry checkpoint

Local increment on `feat/mana-conversion-agent-20261021`, after `863bc06`.
This is not a production release, paid conversion measurement, or proof of full
population tracking. Existing production `f8d095e`, its keys, private volume,
main/audio, OPERATION services, source refresh and schedules remain unchanged.

## Implemented behavior

- New `MANA_CONVERSION_CONVERSATION_ENABLED=false` captures commercial context
  only on newly admitted parent messages. It requires the owning conversion/
  review-first runtime. No old turn, digest, offer or receipt is upgraded.
- A private SQL context freezes the last actually published same-parent offer,
  exact approved terms, availability at capture, grant status, recipient language,
  and known terminal-receipt time. Later snapshots/catalog changes cannot rewrite
  that historical prompt. Empty commercial context is omitted to avoid irrelevant
  model input. IDs, approval references and purchase IDs are excluded from the
  model-facing projection.
- Parent-Touch may explain those terms in ordinary conversation. It receives no
  grant/payment tool. Parent text, model output, acceptance, free entitlement and
  actual paid purchase are distinct. An activation phrase alone proves no result.
  New typed observations and prompt instructions remain code-managed and separate,
  following [official prompt guidance](https://developers.openai.com/api/docs/guides/prompt-engineering#message-formatting-with-markdown-and-xml).
- The existing backend `POST /conversion-agent/trial-acceptances` remains the
  explicit write entry. Its `reply_turn_id` must point to a real parent message
  after the latest offer and, in v9, to that exact frozen, available offer. A
  generic acceptance cannot select an older three-day offer after a newer offer.
  Current catalog/account/consent/trial policy is checked again before the claim.
- A valid free-day receipt must match the parent, approved days/expiry and exact
  documented tariff `Maxsus`. Wrong/malformed receipts become durable `unknown`;
  replay/restart cannot repeat the provider write. This also fixes the earlier
  v7/v8 acceptance of a different tariff name. Definitive rejections remain closed;
  no hidden automatic rearm is introduced.
- A terminal free-day receipt queues its own service-result message in the same
  SQL transaction as settlement. Its separately recorded timestamp is not the
  earlier claim time. Parent-Touch's worker publishes that assistant-only message
  once, with success, refusal or uncertainty and explicit dates. It neither calls
  a model nor emits a fabricated child assessment or second speaker.
- Result messages wait behind unresolved chat/child-analysis and current urgent
  safety notices. They are service receipts, not new promotions, so they do not
  apply marketing quiet hours or promise another offer. They are currently
  **chat-only**: no new service-push permission is inferred from safety/marketing
  consent. Existing approved offer/safety push flows remain separate.

## Confirmed trial expiration → paid invitation

Only the new captured v9 lane opts into `free_access_expired`. Existing v7/v8
callers retain the earlier reason behavior. The new decision requires:

1. A fresh backend observation with explicit `free` or `expired` status.
2. Actual ordered free start/end dates, with the end already confirmed by that
   observation and not merely crossed by a local timer.
3. Separate marketing consent and recent measured adult-parent activity.
4. The configured outreach window after expiry, default seven days (1–30).
5. A valid billing-approved **paid** offer; never another free grant for this reason.

Templates state the ended period and its actual UTC date, preserve every approved
price/discount/renewal term, and stop counting elapsed free days at the end. A
snapshot without end dates retains the existing hot/seven-day free-use behavior.
Publication and marketing-push checks use the same owning eligibility helper.
Clock-only expiration cancels a now-unverified queued offer rather than rewording
it into a new promise. A new verified snapshot can admit a new proposal.

This is deterministic admission, not a learned purchase prediction or causal
business result. Child GPS, conversations, safety findings and fears are not
commercial targeting inputs.

## Persistence and deactivation

Private SQLite v9 adds `conversion_chat_contexts` and
`conversion_trial_result_messages`; v6/v7/v8 histories and unknown holds survive.
New capture binds only new turns. Replaying an old failed/in-progress request
returns its established refusal/status, never a new commercial context.

The current runtime selects v9 and its same-code closed/history reader by the
actual storage version. Disabling the new flag stops new capture/receipt
publication; prior contexts remain readable internally and chat history survives.
The previous `863bc06` v8 image and production `f8d095e` are **not v9 rollback
readers**. Never downgrade or restore an old DB over new history. Candidate-image
deactivation has since passed on the actual `88193f53d363…` image; see
[the candidate evidence](mana-conversion-candidate-checkpoint.md). Real-device
notification acceptance and any production contact release remain separate.

The older HTTP limitation is explicit: conversion/grant GETs still require their
configured service, so closing those flags returns a controlled 503 rather than
dispatching a read/retry. SQL receipts and the saved chat are retained. A separate
closed-mode receipt HTTP observer is not claimed by this increment.

## Checks and outstanding obligations

All provider checks use synthetic accounts, fakes and MockTransport. No real model,
grant, push, Firebase/GA4 read, production login or source scan was performed.
Focused coverage includes expiration selection, cap/terms honesty, frozen context,
review-first integration, current-state fencing after payment, latest-offer binding,
RU/Uzbek Latin/Uzbek Cyrillic/English result receipts, atomic concurrent publication,
HTTP auth/replay/history and runtime/current closed-v9 selection.

The initial new test run incorrectly expected in-progress/failed synchronous
admission to replay as a returned turn. The established contract correctly raises
the original controlled status; the tests were corrected without changing that
contract. A subsequent runtime fixture needed output tokens inside its explicit
job budget. Earlier failures are not renamed successful runs.

Full `make verify` session **33729** reached terminal exit **0**: **780 backend
tests** (one skipped/two excluded), **26 UI tests**, mypy **272 files**, lint/types,
Next production build and dependency audit zero vulnerabilities. These are local
fake-provider acceptance checks, not production or broad model-quality acceptance.

The original goal remains open: install an authoritative all-parent subscription/
activity event producer with coverage accounting, supply real approved offer terms,
finish candidate/channel release acceptance, and validate paid outcomes. Current
Parent List does not distinguish paid/free or supply trial history/consent/activity.
See [the owning-backend field contract](mana-conversion-backend-events.ru.md).
