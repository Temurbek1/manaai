# Source change -> Child-Safety -> Parent-Touch — local checkpoint, 2026-10-24

This advances the full [autonomous-agent objective](mana-autonomous-agents-plan.md),
not a replacement goal limited to battery readings or a production release.
Source checkout: `/mnt/ssd2/mana-conversion-agent-20261021`, baseline `25c563c`.
All remaining source/native-tool, commercial/reminder, administrative, real-quality
and release requirements in the inventory remain open.

## Implemented path

The existing private source cache now supports an opt-in source-to-safety consumer.
Source publication atomically freezes whether that **new change** was admitted
under the exact consumer policy. An event published with the consumer disabled,
a missing admission, or an older v1 change cannot gain automatic inference later.
Consumer activation records an SQL cutoff, not a source scan or historical backfill.

The consumer freezes its source event, exact snapshot/fingerprint, fresh connected-
child profile/known age, policy, target and existing `SafetyMonitorRequest` before
dispatch. The actual request is stored with an exact hash; receipt observation
cannot recapture its data or authorization. Parent names/phone numbers are not
copied into source receipts. Preparation claims are durable before profile I/O;
lost preparation is not automatically repeated. A stored intent can resume without
another profile/source read, but the existing Child-Safety workflow still verifies
current ownership before inference.

Child-Safety admission remains the existing local SQL lifecycle, not a new model
or duplicate queue. A claimed dispatch is single-use. On a lost acknowledgement,
`observe_analysis_request` checks the exact original parent/request/body in family
SQL: an existing job is observed, and an absent uncertain result is not redispatched.
Cancelled/unknown results retain their exact context. SQL observation of an unknown
preparation does not convert it into an admission attempt. The consumer journal
retains independent states: preparing, prepared, dispatching, admitted, skipped,
unknown. `admitted` is not a completed analysis, parent message or push receipt.

Semantic measurement dedup ignores database-write-only timestamp changes. A source
cursor advances atomically with its consumer receipt, so idle polling does not
rescan the whole change history. Missing, ambiguous, undated, stale, unknown-age or
revoked-child cases remain qualified skips, not fabricated measurements or claims
that the child is safe. Undated source facts remain readable as qualified cached
facts; they do not become current automatic alerts.

`BatterySignal.online` now additionally accepts explicit null. The old boolean
values and default true remain unchanged for old callers. New battery-derived
requests use null: a battery write is not proof of connectivity. Deterministic
analysis emits no offline finding for null and preserves an uncertainty note.
There is no invented charging state, camera/phone control or emergency action.

The optional consumer hook in `FamilyAgentWorker` defaults to absent. The lab
explicitly installs it with one fictional family/source. Its new scenario reaches
the same existing Parent-Touch notice and chat without an initial parent message.
Only Parent-Touch publishes. Existing consent/language, safety budgets, question
priority, dated report checks, delivery dedup and push gates still apply.

## Storage and compatibility boundary

Only the additional source cache gains private **schema v2**: consumer policy,
captured admission and dispatch tables. V1 cache snapshots, exact read receipts,
pending/unknown source holds and limits are preserved. Migration captures the
current change cutoff and does not backfill inference. The v1 reader refuses v2;
it is not a rollback reader. Do not downgrade/overwrite a populated cache.

Family chat remains schema **v9** in the lab. Nullable source inputs are a new
input contract: old active workers must not execute them. Current-code closed
family/source readers preserve the input, history and an actual fake submitted
model hold through a three-day clock change. That is a **same-code closed-mode
check**, not old-image/candidate-image or production rollback acceptance. A future
release needs its exact compatible closed image and stop/backup/reconstruction
checks; no migration or new worker ran against production.

No source registration, model tool selection, real credential construction,
09:00/15:00 collection, listener, transport retry, new public product route or
source write is enabled by this increment. Product paths/auth remain unchanged;
the generated public component change is the explicit nullable battery field.

## Lab and English integration

`make chat-lab` now offers **Низкий заряд (тестовый источник)**. Its private
`POST /lab/child-battery` remains fixed-family, cookie/CSRF/Origin protected and
outside the product factory. Controlled refusal is not an unhandled HTTP 500.
The UI reports cached reuse, not a promise of another message. Diagnostics expose
only fictional SQL change/dispatch state. Initial history opens at the latest
message; normal polling does not pull the user away from older history.

The fixture date is durably saved in `source-fixture.json` and is never refreshed
by reload or restart. Source data is fictional in both simulation and optional
paid-model modes. No fixture reset or alternate real-model quota was used.
The [English integration guide](mana-single-chat-integration.en.md#11-autonomous-source-to-chat-processing--local-not-released)
explains that mobile retains the same three chat operations; local lab routes are
not production integration endpoints.

## Actual verification

Final full **`make verify` session 9237**, terminal exit **0**:

- **1064 backend tests passed**, one skipped, two opt-in live tests excluded.
- **26 admin tests** /11 suites and **seven lab controller tests** passed.
- Ruff formatting/lint, ESLint with 34 compatibility checks, strict mypy
  **298 files**, TypeScript, Next production build and dependency audit
  (**zero vulnerabilities**) passed.

The new source-safety suite has **21 fake-only cases**, terminal session **36352**.
They cover assistant-only first contact, exact one-analysis/source reuse, explicit
unknown connectivity, lost/absent/cancelled admission acknowledgement, prepared
restart without recapture, stranded preparation, stale/undated skips, revoked
ownership before inference, semantic dedup, populated v1 migration and refusal,
intent corruption, foreign-family observation, disabled-event admission capture,
preparation stop fences, current closed readers/unknown model holds and atomic
rollback of source publication plus consumer admission. The additional ASGI case
exercises the actual SQL worker and authenticated lab route; browser-controller
cases cover correct local routing and an unknown source result without redispatch.
These counts overlap the final gate and are not additive quality evidence.

Earlier focused passes (16 initial cases, then 63 related cases) and full session
**93529** (1062 backend /26 admin /five controller) predate the last regressions/UI
handling. Initial static runs failed on formatting/long SQL lines before pytest;
those remain failures, not a green full gate. Context-mismatch patches changed no
files and were reapplied against formatted source. No negative real-model party
or historical lost receipt was replayed or rewritten.

Actual isolated Chromium verified the local browser -> authenticated lab API ->
source cache/consumer SQL -> existing specialist/Parent-Touch -> chat path with
saved earlier history. The new message contained **12%**, its original October 24
observation date and unknown-connectivity qualification. Two subsequent button
presses/reload retained **one source change**, **one admitted job**, **nine total
messages**, **750 simulated chat tokens and 750 simulated safety tokens**; only
the first flow added 150 to each already existing 600 ledger. No reset occurred.
The first-ever-parent-message case is established separately by ASGI/unit tests,
not falsely inferred from this browser's already populated history.

Desktop 1440x900 and mobile 390x844 screenshots were inspected under local
`output/source-safety-browser-20261024/`; the first mobile capture caught an
unfinished smooth scroll, and the settled/final captures show the complete
message. One read-only browser diagnostic had a JavaScript syntax error; the
corrected observation read SQL only, not another POST. Browser errors were empty.
The owned browser was closed and server PID **1321842** shut down gracefully,
terminal session **52806**, exit **143**. No test/model/source data was removed.

## Remaining acceptance

No real Firebase/GA4/Manakids/OpenAI call, push or grant occurred in this increment.
No production, key, SSH, scheduler or shared source setting changed. Real server
credentials and model-selected source tools still need wiring, bounded cost proof
and actual acceptance. The 2000-token global safety pool is not proven sufficient
for whole-population analysis. Passing the simulation does not establish model
quality, emergency response, customer delivery, retention/paid conversion or full
four-agent administrative capability. The complete goal remains active.
