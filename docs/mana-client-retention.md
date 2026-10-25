# Client Retention / Win-back — local checkpoint, 2026-10-25

Retention now has an executable client-chat workflow, not another chat or speaker.
The server detects a dated gap in the parent's own chat, admits one immutable
intent, and asks Parent-Touch to generate one useful check-in in the verified
recipient language. The actual recent same-parent history is available as
historical context. A new parent reply follows the existing Child-Safety review
and Parent-Touch path. SQL records the returned-to-chat event once.

This is the first supported retention scenario. **Chat inactivity is not app
churn**: the system does not infer uninstall, payment state, child danger or app
inactivity from that gap. Subscription renewal, cancellation/pause, discounts,
paid win-back and their business outcomes are still incomplete. The earlier
aggregate GA4 work cannot identify a particular parent or child. No payment,
transaction, free tariff, discount or new backend webhook is introduced here.

## Runtime and policy

`MANA_CLIENT_RETENTION_ENABLED=false` remains the default. The current profile
requires the existing native/source-review/reminder family runtime. Independent
activation on older family profiles is not implemented. The isolated production
family API is unchanged; this local code is not deployed or enabled there.

Defaults are a 14-day gap since the last completed parent message, at most 20
outreach admissions globally per rolling day, and a 180-second preparation window.
One intent per parent/last-message anchor is immutable. Another worker, a restart,
a missing acknowledgement, passing time or a different nonce never repeats it.
Changing the policy cannot reset that history or silently raise limits.

New backend-verified contact fields are optional and default false:
`retention_chat_consent` and `retention_push_consent`. Existing safety, marketing
or assistant permissions do not substitute; neither a tariff nor model prose
grants permission. Contact validity/revision/language rules remain unchanged.
The proactive switch, verified recipient timezone and existing quiet hours apply
before admission. No current permission means no outgoing model call.

Active/queued specialist questions and notices, pending parent messages, unknown
turns, unconfirmed reminders and due reminders take priority. Eligibility is
checked again in the same transaction that would publish the priced answer.
New parent text, revoked/changed contact metadata, an urgent specialist need or
an opt-out arriving during inference discards the late text while retaining its
verified usage. The model cannot invent a managed question or a new action.

Parent-Touch uses its existing **2000 raw tokens per parent/day**. Retention has
no additional model budget. It does not invoke Child-Safety for its own proactive
text; the parent's later reply still uses the normal separate **2000-token global
Child-Safety allowance**. It reads local SQL and one fresh ownership-filtered
parent profile before generation, not Firebase collections. Lost source/generation
outcomes are not retried. Unknown model holds block new inference across midnight.

Only Parent-Touch publishes an assistant-only chat turn. Message persistence and
an allowed neutral push outbox entry share one transaction. Push is separately
consented and one-shot; provider queueing is not delivery or reading. No lab has
an external push gateway. A parent return means an actual admitted parent message
following a published check-in, not a causal improvement in measured retention.

## Parent API and stopping contact

The phone still uses only message POST, message-status GET and single-history GET.
No extra parent chat, reminder-like confirmation ID, child question ID or public
Retention endpoint is needed. The internal intent and its authority are host-owned.

A parent may write `не пиши первым`, `не напоминай о чате`,
`пиши только если я напишу`, `birinchi bo‘lib yozmang`, or `stop check-ins`.
These exact supported controls persist a refusal and reply without another model
call, including after the chat allowance is exhausted. Replaying their original
request observes its original answer. A later consent update does not silently
remove a chat opt-out. Queued retention pushes are suppressed; an already
submitted external push cannot be recalled. Safety communication permissions
remain independently governed.

The runtime directory lists the non-speaking `retention-agent`. Administrative
Retention remains one of the canonical four OPERATION owners; this does not create
a fifth top-level operational agent or claim full administrative action coverage.

## Practical lab

Run `make chat-lab-retention`. In an empty fictional history, click
“Возврат после паузы (вымышленная история)”. This one-shot local fixture creates a
clearly declared 15-day-old parenting conversation and a fictional fresh opt-in.
The real-clock worker then admits Retention and Parent-Touch publishes the check-in.
Reply normally, then try the stop phrases. Clicking the fixture again only observes
its existing receipt. It refuses a different populated history. No real parent's
state or clock is changed, and no paid model can invoke that fixture endpoint.

`chat-lab-retention-live` is a separate explicit paid-model directory with fictional
profiles and the real clock. Do not reset its quotas, seed a new party to replay
an old failure, or use a paid model with an artificial time source.

## Actual evidence and limits

Thirteen lifecycle cases pass: full return flow, exact replay, separate consent,
unknown generation/restart/midnight, two concurrent workers, opt-out during
inference, specialist priority before/during inference, claim expiry, fixture
one-shot behavior, quiet hours and quota exhaustion. SDK MockTransport checks
retain raw usage for a refused unmanaged question. Production factory tests
assemble v15 lazily with fake providers and no network. No automated test calls
a real provider, user, push or grant API.

One independent actual-model party in `output/client-retention-model-20261025`
completed the entire sequence: declared fictional old history -> generated RU
check-in -> parent reply -> real Child-Safety review -> Parent-Touch continuation.
It made six OpenAI HTTP attempts, three generations, and used **1734 speaker** /
**1024 safety** tokens with **zero unknown holds**. No duplicate check-in appeared;
one return event was saved. The content addressed the adult, used the earlier
homework topic conditionally, and offered practical steps without inventing current
measurements, tariff offers or actions. Estimated standard uncached generation
cost is **$0.0076030**, not an invoice or proof of token-count endpoint billing.
The actual role models were GPT-5.4 / GPT-5.4-mini. This single RU fictional party
does not establish broad model/UZ quality, real customer consent or business lift.

Owned 390px browser evidence covers one assistant-first check-in, Uzbek parent
reply, zero-inference Uzbek opt-out and fresh navigation/restart. Exact four SQL
turns/seven displayed messages, 300 simulated speaker tokens, 150 safety tokens,
returned status, one opt-out and five audit records survived. No horizontal
overflow appeared. The first browser exposed an unhandled `lab_state_busy` error;
the route now returns controlled 409, covered by a regression. The first fixture
button also used generic source-read error wording; its dedicated result handling
and regression now distinguish fixture admission. Neither correction replays work.

Private family schema **15** adds intent/policy/turn/opt-out/audit tables; source
schema stays **4**. Current packaged closed readers retain history with execution
disabled. Networkless v13 -> v15 upgrade preserves every old table fingerprint,
150 known /1850 unknown safety tokens and captures no historical outreach; the
closed reader retains all five messages of the actual-model party unchanged.
Earlier images do not implement this feature. Do not downgrade populated private
history, restore an old database over new chat records or claim old-image refusal
as a working rollback. Candidate details/final gates are recorded below.

The full goal remains active. Next is Upsell using actual tariff facts and supported
eligibility, then the remaining retention/action/referral and administrative flows.
No production setting, source schedule, Firebase/GA4 data, main/audio container,
key, SSH policy, customer tariff or existing paid diagnostic was changed here.

Final gates: `make verify`, session **49659**, exited **0** — **1252 backend
cases**, one skip, two live opt-ins excluded; **26 admin tests /11 suites**,
**10 lab-controller cases**, mypy **373 files**, format/lint/typecheck/build and
zero npm vulnerabilities. API synchronization, Ruff, independent mypy, marker
scan and secret scan (**1027 files**) passed. The 13 Retention lifecycle cases
are included in that backend total, not an additional population/model study.

Candidate `mana-ai-family:retention-v15-20261025-local` / `5bd40d810980` passed the
networkless upgrade/closure probe. Its critical runtime/store/model source hashes
match the final host sources. Actual previous v14 `b14af3564999` refuses v15 with
unchanged bytes. Current closure and old refusal do not prove production rollback.
The owned browser and loopback servers are stopped. The qualified real-model
party was not rerun after UI fixes; those fixes change no model instructions.
