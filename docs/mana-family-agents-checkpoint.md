# Parent-Touch / Child-Safety — production handoff, 2026-10-20

## Active production release

The owner authorized deployment and explicitly set **2000 Child-Safety tokens/day
globally across all parents**, separate from **2000 Parent-Touch tokens/day per
parent**. Application **`f8d095e`**, private SQLite **v6**, is now enabled on the
isolated parent-chat sidecar. Release documentation is committed as **`813ad50`**
in the clean feature worktree; this root tree retains unrelated owner changes.

Read [the authoritative production record](/mnt/ssd2/mana-family-agents-20261020/docs/mana-family-agents-release.md)
and [backend integration](/mnt/ssd2/mana-family-agents-20261020/docs/mana-family-agents-integration.md).

- Swagger: <https://ai.360rec.uz/docs#/mana-ai>; API base:
  `https://ai.360rec.uz/api/v1/mana-ai`.
- New `POST /parent-touch/messages` admits review-first work with `202`;
  SQL-only status/history GETs observe it. The legacy `/chat` stays compatible,
  not silently upgraded. The existing isolated backend token remains required;
  the general inference key cannot access family history.
- Child-Safety and automatic private-SQL event handling are enabled. New parent
  messages and backend-submitted child observations trigger work; no Firebase/GA4
  refresh, listener, historical backfill or operational schedule was activated.
  The application backend still needs to submit observations to the typed APIs.
- Safety reserves the whole **2000-token job** before inference. This tiny global
  pool generally admits only **one short analysis/day**, not continuous coverage
  for every family. Review-first messages cannot bypass an unavailable review.
  Unknown costs keep their holds; unchanged observations/replays do not regenerate.
- Only `mana-parent-chat-parent-chat-1` was recreated. Existing private volume,
  history, quota rows, backend/provider keys and SSH were preserved. Main/audio,
  operational API, UI, scheduler and PostgreSQL retained their container IDs,
  start times and configurations. All six containers are healthy.
- Fresh `make verify`: original session **88188**, exit **0**, **509 backend /
  26 UI tests**, mypy **247 files**, lint/types/build. Actual packaged-app checks
  used network-disabled fake providers. Both copied and live v1-to-v6 migrations
  preserved legacy row fingerprints; current compatible closed readers passed.
- Public/private authorization, all ten protective request validations, historical
  idempotent replay and Chromium Swagger rendering passed: **32 paths /35
  operations**. At acceptance safety used/reserved **0**, remaining **2000**.
  Two production-key model-metadata GETs returned 200; no new paid production
  generation was attempted. This is not real-family semantic acceptance.
- Server image `af269c62bdd3…` matches all ten filesystem layers and all nonempty
  runtime configuration of tested local image `d4e3af258227…`; only allowlisted
  omitted empty Docker metadata differs. The raw image digest is not identical.
- Kit: `/opt/manaai-releases/family-f8d095e-20261020/kit/`; backups:
  `/var/backups/mana-ai/family-f8d095e-20261020/`. Compatible deactivation retains
  v6 history with the current image; never restore an old database/image over it.
- GitHub push remains **403**: account `samanwirst` has pull but no push permission
  on `Temurbek1/manaai`. Production uses verified tracked source/image artifacts;
  remote branch publication still requires repository Write access.

## Historical local review-first checkpoint — `f8d095e`

Local implementation at that checkpoint: **`f8d095e`**, additive SQLite v6 /captured review-first
parent messages. Parent-Touch speaks only after the new Child-Safety review supplies
qualified guidance. New `POST /parent-touch/messages` returns `202`; its GET status
and the shared single-chat history are observation only. Old synchronous `/chat`
and `/parent-touch/chat` remain compatible, never silently upgraded.

Read [the current review-first checkpoint](/mnt/ssd2/mana-family-agents-20261020/docs/mana-family-review-first-checkpoint.md)
and [backend integration](/mnt/ssd2/mana-family-agents-20261020/docs/mana-family-agents-integration.md).
Full gate: **509 backend /26 UI tests**, mypy **247 files**, lint/types/build,
original session **67339**, terminal exit 0. Network-disabled actual candidate
**`d4e3af258227…`** passed v5/v6 SDK/HTTP/closed-profile checks: eight mocked
generations/ten fake profile reads, zero real source/provider calls. Twelve new
review-first regressions cover concurrency, expiry, late-publication fences,
unknown holds and no automatic retry across restart/midnight.

Two fresh synthetic RU/UZ parties: **16 known generations /$0.03402875** estimated,
no unknown holds. Final speaker totals **1691/1741** chat tokens; separately metered
specialist guidance precedes and supports the answer. Combined retained family
diagnostics: **135 /$0.21582965**, not an invoice. Limited model-quality qualifications
remain documented; this is not broad real-family/emergency/business acceptance.

The local two-agent API flow is implemented; production activation, isolated
ingress/credential checks and app-owned real-family/channel acceptance are separate.
No deployment, remote push, source refresh, key/SSH, audio, UI or OPERATION changes.
Actual code remains in the feature worktree below; unrelated root dirt is preserved.

## Previous specialist checkpoint — `920cc3f`

SQLite v5 /new private safety context v2.
The two APIs, event worker, notices and closed profiles now have host-bound text
slots, conservative language hints, output admission floors and independent role
models (new roles GPT-5.4 /mini; old production OPENAI_MODEL unchanged).
Read [the latest specialist checkpoint](/mnt/ssd2/mana-family-agents-20261020/docs/mana-family-specialist-checkpoint.md).
Explicit next-day backend continuation now handles only pure pre-generation quota
refusals, never unknown/paid calls or automatic worker retries. Actual full gate:
**497 backend /26 UI tests**, lint/types/build, original session **78773**, exit 0;
isolated network-disabled candidate smoke passed (image `873001e9e071…`).
Five new synthetic parties: **28 generations /$0.04819550** estimated; combined
**119 /$0.18180090**, all known receipts. Both automatic specialist loops passed
mechanically within 2000 chat tokens, but independent speaker judgments remain a
negative semantic result. Next implement durable **review-first** parent messages,
not more prompt-only tuning. **The complete goal remains active**, no deployment.
Older zero-spend/unimplemented statements below describe their historical stages.

The owner requested a new **application-facing** agent environment. Parent-Touch
is the only speaker in the parent's single chat and manages other agents'
questions. Child-Safety owns child protection/behavior analyses and reads the
same parent's conversation. This is not a fifth operational agent, replacement
of the four administrative domains, or an authorization to deploy on production.

Confirmed by the owner: re-analyze on **new child data or new parent messages**,
not unchanged-context polling; **2000 tokens/day belongs to Parent-Touch only**,
with a separate server budget for Child-Safety. The earlier twice-daily bulk
operational analytics direction is not this child-safety event-trigger policy.

## Authoritative implementation

- Worktree `/mnt/ssd2/mana-family-agents-20261020`, branch
  `feat/mana-family-agents-20261020`.
- Baseline `bf1d12a`, the clean isolated parent-chat release branch, not the
  unrelated dirty operational working tree.
- Local core commit **`d796c8c`** (`Build durable Parent-Touch question coordination core`).
- Local HTTP/runtime commit **`3f8f3f4`** (`Wire backend-only Parent-Touch chat and durable delivery API`).
- Local event/budget core commit **`867d915`** (`Add durable Child-Safety event outbox and separate token ledger`).
- Local API/runtime commit **`e30fba4`** (`Wire Child-Safety API, metered analysis and Parent-Touch question worker`).
- Detailed contracts and full remaining acceptance:
  [family-agent implementation document](/mnt/ssd2/mana-family-agents-20261020/docs/mana-family-agents.md).

Implemented and verified locally: two family-role definitions; one-speaker policy;
durable priority/coalescing question queue; one active question per parent;
explicit answer/child/parent bindings; atomic admission and question publication
with accounting; retained unknown holds; fresh own-child checks before question
inference; structured single-question model replies with strict raw usage;
preserved old message digests, history and quotas. This is a service/store/model
core. The subsequent HTTP increment wires that core into authenticated
`/parent-touch/chat` GET/POST, `/parent-touch/requests` GET/POST,
`/parent-touch/deliver` POST and `/agents` GET. Parent-Touch and old `/chat` use
one runtime/history/quota; response replay retains the original asked-question
identity. Proactive delivery stores no fake parent text and freezes language from
the latest saved parent message. Durable intent claims precede ownership reads;
nonce/body/revision duplicates, source failures and terminal answers do not
repeatedly read children. Child-Safety is honestly listed as `not_implemented`.
This is **not yet the event worker or Child-Safety execution**.

Full `make verify`: original session **71187**, actual exit **0** and log marker
`MAKE_VERIFY_EXIT_CODE=0`: **364 backend tests**, **1 skipped**, **2 opt-in live
tests excluded**, **26 UI tests /11 suites**, formatting/lint, mypy **217 files**,
TypeScript/build, zero npm vulnerabilities. Related focused suite **82 passed**;
counts overlap, not additive. Tests use fakes/actual SDK MockTransport only.
Logs: ignored `output/family-agent-core-verify-20261020.log`,
`output/family-agent-parent-touch-final-20261020.log`,
`output/family-agent-schema-20261020.log`, and secret scan log.
That was the historical core gate. The current HTTP increment's terminal
`OPENAI_API_KEY=unit-synthetic-key make verify`, original session **28013**, exit
**0**: **375 backend tests**, **1 skipped**, **2 live tests excluded**;
**26 UI tests /11 suites**, lint/format, mypy **220 files**, TypeScript/build,
zero npm vulnerabilities. Related suite **97 passed**, plus a standalone
checkout-resolution regression; these counts overlap the full suite.
Log: `output/family-agent-parent-touch-api-final-verify-20261020.log`.
The first attempt without a synthetic key failed at legacy test import and is
retained as `output/family-agent-parent-touch-api-verify-20261020.log`, not a pass.
Generated/public contracts now include the implemented routes; product docs
export **17 paths**. Both exporters resolve their own checkout instead of an
unrelated editable install. `make audit-schema` and secret scan **381 files** pass.
No new live model/child/Firebase/GA4 call was made; local provider spend is **$0**.

## Subsequent Child-Safety core checkpoint

The private `SqliteChildSafetyStore` **v4** now provides an atomic parent-message
outbox, typed child-data admissions, immutable bounded own-family chat/saved-result
references and a separate explicit job/parent/day/server/day token ledger.
Equivalent observed facts are deduplicated independently of new request IDs,
revision labels, evaluation/display metadata, UTC-offset representation or later
chat messages; parent messages have their own review jobs. Assistant-only questions
are included in the frozen conversation, but never trigger another safety event.
SQL eligibility filtering prevents full/exhausted queue prefixes from starving
other families. Claims precede future provider I/O, never requeue unknown costs,
and retain raw verified costs before future decision validation. Late receipts
reconcile original-day usage without publishing new decisions; budget counters
and Parent-Touch's 2000-token quota remain separate.

Evaluation time, actual signal timestamp bounds and SQL/process dates are stored
separately after known-terminal raw input cleanup. Exact stored capability
restoration prevents structurally overlapping protective requests from turning
into another capability. Result and optional specialist-question publication
are atomic; only Parent-Touch inserts parent-facing messages.

Latest full gate: original session **37549**, exit **0**,
`output/family-agent-safety-ledger-final-verify-20261020.log`: **398 backend tests**,
**1 skipped**, **2 live tests excluded**, **26 UI tests /11 suites**, lint/format,
mypy **223 files**, TypeScript/build and zero npm vulnerabilities. **23** new ledger
cases /**74** focused related cases overlap the full suite. Schema synchronization
and secret scan **384 files** pass. These are manual fake/SQLite receipts and
ID-authorization checks, not a live SDK/source/worker or complete agent-quality pass.

The application factory still selects v1/v3: v4 has **no runtime flag/worker/source/
model/HTTP activation** yet. No real server budget or external source was enabled.
V3-to-v4 local migration preserves old history/replay/unknown holds; older readers
refuse v4, not a working rollback. Do not deploy this checkpoint as the finished API.

The local family SQLite **v3** upgrade is additive and preserves old family history;
older v1/v2 readers **refuse it**. That is fail-closed evidence,
not a working rollback. Do not deploy this checkpoint, downgrade its populated
tables or restore an old database over newer history.

## Earlier API/runtime checkpoint (`e30fba4`)

`e30fba4` wires all ten Child-Safety POST contracts, SQL job paging/status/budget
GETs, strict SDK receipts, fresh own-child profile checks, existing deterministic/
evidence/proposal validation and the SQL-only event worker. One metered generation
is captured for existing validation, never repeated by another gateway. New
information needs automatically reach the one chat through stable-ID Parent-Touch
delivery; its assistant-only turns do not trigger another safety analysis.
The actual lifespan/HTTP fake-model test verifies analysis -> automatic question
-> parent reply -> historical follow-up, separate token counters and safe replay.
Global daily attempts also bound zero-token source failures.

Runtime is default disabled via `MANA_CHILD_SAFETY_ENABLED`; explicit
`MANA_CHILD_SAFETY_LIMITS` JSON and Parent-Touch/chat configuration are mandatory.
No real budget or production/source/model integration was activated. GET/replay
never dispatch; an unavailable worker refuses new jobs but preserves saved replay.
The SDK adapter reuses strict terminal/raw usage transport, disables retries/
storage and uses pinned SDK 2.53.0 strict-schema conversion before requests.

Terminal `make verify`, session **74434**, exit **0**:
`output/family-agent-child-runtime-final-verify-20261020.log`: **416 backend tests**,
**1 skipped**, **2 live tests excluded**, **26 UI tests /11 suites**, lint/format,
mypy **232 files**, TypeScript/build, zero npm vulnerabilities. **41** focused
tests overlap that gate. Docs expose **30 paths**; all earlier path definitions
remain unchanged. Schema synchronization and secret scan **393 files** pass.
The earlier format-only failed gate is retained separately, not called a pass.

Remaining: Parent-Touch needs frozen validated assessment context and automatic
assessment/urgent-notice delivery when no clarification is needed. The current
worker only automatically delivers questions. Add a compatible v4 closed reader
before release: disabling safety currently selects a v3 reader that refuses a
populated v4 DB, preserving data but breaking availability. Never downgrade/restore
history to bypass it. Broader semantic and actual candidate/rollback checks remain
open; current results are fakes/SDK MockTransport, not real-model quality,
production deployment or full goal completion. No external source/model spend.

## Historical continuation notes (latest v5 checkpoint below supersedes these)

1. Wire the implemented outbox, immutable data/chat admissions and separate ledger
   into the actual Child-Safety application service/worker. Read fresh ownership
   once per claimed job and validate it against the canonical family before
   source/context/model use; fake ID authorization is not that integration.
2. Add automatic communication delivery and a separate urgent-notice policy without
   bypassing Parent-Touch, question ordering, ownership or its token allowance.
   Producer admission and terminal/nonce-independent filtering are now implemented.
3. Implement capability-specific Child-Safety routes around the existing ten
   protective contracts and validation pipeline, with fresh ownership and dated
   family-chat context. Child-Safety must never write directly into the chat.
4. Connect the implemented separate budget to strict model receipts,
   worker/restart recovery and bounded input/context admission. Do not silently
   assign an unlimited budget or activate provider refresh/listeners.
   Require explicit configured Child-Safety ceilings when enabling it, reserve
   global/per-parent/per-job usage before inference, retain unknown holds across
   restart/midnight and account raw terminal usage before schema validation. The
   unchanged generic inference gateway uses parsed output/default SDK retries;
   it is not suitable as that new ledger's receipt boundary. Reuse its deterministic
   analysis/evidence/action-proposal validation through a captured typed gateway,
   not a second paid model call. Follow-up chat may use dated derived assessments;
   it must not pretend to refresh sensors or expose another family.
   Add an explicit server-wide daily attempt ceiling before real source I/O as
   well as the existing per-parent attempts/pending limits, so zero-token source
   failures across many parents cannot become unbounded external traffic.
5. Complete HTTP/security/SDK/event/language/queue end-to-end tests, docs and actual
   candidate-image/rollback acceptance, then integrate without overwriting the
   existing root parent-chat changes. Goal completion remains unproven until
   both working APIs and the full user-requested loop are demonstrated.

The operational archive WIP and its interrupted processes belong to the older
work, not this goal; do not restart those tests/paid diagnostics automatically.
Main/audio, existing parent chat/key/history/volume, SSH, operational data,
providers, schedules and production remain untouched.

Root unrelated tracked diff remains SHA-256
`f4b205e5bfe8cc650416eac2f351c39dc60fb74cab460e800c24cf9280427559`.

## Earlier v5 checkpoint — `1bea31c`

Feature worktree `/mnt/ssd2/mana-family-agents-20261020`, branch
`feat/mana-family-agents-20261020`; production/root application code untouched.
New handoff: [backend integration](/mnt/ssd2/mana-family-agents-20261020/docs/mana-family-agents-integration.md).

V5 freezes one minimized validated assessment plus at most one highest-severity
finding, every quality note and separate actual dates at chat admission. New
inference filters freshly revoked children/choices; replays retain original
responses and never reread sources. Child-Safety atomically queues typed notices,
never writes chat. Urgent validated ALERT/BLOCK facts can pass an awaiting question
through Parent-Touch without creating another question. Routine notices coalesce
and may defer without immediate paid repetition. GET remains SQL-only.

The model schema permits only admitted IDs/null, disallows questions in ordinary
body, and the host now rejects transport IDs/UUIDs in visible text. These guards
do not establish semantic quality. The concise Parent-Touch prompt is separate
from unchanged legacy-mode instructions. All raw verified usage is charged before
format validation; unknown calls are not retried or refunded.

Explicit safety-off v5 broker and Parent-Touch-off history/replay-only profiles
preserve schema/history/unknown holds without constructing a safety provider or
worker. V1-to-v5 migration does not recapture old turns. Old production/v1–v4 images
still refuse v5; verified same-candidate deactivation is not an old-image rollback.

Final `make verify`: session **42783**, actual exit **0**, ignored log
`output/family-agent-v5-notice-acceptance-verify-20261020.log`: **433 backend tests**,
**1 skipped**, **2 opt-in live excluded**, **26 UI tests /11 suites**, lint/format,
mypy **237 files**, TypeScript/build, zero npm vulnerabilities. **82** focused
cases overlap. `make audit-schema`, secret scan **399 files** and diff checks pass.
The actual candidate image `mana-ai-family:local-v5-notice-20261020` /
`sha256:a934ed41c4aa6b44b53e69acd399afe50c026ee533ac34152bf4aa40aedf4165`
passed the packaged-app/SDK MockTransport smoke with production configuration,
read-only filesystem, no network/capabilities and temporary private SQLite. It
exercised automatic notice delivery, replay and both closed profiles. This is
hermetic candidate acceptance, not real sources/model quality or deployment.

Four **new** separate real-model synthetic diagnostics (not tests or old replays)
used fake families, the currently configured `gpt-5.4-nano`/none effort and local
ledgers. Twelve generations, all known usage; no unknown holds. Conservative
uncached standard-rate estimate **$0.01095125** total, not an invoice:

- `output/family-v5-model-20261020-IpyWoS`: first reply failed format, $0.00058915.
- `output/family-v5-model-fixed-20261020-i3zXiO`: three valid calls; delivery
  refused before generation by exact daily-token admission, $0.00338140.
- `output/family-v5-model-compact-20261020-U2at2P`: four calls/delivered notice,
  but **negative manual review**: visible routing text and unadmitted clarification;
  not a semantic pass, $0.00348515. The new deterministic guard covers this class.
- `output/family-v5-model-notice-20261020-YJcnpl`: new guarded/finding-context
  party, useful analysis; notice withheld as `provider_output_invalid`. Only 144
  output tokens fit and all were used, consuming the exact 2000 chat allowance;
  raw terminal metadata was not saved, so the more precise provider cause is not
  established. No retry/refund, $0.00349555.

Preserve every `receipt.json`, private ledger and negative review; no old party
may be replayed or relabelled as success. Next work is bounded RU/UZ communication
quality and output admission under the **unchanged 2000 raw-token** chat allowance,
or a separately agreed model/budget decision. Do not silently raise quotas or
drop evidence/quality notes to make a diagnostic pass. Full user-requested loop
quality remains unaccepted; keep the goal active. No deployment, real customer
source read/contact, Firebase/GA4 refresh, SSH/key/schedule/OPERATION change.

The root unrelated tracked diff was reverified unchanged before this pointer edit:
`f4b205e5bfe8cc650416eac2f351c39dc60fb74cab460e800c24cf9280427559`.

## Latest conversation checkpoint — `56e880f`

Authoritative branch/worktree stays `feat/mana-family-agents-20261020` at
`/mnt/ssd2/mana-family-agents-20261020`. New detailed acceptance record:
[conversation checkpoint](/mnt/ssd2/mana-family-agents-20261020/docs/mana-family-conversation-checkpoint.md).

Implemented: model text/bool slots with host-only UUID binding; compact JSON with
unchanged facts/quality dates; pre-generation 128/256-token floors within the 2000
chat allowance; explicit signal dates for communicated notices; frozen same-family
RU/UZ/EN hints and neutral/numeric-reply inheritance; no authority from language.
Private context v2 freezes pending questions and recent explicit answers, filters
fresh authorized child aliases, and captures a review-only schema for new parent
reviews. V1/earlier v2 never upgrade; `1bea31c` cannot execute new contexts despite
SQLite remaining v5. Use **new same-candidate closed profiles**, never downgrade.

New default-disabled role profiles are configurable `MANA_PARENT_TOUCH_MODEL=gpt-5.4`
and `MANA_CHILD_SAFETY_MODEL=gpt-5.4-mini`, with a mandatory separate safety budget.
Old OPENAI_MODEL/legacy chat/stateless/audio and actual production settings unchanged.
All ten protective APIs now have execution-through-SDK-MockTransport coverage, not
just HTTP admission; existing validation, proposals-only result and metering pass.

Final `make verify`, session **20380**, actual exit **0**:
`output/family-role-language-acceptance-verify-20261020.log`: **485 backend tests**,
**1 skipped**, **2 opt-in live excluded**, **26 UI tests /11 suites**, format/lint,
mypy **243 files**, TypeScript/build, zero npm vulnerabilities. Schema sync/diff
checks and final secret scan **406 files** pass. Candidate
`mana-ai-family:role-language-local-20261020` /
`sha256:73242e2bc08bfc14ecdeefe5f359e8a7c71922e9f798a47d7d6ee4ba76006f01`
passed the actual packaged-app/SDK smoke without network, writable root filesystem
or capabilities, preserving new history in closed profiles. Not an old-image rollback.

Thirteen **new** independent paid synthetic parties, 79 generations, all known usage:
conservative standard uncached estimate **$0.12265415**. Together with preceding
v5 diagnostics: **91 generations /$0.13360540**. No real family/source reads.
Each original receipt/ledger is retained in ignored `output/`; the detailed record
lists every party, including negative semantics/language, quota stops and a local
harness NameError. None was replayed or relabelled as success.

Qualified real-model evidence: `family-strong-speaker-20261020-ha05QK` completed
both RU/UZ sequences, two explicitly answered needs per family, three completed
chat reviews each, stable replay; chat cost **1922/1843 raw tokens**, safety separate.
`family-explicit-date-20261020-zdI9iy` delivered a dated historical notice within
1567 chat tokens but had a child-directed recommendation in parent chat. The final
prompt clarifies the adult recipient; **that final phrasing is not live-model accepted**.

Next full-objective acceptance: specialist-originated real-model new need -> automatic
Parent-Touch delivery -> exact parent answer -> safety follow-up; handle valid deferral
instead of requiring every normal response to contain a question. Broader RU/UZ
urgent notice while another question awaits, adult-parent address and actual source/
release acceptance remain open. Exact-context pre-generation quota refusals have no
automatic next-day re-admission policy yet; do not add nonce/retry loops. No quota
increase, source refresh/listener, contact, production, SSH/key, UI/audio/OPERATION
change. Keep the original goal active, not complete or silently narrowed.

Root unrelated tracked diff was again preserved exactly:
`f4b205e5bfe8cc650416eac2f351c39dc60fb74cab460e800c24cf9280427559`.
