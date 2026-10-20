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
- Detailed contracts and full remaining acceptance:
  [family-agent implementation document](/mnt/ssd2/mana-family-agents-20261020/docs/mana-family-agents.md).

Implemented and verified locally: two family-role definitions; one-speaker policy;
durable priority/coalescing question queue; one active question per parent;
explicit answer/child/parent bindings; atomic admission and question publication
with accounting; retained unknown holds; fresh own-child checks before question
inference; structured single-question model replies with strict raw usage;
preserved old message digests, history and quotas. This is a service/store/model
core, **not yet the full public API, event worker or Child-Safety execution**.

Full `make verify`: original session **71187**, actual exit **0** and log marker
`MAKE_VERIFY_EXIT_CODE=0`: **364 backend tests**, **1 skipped**, **2 opt-in live
tests excluded**, **26 UI tests /11 suites**, formatting/lint, mypy **217 files**,
TypeScript/build, zero npm vulnerabilities. Related focused suite **82 passed**;
counts overlap, not additive. Tests use fakes/actual SDK MockTransport only.
Logs: ignored `output/family-agent-core-verify-20261020.log`,
`output/family-agent-parent-touch-final-20261020.log`,
`output/family-agent-schema-20261020.log`, and secret scan log.
Generated/public API contracts are deliberately unchanged until the HTTP layer
is actually implemented. No new live model/child/Firebase/GA4 call was made.

The local family SQLite v2 upgrade is additive and preserves old family history;
the unchanged deployed v1 reader **refuses it**. That is fail-closed evidence,
not a working rollback. Do not deploy this checkpoint, downgrade its populated
tables or restore an old database over newer history.

## Continue the entire requested API

1. Wire Parent-Touch runtime/authenticated GET/POST and invisible reply metadata
   into the same existing chat, including proactive delivery without fake user text.
2. Add durable producer admission, terminal/nonce-independent intent filtering,
   transactional event outbox and new-data/new-parent-message deduplication.
3. Implement capability-specific Child-Safety routes around the existing ten
   protective contracts and validation pipeline, with fresh ownership and dated
   family-chat context. Child-Safety must never write directly into the chat.
4. Implement the explicitly separate server budget, strict model receipts,
   worker/restart recovery and bounded input/context admission. Do not silently
   assign an unlimited budget or activate provider refresh/listeners.
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
