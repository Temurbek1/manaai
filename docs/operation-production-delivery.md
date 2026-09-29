# Operation Agents: production delivery

## Objective and authority

Implement the administrator website and action-capable operational agents described in
`/mnt/ssd2/Downloads/MANA OPERATION AI (2).pdf`, with production access for ongoing user testing.
The eight-page document has the same extracted text as the repository's `(1).pdf`.
The canonical four-agent interpretation remains `operation-agent-model.md`.

Production admin: https://ai-frontend.360rec.uz. API: https://ai.360rec.uz.
This objective is not complete when only the engagement dashboard or sandbox actions work.

## Delivery order and acceptance ledger

| Workstream | Required outcome | Current evidence / remaining work |
| --- | --- | --- |
| Russian, understandable interface | Russian primary UI, human-readable agent/status/action labels, clear evidence/proposal/approval separation, explicit empty/error/loading states, technical IDs and JSON in secondary details. | Requested during implementation; all administrator workflows are in scope. |
| Safe website reads | Page refresh reads persisted views only; no provider health probes or collection. Source age, completeness and live/sandbox state are explicit. | Implemented and regression-tested locally; production verification pending. |
| Retention workspace | Real saved engagement evidence, source coverage, findings, history and actionable explanations visible in the admin UI. | Dedicated saved-evidence workspace implemented and browser-tested; production verification pending. |
| Growth and conversion | Real funnel/billing/attribution facts; twice-daily eligible free-user analysis, approved offers and experiments, measured conversion outcomes. Advertising audience/time/region/creative analysis, governed budget/status changes and nightly reports; channel expansion to Google/TikTok. | Meta analysis is read-only; funnel and executable advertising/experiment paths are fake/sandbox. Live source/write contracts must be verified, not invented. |
| Retention risk | Per-account red/yellow/green risk with evidence of inactivity, cancellation intent, subscription expiry, uninstall, ratings, support and contact history. Unknown evidence is not a low-risk label. | Not implemented; aggregate activity alone is insufficient for individual churn decisions. |
| Retention actions | Approved push offer, follow-up email, subscription pause, bounded annual discount and win-back; consent, suppression, contact/value limits and abuse prevention. | Not implemented. Requires authorized delivery/billing endpoints and fresh target-state verification. |
| Loyalty/referral | Evidence-backed happy-user eligibility, approved referral offers and idempotent rewards after verified paid referral. | Not implemented. |
| Orchestrator | Admin chat/commands, persisted metric/baseline/target/deadline/constraints, typed plans/tasks/dependencies, delegation and repeated outcome evaluation until success or explicit escalation. | Not implemented; implement after Retention risk/action capabilities. |
| Executive analytics | Daily finance/users/churn/conversion/retention report, period comparisons, risk-user query, source-grounded root-cause hypotheses and ARR forecasts with uncertainty. | Not implemented; do not label missing revenue or churn as zero. |
| Cross-agent coordination | Correlate reliability/product/growth signals, delegate approved interventions, track effects and alert administrators. | Not implemented; orchestrator has no unrestricted provider credentials. |
| Technical Reliability (last) | Crash/latency/error/release/device analysis; app-store reviews/support clustering; affected-user impact, priority, approved issues/incidents and administrator alerts. | Not implemented; real observability/review/support/issue integrations must be established. |

The PDF's hourly Retention analysis must not mean hourly full Firestore scans. Analyze persisted
facts or incremental authorized events; keep approved source-read budgets and cadence unchanged
unless separately agreed. Safety events must be genuine and minimized, never fabricated to induce
a purchase. Raw child audio, transcripts and precise locations stay outside the operational plane.

## Release invariants

- Preserve SSH access, existing credentials, Firebase rules/IAM, stored user data and audio service.
- No unapproved broad data scans, increased Firestore limits, real ad writes, customer messages or
  financial benefits. A deploy authorizes software delivery, not arbitrary customer campaigns.
- Typed contracts, policies, approval, idempotency, fresh-state checks, verification, uncertainty
  recovery, outcome measurement, audit and sandbox executor are mandatory for each action family.
- Never present configured adapters, fabricated data, aggregate engagement or a passing test as
  evidence of real per-user retention, revenue or customer action execution.
- Inspect production revision/configuration before each release, retain rollback artifacts and
  database backup, run required quality gates, then verify the exact deployed behavior.

## Verification

For every workstream retain code/test evidence and production observations. All automatic tests
use fakes. Browser testing uses an isolated database and fake Telegram delivery. Safe production
GET checks must demonstrate no additional provider requests. Live mutations require an explicitly
approved canary target and verified rollback/reconciliation behavior.

Initial inspection: admin and API health returned HTTP 200 on 2026-09-29. No implementation or
release in this ledger should be marked complete without corresponding evidence below.

### First increment (implementation; production verification pending)

- Added saved Retention overview API and Russian `/retention` workspace with source coverage,
  source mode, age, findings, sample counts and completed-run evidence. Missing mobile sources
  display no-data, not zero. Per-user risk and customer actions remain explicitly unavailable.
- Removed external provider health probes from administrative GET endpoints. Health is persisted
  evidence, with explicit missing/stale states and configurable staleness threshold.
- Translated navigation, page controls, statuses and confirmations; advanced JSON is collapsed.
  Longer Russian navigation is scrollable on short screens. Manual analysis requires confirmation.
- Local gates: 277 backend tests, 26 frontend tests; Ruff, mypy, ESLint, TypeScript, generated API
  synchronization, production build and secret scan passed. Fake-provider browser E2E passed:
  login, manual-run confirmation, different-admin approval/rejection, refresh/logout, Retention
  evidence and mobile layout. Desktop/mobile screenshots were inspected in `output/operation-admin-20260929/`.
- npm audit retains the previously documented moderate dev-only `undici` advisory; the high-level
  gate passes. No dependency or credential changes were made.
