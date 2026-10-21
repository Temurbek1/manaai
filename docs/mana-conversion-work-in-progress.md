# Conversion goal — unfinished local work

The original goal remains active: track each MANA free account, identify timely
upgrade opportunities, communicate approved offers through Parent-Touch, and measure
verified paid conversion. This checkpoint does not narrow that goal to free grants
or claim the full implementation is complete.

Source: `/mnt/ssd2/mana-conversion-agent-20261021`, branch
`feat/mana-conversion-agent-20261021`, based on published family `8683f20`.
This is a locally verified implementation checkpoint, not a finished goal.
Root operational application dirt was not edited; only its owned handoff documents
were updated to point here.
Production remains family `f8d095e`; no conversion release, real contact, paid model,
Firebase/GA4 read, tariff grant, SSH/key or schedule change was performed. One
bounded Parent List contract read for previously designated test parent `4` was
performed separately, as described below.

## Owner clarifications

- `/home/samanwirst/Downloads/Telegram Desktop/agent-tariff-api.md` was read fully.
  It documents only `POST /api/v1/admin-panel-payment/agent-grant-tariff/` after
  existing JWT login. Body is integer `parent_id` and 1–30 `days`.
- This is one lifetime non-paid Maxsus grant. No payment/transaction is created.
  It is NOT a 15% discount API, paid subscription, or subscription-status source.
  The backend rejects an existing grant/active paid tariff/missing configuration.
- The owner explicitly confirmed that the agent must not create payments or
  transactions. The new adapter has no payment/transaction-creation call.
- Earlier `parent-api.md` was re-read: current `tariff_name`, `valid_until`,
  `payment_date` do not distinguish paid from free; `is_paid` is not filtered.
  Do not infer an authoritative subscription state from those fields.
- A fresh login and one exact `parent_id=4&limit=1&offset=0` GET returned 200,
  count one, matching ID, no next page. Only field names/types were retained:
  `age`, `children`, `children_count`, `district`, `fullname`, `id`, `payment_date`,
  `phone`, `region`, `status`, `tariff_name`, `valid_until`. No actual personal
  values were logged. `is_paid`, free start/end, agent-trial history, marketing
  consent, language, registration/activity metrics were absent. No retries,
  scans, Firebase reads, grant or push occurred. The documented duplicated
  `/api/v1/api/v1/` prefix was not used.
- `notify-parent-api-2026-10-16.md` was read fully. It accepts only title and
  description after JWT login, and reports a device queue, not delivery. The owner
  requested first contact even if the parent has never written, and explicitly
  authorized parallel agents for implementation/review.

## Implemented locally, not a finished release

- Typed adult-account observations, hot/seven-day deterministic eligibility,
  server-approved paid/free offer catalogs, recurring-price disclosures,
  consent/opt-out, cooldown/rolling caps/recipient quiet hours, scoped outcomes.
- Private SQLite v7 atomic proposals and Parent-Touch assistant-only templates;
  no fabricated parent message, provider receipt or child-analysis event. No LLM
  needed for eligibility or commercial templates; normal chat stays AI-backed.
- Priority gates behind questions/notices/in-flight child/chat jobs; current
  account/offer/consent checks before publication. Only Parent-Touch publishes.
- Backend-only routes, conditional directory entry and default-disabled runtime.
- Explicit same-family activation phrase + typed backend confirmation before
  one durable non-paid trial action. No unknown/rejected automatic retry or new-
  nonce bypass. Real HTTP adapter uses the documented login/grant endpoints only.
- A fresh JWT is obtained once per distinct trial grant or push. No indefinitely
  cached expired JWT, automatic write retry, redirects or relogin-after-denial.
- [Proactive Parent-Touch](mana-parent-proactive.md): explicit typed recipient
  language/timezone/separate contact permissions, first assistant-only message
  before parent text, immutable locale admission and one-shot durable push outbox.
  Safety messages and commercial templates remain one speaker in one history.
  Push failure/zero devices never erase the message or trigger model repetition.
- Current account/opt-out/paid state/offer validity are checked again before a
  marketing push claim. Generic notification text contains no child facts or
  offer price. A claimed unknown/submitting external send is never reclaimed.
- Additive SQLite v6 -> v7 -> v8 migration and current closed/history-only v8
  reader. Old production v6 images cannot read v7/v8; no old-image rollback or
  candidate-container acceptance is claimed. Feature flags default disabled.
- Authenticated ASGI/runtime/lifespan coverage proves automatic first-contact
  progression with fake model/source/push, observation-only GETs, explicit
  language, exact replay, zero devices and state-preserving deactivation.

## Verification checkpoint — 2026-10-21

The original full gate (session `8388`) failed one architectural check because
the private push-claim field was named `state`. It is retained as a failed run,
not relabelled. Renaming it to `notification` fixed the prohibited attribute
without weakening the architecture test. Synthetic credentials were relabelled
with the existing `fake-` convention; the secret scanner was not relaxed.

The subsequent **`make verify` session `34793` terminated with exit 0**:

- Ruff format/check, UI formatting/ESLint and 34 lint compatibility checks passed.
- mypy: **268 files**; TypeScript typecheck passed.
- Backend: **707 passed, 1 skipped, 2 deselected**, 39.48 seconds.
- UI: **26 tests /11 suites**; Next production build passed.
- Dependency audit: **zero vulnerabilities**.
- Separate secret scan: **436 files**, passed; `git diff --check` passed.
- Generated local product schema: **41 paths /45 HTTP operations**, synchronized
  with `admin-ui/openapi.json` and TypeScript definitions. These are local routes,
  not a claim that the production ingress was changed.
- After handoff documentation was added, the secret scan passed **437 files**.
  All six guide JSON examples validate against typed contracts. Comparing the
  complete generated admin schema against baseline found no removed or changed
  existing paths; the new API is additive.
- Staging the new guide exposed an inherited Markdown trailing-space line that
  the earlier unstaged check had not covered. It was corrected in a docs-only
  follow-up; no application code or verification policy was changed.

All automated provider tests use fakes/MockTransport. Notable coverage includes
86 push-adapter cases, 48 proactive-store cases and 16 proactive-service cases;
these are subsets of the 707, not additional tests. No real push, free grant or
paid-model generation was used for this checkpoint. Three delegated agents
covered gateway integration, SQL first-contact/outbox, and conversion/service
review, with the main agent integrating HTTP/runtime/docs and the final gate.

## Next work — preserve the complete goal

1. Finish Parent-Touch's typed commercial context/recipient acceptance flow and
   non-paid grant result communication. Currently the backend acceptance route
   exists; ordinary chat must not falsely claim a grant has already succeeded.
2. Add an actual subscription-state/activity source or agree an owning-backend
   event producer. Current input contract is a backend observation; a production
   event feed is not installed. No full-population scans are authorized by this WIP.
3. Verify the trial-expiry -> honest paid-upgrade invitation path; do not promise
   a discount without billing-confirmed support. A free grant must never become a
   recorded paid conversion. Keep real purchase measurement separate from interest.
4. Perform candidate-image/state-preserving closure checks and an approved
   designated-device channel acceptance before a separately scoped production
   contact release. Current fake/SQLite tests are not broad model quality,
   notification delivery or measured business improvement. Keep the goal active.
5. Preserve the verified local increment and exact unknown holds. `.venv` is a
   local symlink and must not be committed. No sweep of the unrelated root tree.

The owner's parallel documentation request is fulfilled in
`docs/mana-single-chat-integration.ru.md`: the five production examples remain
unchanged, and a clearly unreleased supplement documents first contact/push.
The last production OpenAPI read showed 32 paths and no conversion/proactive
routes. Production remains `f8d095e`; no new production recheck is implied by the
local 41-path export.
