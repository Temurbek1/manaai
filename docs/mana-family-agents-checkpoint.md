# Parent-Touch / Child-Safety — active application redesign, 2026-10-20

Current local checkpoint: **`1bea31c`**, private schema v5. Both APIs, the event
worker, frozen validated report context, ordinary/urgent Parent-Touch notices and
same-candidate closed profiles are implemented. **Real-model quality remains open**:
four new synthetic parties revealed format/semantic/quota limits; do not call this
a production-ready release or complete the goal. Read the latest v5 section below
and the feature worktree's full checkpoint before continuing. Older zero-spend/
unimplemented statements below describe their historical stages only.

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

## Latest v5 checkpoint — `1bea31c`

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
