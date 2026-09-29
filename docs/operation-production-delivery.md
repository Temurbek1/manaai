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
| Russian, understandable interface | Russian primary UI, human-readable agent/status/action labels, clear evidence/proposal/approval separation, explicit empty/error/loading states, technical IDs and JSON in secondary details. | Russian primary navigation and workflows deployed; historical provider narratives remain original evidence. Further risk/action workflows must follow the same conventions. |
| Safe website reads | Page refresh reads persisted views only; no provider health probes or collection. Source age, completeness and live/sandbox state are explicit. | Regression-tested and production-verified on 2026-09-29. |
| Retention workspace | Real saved engagement evidence, source coverage, findings, history and actionable explanations visible in the admin UI. | Dedicated saved-evidence workspace deployed; authenticated public API and local browser/mobile checks passed. |
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

### First increment (deployed 2026-09-29)

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

Production evidence at 15:23 UTC:

- Code commit `e73c10afc2a1c6d886d442f9e3bdb7b59acd5e38`, pushed to
  `feat/operation-admin-20260929`; deployed immutable checkout `/opt/manaai-releases/e73c10a`.
  Backend and admin images carry the full revision label; transferred filesystem layers match
  the locally built/tested images. The backend image itself passed 277 tests, 3 skipped.
- Verified PostgreSQL dump and prior configuration retained in
  `/var/backups/mana-ai/operation-admin-20260929/`. No schema migration or PostgreSQL restart.
  Effective Compose/runtime environment comparison passed: only build/image revision changed.
- API, admin and worker containers healthy. Brief admin HTTP 502 was observed during replacement,
  before startup completed; subsequent public health, seven Russian routes and auth checks pass.
  Do not describe this replacement as zero downtime.
- Eighteen repeated authenticated local GET checks (dashboard, agent cards, marketing,
  Retention, integration health) created no new runs. Public API and frontend-proxy Retention
  checks return 401 without credentials and 200 with the existing technical credential.
  API/worker logs during the verification window contain zero Retention provider requests.
- Saved live Retention evidence is from run `56594008-f0c4-457f-8529-3be344467cef`,
  collected at `2026-09-29T12:20:22.296723Z`, with five Firestore documents. Mobile analytics
  remains unavailable, explicitly not zero. Source completeness values must not be interpreted
  as population coverage: the operational Firestore sample remains deliberately tiny.
- Retention schedule remains enabled at `20 */6 * * *` UTC with next slot 18:20 UTC;
  limits and circuit breaker unchanged. No manual collection or canary was launched for this UI release.
- Audio readiness is `ready`; unauthenticated submission is 401 and authenticated invalid
  payload is 422. No real audio/model request was made for these checks. Pre-restart log window
  contained 18 accepted and 18 delivered audio jobs, with no unmatched IDs.
- Public browser check reached the Russian login form. Authenticated Russian workflows and
  mobile layout were verified locally using isolated fake Telegram/providers, not by bypassing
  production Telegram authentication.
- Active server release instructions updated; previous incident-fixed `4253e82` images and
  checkout remain available for application-only rollback. SSH, nginx, keys and Firebase
  rules/IAM/documents are unchanged.

Remaining scope is the full ledger above, including real per-account risk, governed customer
actions, executive goals/orchestration and Technical Reliability last. This release does not
close the overall objective.
