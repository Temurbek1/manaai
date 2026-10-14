# Private Retention contact foundation

Local application/domain/persistence checkpoint, **not an enabled capability or release**.
It advances the Retention-first action lifecycle without adding a fifth agent, sharing
credentials with the Orchestrator or changing existing advertising/Growth action enums.

## What exists

An isolated typed `send_retention_message` intent supports only fictional MANA adult
accounts and a fake push receiver. Two immutable templates (`onboarding_help`,
`renewal_reminder`) have explicit Russian/Uzbek Latin versions and exact text hashes.
The human proposal fingerprint binds owner, topic, request, complete message, source
snapshot, policy and expiry. Approval persists before dispatch. Replays and unknown
outcomes only observe SQL or an exact receipt; they never send again.

Eligibility requires confirmed active paid access, adequate individual activity/risk
facts, no open complaints, explicit recipient timezone and 09:00–21:00 local hours,
purpose/channel/evidence-bound current contact consent, explicit matching language,
no suppression and complete bounded contact history. An expiring confirmed subscription
is additionally necessary for the renewal template. A tariff, parental aggregate or OS
push permission alone does not qualify. All three independent kill scopes are rechecked.

SQL migration `b47ea6c9130d` adds three private tables for intents, recipient reservations
and atomic revision audit. Existing generic recommendation/proposal JSON is unchanged.
The recipient slot is shared across runtimes: verified acceptance reserves seven days;
in-flight/unknown outcomes retain an unbounded hold until exact reconciliation. A known
pre-dispatch refusal releases only its unused slot. Downgrade refuses populated private
history, never deletes it. The migration has **not** been applied to production.

Fake verification means `sandbox_accepted`, not delivery, opening, retention improvement
or conversion. Every action retains business outcome `not_measured`.

## Remaining work

There is no public route, enabled agent capability, chat/native action bridge, schedule,
source adapter, customer-facing push/email/billing executor or budget authority for this
family. The service is not instantiated by `app.main`. Models correctly continue to say
Retention contact execution is unavailable. Before exposing it, integrate exact typed
human review/receipt memory with a separately verified private checkpoint and rollback,
API/UI authorization, owning-agent executor registry and end-to-end acceptance. Live
contact requires approved individual billing/consent sources and a separately authorized
channel executor; current aggregate sources cannot stand in for them.

Fake/SQL tests cover exact body/language binding, current-state refusal, role/owner and
self-approval gates, kill switches, expiry, lost acknowledgement, permanent unknown holds,
cross-runtime idempotency and cooldown after a receiver restart. Isolated local PostgreSQL
checks exercise cross-connection approval and durable known-recipient cooldown. No live
customer contact, paid model call or production/source mutation occurred.
