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
Firebase/GA4 read, tariff grant, SSH/key or schedule change was performed. Bounded
Parent List contract reads for previously designated test parent `4` were
performed separately, as described below and in the subsequent source checkpoint.

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

1. Add an actual subscription-state/activity source or agree an owning-backend
   event producer. Current input contract is a backend observation; a production
   event feed is not installed. No full-population scans are authorized by this WIP.
   [The owning-backend contract](mana-conversion-backend-events.ru.md) lists exact
   required fields/provenance and current routes. Real approved offer terms remain
   necessary; a synthetic 15% fixture is not a production billing discount.
2. Complete approved designated-device channel acceptance and a separately scoped
   production contact release. The packaged candidate/closed-v9 diagnostic now
   passes; it is not real model quality, delivery or business measurement. See
   [the actual candidate checkpoint](mana-conversion-candidate-checkpoint.md).
   Do not mark the original goal complete without authoritative source coverage.
3. Verify ordinary conversation quality with the new frozen terms, not merely
   prompt contents. The explicit backend acceptance endpoint remains required;
   there is no automatic free grant triggered by model text. Closed-mode grant
   HTTP observation still returns controlled 503 when its service is disabled;
   the durable SQL receipt and chat remain retained.
4. Preserve the verified local increment and exact unknown holds. `.venv` is a
   local symlink and must not be committed. No sweep of the unrelated root tree.

## Subsequent commercial-context / expiry increment

See [the detailed checkpoint](mana-commercial-conversation-checkpoint.md).
Default-disabled `MANA_CONVERSION_CONVERSATION_ENABLED` adds private v9 for new
parent turns only. It freezes exact published offer terms and known receipt status,
binds actual acceptance to that offer, and atomically queues one same-chat terminal
grant-result message. Wrong/malformed `Maxsus` receipts become durable unknown.
The opt-in expiry decision requires fresh confirmed end dates and chooses paid
offers only; elapsed days stop at the actual end. Existing histories never upgrade.
Only current same-code closed-v9 readers are verified, not old v8/production images.

Full **`make verify` session `33729`, terminal exit 0**:

- **780 backend tests passed**, one skipped, two excluded; 39.60 seconds.
- **26 UI tests /11 suites**, Next production build passed.
- Ruff format/check, UI formatting/ESLint (34 compatibility cases), TypeScript
  and mypy **272 files** passed; dependency audit zero vulnerabilities.
- Secret scan before the final docs update passed **443 files**; after the
  checkpoint was included, the final scan passed **444 files**. Diff check passed.
- 43 new expiry domain cases and 24 commercial SQL/HTTP/review/runtime cases are
  included in the total, not additional tests. Provider receipt tests include the
  tariff/malformed-instance regression. All use fake providers and fictional adults.

No paid model call, real source read, grant, push, production/SSH/key/schedule
change occurred in this increment. The prior bounded Parent List diagnostic is
historical and was not repeated. English single-chat documentation is also kept
in this feature source, alongside the preserved Russian version.

## Packaged candidate and English backend handoff

The actual `efc9645` application image **`88193f53d363…`** passed the new network-
disabled conversion SDK/HTTP/worker lifecycle and the existing family diagnostic.
All 184 packaged Python source hashes match; `/app/.env` is absent. Exact legacy
row fingerprints and the 2000-token unknown hold survive migration and closed-v9.
No host/customer data, source refresh or real external call was used.

Subsequent **`make verify` session `10748`**, terminal exit **0**: **781 backend /
26 UI tests**, mypy **274 files**, lint/types/build and audit zero. The added
diagnostic uses fake provider decisions; it does not establish real sales quality.
See [the complete candidate evidence](mana-conversion-candidate-checkpoint.md).

[English backend event integration](mana-conversion-backend-events.en.md) now
specifies the actual missing input and owning-backend producer boundary. Its JSON
example validates against the typed snapshot. The full objective is still not
complete: there is no confirmed real all-parent state feed or real offer catalog.
Final secret scan passed **448 files**, and `git diff --check` passed. The source
owner was asked for the missing authoritative subscription endpoint/documentation;
no undocumented endpoint or paid/free inference was invented in its place.

## Revalidated external blocker

After the commercial and candidate checkpoints, the next continuation re-read
the provided `parent-api.md` and `agent-tariff-api.md`. They still describe current
tariffs with `is_paid` deliberately unfiltered, and a non-paid grant POST only.
Neither supplies authoritative paid/free classification, free-period history,
all-parent activity/permissions or real paid-offer terms. A configuration-name-only
check of the root `.env` found no conversion or subscription/tariff/activity-source
entries; no values or credentials were printed by that check. This is not a claim
that the missing data does not exist elsewhere, or a new production inspection.

Feature source remains `e4aee2c` with only its pre-existing local `.venv` symlink
untracked. No provider process is left running or awaited. The last goal turn made
real progress through the packaged checks; this continuation confirms that the
same missing-source/catalog dependency, already recorded in the last two goal
turns, still prevents the full requested end state. More fake accounts, repeated
tests or new synthetic offers cannot install that external backend integration.

The source owner has already been asked for the concrete endpoint/documentation.
Resume the full objective when that source or a committed backend event producer
and approved real offer terms are supplied. Do not infer subscriptions from tariff
names, activate real contacts, invent a 15% discount, or mark the goal complete.

The owner's parallel documentation request is fulfilled in
`docs/mana-single-chat-integration.ru.md`: the five production examples remain
unchanged, and a clearly unreleased supplement documents first contact/push.
The last production OpenAPI read showed 32 paths and no conversion/proactive
routes. Production remains `f8d095e`; no new production recheck is implied by the
local 41-path export.

## Newly announced Parent List fields

The owner subsequently reported `is_paid`, `created_at` and `agent_trial_used`.
One post-announcement exact-parent production check returned 200 but still
omitted these keys. The deployment and date semantics were requested, not guessed.

[The new source contract checkpoint](mana-conversion-account-source-checkpoint.md)
adds an account-only application port, minimized typed facts and a strict bounded
HTTP adapter. It does not add a runtime read, population producer, migration or
contact release. Missing fields fail closed; explicit null stays unknown.
`created_at` is not yet mapped to free-period start, and a selected non-paid
record does not establish paid-entitlement precedence. Durable source admission
must be implemented before runtime wiring; an idempotent event replay must never
perform a new source read. Existing event/offer/permission requirements remain.

Final **`make verify` session 92804**, exit **0**: **856 backend /26 UI tests**,
mypy **278 files**, lint/types/build and audit zero. The earlier no-key collection
failure is retained in the detailed checkpoint; the successful run used only an
explicit dummy key. Final secret scan **453 files** and diff check passed.
All new provider tests are fictional. This is source-boundary acceptance only,
not live-source, full-population, contact or production acceptance.
