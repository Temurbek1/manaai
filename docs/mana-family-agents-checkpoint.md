# Parent-Touch / Child-Safety — active application redesign, 2026-10-20

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

## Continue the entire requested API

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
