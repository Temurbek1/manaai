# Saved observations and tariff follow-ups — local checkpoint, 2026-10-28

This increment connects new typed tools to the existing parent chat. It is
default disabled and **not production-ready**: the two new real-model end-to-end
cases stopped at their unchanged token limits. The original goal remains active;
passing fake workflows does not replace those negative results.

## Child-Safety: separate saved-only tool

`MANA_FAMILY_SAVED_OBSERVATIONS_ENABLED=false` captures native protocol **4**
only on new eligible turns, with private family schema **38**. The model may
choose `inspect_saved_child_observation` or the existing live-read tool; there is
one total tool choice per review, no automatic fallback. Old protocols 1–3 and
their original inputs, receipts and costs never upgrade.

The inspector opens an existing, explicitly bound source7/8/9/10 file through a
read-only SQLite URI. It cannot initialize/migrate that file, claim a source
read, refresh a provider, use credentials or change its counters. It supports
saved battery, app counters, last GPS points and a family/day page minimized to
the exact owned child. Fresh ownership still uses the existing MANA profile port.
This avoids a Firebase read, not every profile HTTP request.

The six-hour provider-check freshness, source circuits, unresolved reads, exact
source binding and fingerprints remain enforced. Missing/stale/foreign/stopped
data produces a typed unavailable result, never an older fallback or new query.
Measurement, provider check, snapshot collection and SQL inspection dates differ.
An inspection date does not make a measurement current. Model projections exclude
family identifiers, point hashes and coordinates.

The separate immutable local-SQL policy permits at most **1000 inspections
globally /20 per parent per rolling day**, one per native review. These are SQL
admission ceilings, not new Firebase or model allowances. Family SQL freezes the
call/target/policy before reading and binds the exact terminal result. Lost local
results or model receipts are not redispatched by a nonce, restart or midnight.

## Parent-Touch: contextual tariff refinement

`MANA_UPSELL_FOLLOWUPS_ENABLED=false` adds family schema **39** and initial-manager
publication protocol **6** on newly eligible turns only. It freezes the latest
same-parent completed quote, exact originating request words, explicit currency
answer if any, typed terms and provenance. A bounded clarification keeps its full
request chain; overflow refuses instead of trimming. Older turns retain their
original protocols and messages.

An explicit refinement may retain unchanged prior currency/budget/duration and
apply the newly requested change. An unrelated request does not inherit defaults.
The original quote is historical context, never current pricing, entitlement,
consent, a source grant or payment authority. The existing owner still validates
fresh membership, current catalog, filters, priority, cancellation and expiry.
Strictly-cheaper single-option ceilings are computed in code; zero never becomes
a positive price. No payment, discount, renewal or transaction is created.

## GPS time presentation

`MANA_FAMILY_LOCATION_TIME_LABELS_ENABLED=false` adds source schema **10** with
admission/head companions. Only a new physical GPS admission captures presentation
marker **2**; old source9 in-flight reads and saved events never acquire it.
Both host-generated measurement labels include seconds and explicit **UTC**.
The final publication must contain every known label when communicating the
notice. Unknown time remains unknown. Source/family stop fences retain the marker
and costs instead of silently degrading to the old presentation.

The new RU actual-model first-contact test used exact UTC labels successfully,
but exposed an internal `dated` enum and a confusing single-point opening. Its
**1718 parent /1388 Safety tokens**, receipt and negative review remain unchanged.
Subsequent marker2-only guidance removes the conflicting single-point instruction
and explicitly translates metadata; this later wording has fake verification,
not another claimed real-model quality pass.

## Practical lab and combined ordering

Run `make chat-lab-agents CHAT_LAB_PORT=8116` for the separate fictional directory
`data/chat-lab/agent-workspace-v39-simulation`. Earlier lab directories/captures
remain untouched. The new workspace combines GPS reports, saved-only questions,
tariff follow-ups and the existing controls in the same chat. Its fake interpreter
demonstrates selected exact refinements; production interpretation uses the model.

Three new combined ordering regressions complete Retention question -> urgent
Safety interruption -> exact answer -> next child question, plus price cancellation,
controls, replay and restart. A caught fake-model bug had incorrectly generated a
tariff enquiry for an ordinary support answer; only the fake branch was corrected.
It is not evidence of a production policy failure or real-model quality.

## Preserved real-model negative evidence

- **Actual sources and models, designated parent4:** reused complete copies of
  the original family34/source4 ledgers after their original 24-hour window
  naturally opened. One bounded battery query succeeded (limit2, conservative
  reserve2), then one native saved inspection left the source ledger unchanged.
  All originals remain byte/cell-identical. Parent used **819** raw tokens;
  Safety used **1319**. Its next input count **1143** exceeded remaining **681**;
  no second Safety generation or parent answer occurred. No holds or retry.
  Known uncached generation estimate **$0.003373**, not an invoice.
  Evidence: `output/saved-family-live-20261028/`.
- **Two fictional price enquiries, real model/clock:** the first quote completed
  using **843** parent tokens and one fake catalog read. The follow-up's final
  input count **1118 +128 minimum output** exceeded remaining **1157**. It made
  no second generation or catalog read. Known uncached generation estimate
  **$0.00292**; three count calls/one generation. The earlier option-validation
  harness failure made zero calls and is kept separately.
  Evidence: `output/tariff-refinement-model-setup-fixed-20261028/`.

Next work is a new captured compact source protocol and zero-inference strict
literal tariff refinements. Never replay either failed party, reset its ledger,
lower output floors or raise the **2000 parent /2000 global Safety daily limits**
to manufacture a pass. Source renewal, real contacts, grants, bulk collection,
production/SSH/keys/schedules remain outside these local changes.

The mobile-source audit also confirms no existing verified per-parent locale,
timezone or purpose-specific consent source. Device registration and aggregate
GA4 language do not establish those settings. Existing contact-context ingestion
still requires independently verified facts; the system does not invent them.

## Local gates and remaining release boundary

Final `make verify` exited0 in
`output/saved-agent-typed-test-fixed-verify-20261028.log`: **1845 backend cases**,
one skip/two live exclusions, **26 admin /23 lab-controller cases**, mypy
**490 files**, formatting/lint/typecheck/build. OpenAPI synchronization passed.
The required high-severity npm audit gate passed with **five low-severity
findings**, not zero findings. A preceding test-only dynamic-kwargs typing
failure is retained and corrected; production code was not weakened.

The 390px actual browser covered GPS labels ->90-day quote ->180-day refinement
->saved GPS inspection in one history. Seven messages, **750/450 simulated
parent/Safety tokens**, two original source admissions/four conservative units
and one saved SQL inspection remained unchanged through reload. All **83 family /
31 source tables** and full REST state matched, with no JavaScript error or
horizontal document overflow. The owned browser/server8116 are closed.

Fake regression suites include current closed38/39 readers, unknown holds across
restart/midnight and old-capture compatibility. A new candidate image/active
rollback/production release is **not** established by this checkpoint and is
reserved for the combined next increment. Never downgrade these schemas or
restore an older DB over their history. Earlier candidate images cannot execute
new38/39 state. Production services and source schedules remain unchanged.
