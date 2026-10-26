# Confirmed free-access periods — local checkpoint, 2026-10-26

New known free-day grants can now support one pre-expiry reminder in the parent's
existing chat. Parent-Touch remains the only speaker. The reminder preserves the
confirmed duration and exact local deadline; a subsequent price enquiry uses the
existing manager/Upsell/catalog workflow. There is no new mobile endpoint, chat,
payment, renewal, discount, tariff grant or entitlement inferred by this feature.

This is local and default disabled: `MANA_CONVERSION_TRIAL_PERIODS_ENABLED=false`.
Enabling requires the complete existing Parent-Touch manager profile. Production
remains on the separately released family `f8d095e`; this checkpoint does not
deploy code, start collection, alter budgets or authorize customer contact.

## Evidence and durable capture

The existing grant gateway already validates `created_at`, `is_paid=false` and
`agent_trial_used=true` when that complete metadata group is returned. It now
passes those facts as private typed metadata to the owning grant service. The
service revalidates nested values even from constructed model instances, verifies
the requested duration/end and preserves the original one-shot unknown outcome
handling. Public request/response schemas and legacy receipt JSON are unchanged;
the private metadata is neither an API field nor an OpenAPI component.

Family schema **22** adds four private tables: `trial_period_admissions`,
`trial_period_facts`, `trial_period_notices` and `trial_period_state`. A grant claim
freezes consumer eligibility before external submission, atomically with its
original action. Pending/unknown enabled admissions retain their capacity. Only a
new captured, known grant with complete verified metadata records an immutable
period in the same receipt transaction. It binds action, parent, purchase, days,
provider start/end, host receipt time and digest. It is not a source/contact grant.

Historical grants, disabled claims and absent metadata never acquire a period on
restart, re-enable or replay. Do not backfill a start from expiry minus days, use
profile `created_at` as a universal free-start date, or repeat parent 4's consumed
real grant to populate this table. Out-of-window receipt metadata closes this
consumer without rewriting the known grant. Corrupt/mismatched period proof also
closes this consumer; the existing paid-expiry consumer remains independent.

## Publication and costs

The existing current selected-tariff cache must independently show non-paid access
with that exact recorded end. Unknown, stale, conflicting or changed terms cannot
publish. All existing Retention consent, language/timezone, quiet hours, opt-out,
conversation-idle interval, safety/question priority, outreach caps and deduplication
still apply. A tariff and a grant receipt do not imply consent. The fixed RU,
Uzbek Latin, Uzbek Cyrillic and English templates ask no unmanaged question and
make no loss-of-protection, paid-conversion or automatic-renewal claim.

The assistant message and private proof commit before a neutral permitted push.
Missing/changed proof or a disabled consumer suppresses an unsubmitted free-period
push without deleting its chat message. Unknown push outcomes remain nonretryable.

Period capture and templated reminders add **zero model calls and zero Firebase
queries**. Existing profile/collection acquisition supplies the tariff fact; a
new manual read is not silently created to make an expired cache usable. Subsequent
dialogue retains **2000 raw Parent-Touch tokens/parent/day**, separate from **2000
global Child-Safety/day**, including all original unknown holds.

## Practical acceptance

`make chat-lab-trial-periods` starts an isolated loopback simulation. Its banner
explicitly declares a fictional one-day grant. A fake provider, fixed fictional
recipient and earlier synthetic acceptance are seeded once through the actual
grant lifecycle. No real grant endpoint is attached. The acceptance is eleven
fictional minutes earlier to exercise the actual idle rule, not a changed server
clock or production policy. An incomplete seed is never automatically replayed.

- Final `make verify` exited **0**: **1478 backend tests**, **26 admin tests / 11
  suites**, **10 chat-lab tests**, mypy **415 files**, formatting/lint/typecheck,
  production UI build and npm audit (**zero vulnerabilities**). Test counts overlap
  with focused suites and must not be added. One backend skip and two excluded
  opt-in live cases are not passes. Log:
  `output/trial-period-verify-configured-20261026.log`.
- The dedicated factory and restart regression is included in the **20** focused
  cases. Earlier diagnostic clocks incorrectly skipped the required fictional
  morning step; the actual factory had the same defect. It now advances through
  both allowed windows, and its regression starts/restarts the real factory.
- Actual old v21 image creates a known legacy grant without metadata. The new
  image upgrades that fixture and a separate populated unknown fixture to v22,
  preserving every original cell. Neither recaptures a historical period; the
  **1850-token unknown hold** survives. Current closed v22 preserves all rows and
  new reminder history. These are networkless synthetic fixtures, not fleet proof.
- Local image `mana-ai-family:trial-period-v22-private-20261025-local`, ID
  `sha256:1c19b0ba62126a87b04c3df6dccd91602177d186af4ab25bb116f0b55e0d1e6f`,
  matches all **12** changed/new application files and contains no `.env`. The
  subsequent factory/test-only postfix is outside that image's application copy.
  Actual previous v21 refuses all three v22 files with every row unchanged. This
  is **not working old-image rollback**; use the current closed v22 profile and
  never downgrade or restore a stale database over new history.
- The already protected actual production-v6 copy was also upgraded directly to
  v22 through this exact image's production HTTP/runtime factory, locally with
  networking disabled and synthetic keys. All original cells in **16 tables**,
  two historical messages and exact legacy replay were preserved. Liveness,
  history, directory and replay returned **200**; missing auth returned **401**.
  Current closed v22 returned the identical history and retained all fingerprints.
  New period/action/source tables stayed empty, with **zero external requests**.
  No new production copy or server access was needed. Its private SQL artifact is
  outside Git/images in a 0700 directory with 0600 file permissions. This is a
  small real-history migration check, not live rollout, fleet/load acceptance or
  evidence that all native workflows have working old-image rollback. Receipt:
  `output/trial-period-production-copy-http-20261026.log`.
- Named Chromium session exercised the real loopback UI/API/SQL: one free reminder,
  a 90-day enquiry, a simulated exact catalog quote and **eight messages**. Reload
  and server restart preserved every family/source table fingerprint, with no
  regrant, duplicate notice or generation. The 390px viewport has no horizontal
  overflow; the scrolled final quote was visually inspected, with no console
  errors. The worker also reviewed the seeded historical acceptance once (**150
  simulated safety tokens**); the enquiry used **300 simulated parent tokens**.
  These are fake model counters, not paid quality or real source acceptance.

Retain negative diagnostics: the initial schema exclusion leaked an unused
OpenAPI definition (fixed by a private attribute); two lab restart cases initially
required absent period metadata (fixed without backfill); one full gate failed
collection because its command omitted the required dummy inference key. The
subsequent explicitly configured full gate passed. No actual key was introduced
into pytest, and no failed paid receipt was overwritten.

## Bounded model/catalog parties

The first fictional one-day-period diagnostic used real Parent-Touch models but
accidentally injected the catalog into an unused attribute. It used the fake
catalog. Its original receipts and append-only `qualification.json` remain in
`output/trial-period-model-20261025`; it is not real-catalog acceptance.

A distinct **30-day** enquiry then bound the actual catalog source and verified
that binding before I/O. One login plus one `GET /api/v1/tariffs/` produced the
known **60000 UZS / 30 days** catalog option. Four OpenAI HTTP attempts (two token
counts and two generations), **1209 raw parent tokens**, **zero safety tokens**,
zero unknown holds, one reminder and eight messages were recorded. Exact replay
observed the original result. Generation-only uncached price estimate is
**$0.004235** for each party (**$0.00847 combined**), not a provider invoice or
cost for real customer grants. No real parent profile, child data, Firebase,
grant, contact, payment or production mutation occurred in either model party.
The fictional recipient used verified EN/New York lab settings during daytime;
all grant/consent/history fixtures were explicitly synthetic. Read:
`output/trial-period-model-live-catalog-20261025`.

## Full objective remains open

This adds a supported conversion/retention step, not the complete agent team.
Ordinary chat acceptance still does not itself activate a trial; the existing
trusted-backend acceptance contract owns the grant. Automatic eligibility,
proactive paid upsell, real referral/reward contracts, populated monitoring
semantics, GPS runtime integration, broader source/model/fleet capacity, complete
OPERATION actions and a separately approved production rollout remain unfinished.
