# Confirmed free-period end — local, 2026-10-26

New confirmed grants can support one service message after their free period has
ended. Parent-Touch publishes it in the existing chat; the parent's later tariff
question uses the existing manager/Upsell/catalog workflow. This does not yet
implement general proactive paid-offer targeting or prove app engagement.

`MANA_RETENTION_TRIAL_END_ENABLED=false` is the default. Enabling requires the
existing confirmed-period and complete Parent-Touch profile. Production is still
the last confirmed family `f8d095e`; no deployment, source refresh or actual tariff
grant is part of this increment.

## Admission, evidence and communication

Family schema **26** adds three private tables: `trial_end_policy`,
`trial_end_admissions` and `trial_end_notices`. Eligibility is frozen atomically
with a new owning grant claim. Old grants and disabled admissions never backfill
when enabled, migrated, replayed or restarted. The explicit capture ceiling closes
this consumer without cancelling an already admitted financial action.

Publication requires the exact known granted period plus a selected-current-tariff
observation showing `is_paid=false` and the same end. That observation must have
been collected **after the end**, no more than **180 seconds ago**. Crossing the
deadline with an earlier observation is insufficient, even if it is still fresh.
The notice window is bounded to seven days. Missing, paid, changed, stale or closed
source facts cannot publish; no on-demand read is created to fill the gap.

Existing independent Retention chat consent, language/timezone, quiet hours,
opt-out, conversation idle, safety/question priority, global outreach cap and
24-hour contact interval remain mandatory. A bounded round-robin SQL scan avoids
an ineligible prefix permanently starving later eligible admissions. It is not a
Firebase scan or an additional collection schedule.

The fixed RU/Uzbek Latin/Uzbek Cyrillic/EN text names the confirmed days and local
end date. It offers help looking at tariffs without inventing a price, discount,
payment, renewal, protection loss or unmanaged question. The assistant turn,
private proof, audit event and any separately permitted neutral push commit
together. A pending push rechecks current proof/source/flags; losing proof or
becoming paid suppresses the push and preserves the saved chat. Submitted/unknown
pushes retain the original nonretryable lifecycle.

The initial message adds **zero model calls and zero external reads**. A later
parent enquiry retains 2000 raw Parent-Touch tokens per parent/day, independently
of 2000 global Child-Safety tokens/day. Historical and unknown holds never reset.

## Test chat and actual checks

Run `make chat-lab-trial-end CHAT_LAB_PORT=8100` and open
<http://127.0.0.1:8100>. A clearly labelled, fictional one-day grant is seeded once.
The scenario button advances only this isolated fixture from October 26 to 28 and
supplies new fictional source/contact facts. It never changes the system clock.
Its durable marker prevents repeated seeding and restores the same clock after
restart. An incomplete marker refuses further work. No real grant, push, Firebase
or GA4 adapter is mounted. Other lab profiles keep this scenario disabled.

- Final `make verify` exited **0**: **1552 backend tests**, **26 admin tests /11
  suites**, **15 chat-lab tests**, mypy **436 files**, formatting/lint/typecheck,
  production UI build and zero npm vulnerabilities. One skip and two excluded live
  tests are not passes. Sequential OpenAPI/schema synchronization passed without
  a public mobile contract change. Focused counts overlap this full gate.
- Tests cover current/unknown/changed evidence, the exact end-time boundary,
  current language, consent, opt-out, priority, atomic rollback, pending-push veto,
  disabled admissions, old v23 no-backfill migration and current closed v26
  preservation. Old v23 refusal is not working execution rollback.
- Chromium exercised scenario -> same-chat end message -> 90-day enquiry -> fake
  exact catalog quote. Reload and actual server restart preserved every cell in
  **64 family and 15 source tables**, one end notice and one fictional grant.
  The fixture used **300 simulated parent tokens /zero safety tokens**. This is
  workflow evidence, not model quality or a real commercial conversion.
- A separate real GPT-5.4 Uzbek party selected the exact 30-day UZS enquiry and
  reconciled **1266 raw parent tokens**, zero safety/model holds, one fictional
  grant and one end notice. Its real catalog quote **did not pass**: the controlled
  unavailable response retained an unknown source receipt/two HTTP reserves.
  The diagnostic froze time before live responses, making actual collected dates
  future relative to its host clock; upstream status/body were not captured, so
  that is not a proven sole cause. Preserve the negative result, not a pass.
  No retry/replay follows. Generation estimate **$0.00449**, not a billing invoice,
  using the [official pricing](https://developers.openai.com/api/docs/pricing).

Local/private evidence: `output/trial-end-verify-20261026.log`,
`output/trial-end-schema-20261026.log`, `output/trial-end-browser-20261026/` and
`output/trial-end-model-catalog-20261026/`. Never commit diagnostic SQL or keys.

## Compatibility and remaining scope

The current v26 reader supports observation with the feature disabled and the
current closed v26 profile preserves history. Never downgrade populated history
or restore an older database over it. Previous v23 and lab-only v24/v25 readers
are not supported execution rollback targets; action-card labs remain separate.
Packaged candidate/release evidence is recorded separately, when available.

The complete objective remains open: broader source/model/capacity acceptance,
source-backed commercial eligibility, referral/reward contracts, further supported
actions and administrative owning-domain workflows. Technical remains last.
