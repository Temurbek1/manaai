# Goal history — ongoing local verification, 2026-10-18

This is an **unfinished WIP handoff**, not a completed gate, production candidate,
deployment authorization or closure of the original nine-part workspace goal.

Implementation is isolated in worktree `/mnt/ssd2/mana-goal-archive.NRLmHm`, branch
`feat/operation-goal-archive-20261018`, based on `80746b7`. Its code/tests are not yet
committed or merged into the main operational tree. Detailed evidence and negative
harness receipts are in that worktree's `docs/operation-goal-history-checkpoint.md`.
Keep unrelated application parent-chat changes and credentials out of this work.

## Implemented local scope

An authenticated, same-owner/topic/product GET pages five closed Goal references
through the existing SQL keyset repository, with literal objective search and a
dated cutoff. The collapsed RU/Uzbek Latin archive manually opens complete public
saved artifacts and evidence through the existing renderer, explicitly read-only.
There is no background archive polling, command, source read, model continuation,
new migration/private checkpoint, inherited approval or budget renewal. Older APIs
without availability metadata retain their existing latest-100 preview.

## Actual evidence

- Eight focused API cases passed: 112 records beyond the latest 100, timestamp
  ties, owner/topic/product isolation, literal search, malformed projection refusal
  and observation with model execution disabled. Goal/command/cost state is retained.
- Actual isolated PostgreSQL migration/repository audit: **30 passed**, terminal
  exit **0**, `output/goal-archive-postgres-20261018.log`.
- Actual private fake-browser flow: **85381**, terminal **0**. Search opens the
  exact oldest fixture absent from the latest-100 response. RU/Uzbek Latin,
  1440px/320px, accessibility, reload and unchanged Goal/chat/cost/source table
  fingerprints passed. Screenshots were inspected. Log:
  `output/goal-archive-browser-fixed-20261018.log`.
- Separate source export `/mnt/ssd2/mana-history-browser.ffdivn` passed **232 UI
  tests /31 suites**, production build, Ruff/ESLint, mypy **401 files**, TypeScript,
  schema sync, 28-asset bundle scan and no-Vite checks. That combined command then
  failed because the secret scanner requires Git metadata, absent from an archive
  export. Its negative terminal receipt **84924** is retained in
  `output/goal-archive-ui-export-final-20261018.log`, not relabeled a full pass.
  The unchanged scanner passed separately against the actual Git worktree
  (**674 paths**), and the built export's standalone health/protected pages/CSP
  smoke passed separately. Logs: `output/goal-archive-secret-scan-20261018.log`
  and `output/goal-archive-production-smoke-20261018.log`, both exit **0**.
- The first browser launch used the wrong existing limit-extension environment
  name and stopped before the archive checks. Its failure is retained in
  `output/goal-archive-browser-20261018*`; only the corrected launch is a pass.

Frozen source tree: `0e1511daed84275d1076d235a9e9555b1f5b60c9`. Source/test/schema
patch against `80746b7`, excluding the detailed checkpoint document, SHA-256:
`a50587aba23b9e6ab740f5b42b906020fc2f430d98dc4937a85a47f19771f016`.
The browser used its own dependencies/build/database/session, not the full gate's
generated files or the owner's Chrome session. All three temporary server ports
were closed by their own cleanup. There were no new paid/provider/customer calls.

## Still running — do not restart on a wait timeout

The original full `make verify` remains active, tool session **24994**:
wrapper PID **1001187**, make **1001198**, pytest **1001781**.
`output/goal-archive-verify-20261018.log` is authoritative; require its actual exit
and `MAKE_VERIFY_EXIT_CODE=0` before declaring the checkpoint verified. Formatting,
lint, mypy and TypeScript passed before its backend stage. At 20:51 Samarkand time,
pytest was still progressing with no reported failure; this is not a completed pass.

Next: observe the original process, record its terminal result, review/commit the
isolated increment, then integrate carefully without overwriting overlapping
parent-chat changes in `app/main.py` or generated contracts. Any clean operational
release candidate needs its own actual checks and explicit release scope. Do not
deploy this private-contact-bearing baseline. Existing UI-only release and future
multi-source product-policy questions remain unanswered; the existing single fresh
external read per Goal and all source/schedule settings remain unchanged.

The main tree's unrelated tracked dirty diff remains SHA-256
`f4b205e5bfe8cc650416eac2f351c39dc60fb74cab460e800c24cf9280427559`.
Production, main/audio, parent chat, SSH, keys, real contacts and schedules are untouched.
