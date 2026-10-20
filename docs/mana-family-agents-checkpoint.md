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

The local family SQLite **v3** upgrade is additive and preserves old family history;
older v1/v2 readers **refuse it**. That is fail-closed evidence,
not a working rollback. Do not deploy this checkpoint, downgrade its populated
tables or restore an old database over newer history.

## Continue the entire requested API

1. Add the transactional event outbox and new-data/new-parent-message deduplication
   to the now-atomic chat lifecycle. Assistant messages, GETs and replays must not
   recursively trigger analysis. Freeze a bounded same-parent chat cutoff.
2. Add automatic communication delivery and a separate urgent-notice policy without
   bypassing Parent-Touch, question ordering, ownership or its token allowance.
   Producer admission and terminal/nonce-independent filtering are now implemented.
3. Implement capability-specific Child-Safety routes around the existing ten
   protective contracts and validation pipeline, with fresh ownership and dated
   family-chat context. Child-Safety must never write directly into the chat.
4. Implement the explicitly separate server budget, strict model receipts,
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
