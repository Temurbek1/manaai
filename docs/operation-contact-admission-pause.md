# Paused workspace goal — 2026-10-16

The owner explicitly requested pausing, not completing, the original objective:

> Изучи как работают агенты Codex и Claude, нужно реализовать идентичным им функционал на сайте, но связанный с нашим проектом и его данными

Historical pause boundary: no new feature work or deployment should continue until the owner returns to this
goal. This is an **unfinished WIP handoff**, not a verified release checkpoint or
full Codex/Claude parity. Existing negative/qualified model receipts remain intact.

The owner explicitly returned to this goal on 2026-10-17. Continue from the
[resumed checkpoint](operation-contact-admission-checkpoint.md); this document
retains the original paused state and interrupted-test evidence below. Resumption
does not authorize contact production deployment or real customer sends.

## Authoritative state at pause

- Workspace: `/mnt/ssd2/Projects/manaai`, branch `feat/operation-admin-20260929`.
- Base HEAD: `2c82973bc80af7a878eda548f23dc6082190a786`, already pushed.
- Preparation-admission changes remain uncommitted and have not been deployed.
  Preserve all tracked/untracked changes; do not reset, clean or replace this tree.
- The preceding, separately approved **UI-only** production release is `faf0a78`;
  operational API/Goals worker remains `38cdac4`, schema `a36d9f7b802c`, main/audio
  `e73c10a`, independent scheduler `2ea7b9a`. See the professional UI release record.
- Contact flags remain default disabled. Private migrations `b47ea6c9130d`,
  `c58fb7da240e` and new WIP `d69ac8eb351f` are not deployed. This pause adds no
  source read/refresh, model call, real contact, SSH/key change or production mutation.

## WIP implementation, not final acceptance

The new private preparation SQL gate commits a request/target-bound pending claim
before the fictional target read. Creating the resulting action/event and marking
that claim recorded share one SQL transaction. Unknown/cancelled/failed reads and
failed result writes leave a nonexpiring hold; another nonce cannot redispatch them.
Exact recorded requests observe SQL even while stopped. Legacy JSON/history is not
rewritten, and Goals tools stay read-only.

New configuration ceilings are 3 preparations per turn, 10 per owner rolling hour,
100 globally per rolling day, and a 400-row explicit legacy scan ceiling. SQL retains
the tightest configured ceilings, including after refusal; another process cannot
silently loosen them. These are fake preparation counts, not live source/LLM/send
budgets. Bounded legacy history must not be treated as a complete prefix on overflow.

The owning agent's enabled status now participates in admission/execution and new
tool selection. The UI persists only the original fixed fictional choice/nonce in
owner/topic/turn-scoped session storage before POST. Typed known refusal is distinct
from unknown response; only a fresh SQL observation plus another explicit human
confirmation can re-admit a known refusal with the identical request. Unknown/absent
observations never authorize another POST. The observation API maps the original
nonce through the unchanged native v2/legacy binding and returns minimized SQL state.
Storage denial and older missing admission metadata refuse preparation. RU/UZ remain.

Relevant files include `domain/contact_admission.py`,
`application/retention/preparation_errors.py`, `infrastructure/persistence/contact_admission.py`,
the contact service/store/HTTP bridge, migration `d69ac8eb351f`,
`admin-ui/src/features/chat/contactPreparationAttempt.ts`, `RetentionContactActions.tsx`,
the API client, schemas, configuration and related tests. Paths above the UI are
under `app/mana_operation_ai/` unless stated otherwise.

## Actual checks before pause

- Focused related backend cases: **38 passed** (`output/contact-admission-focused.log`).
- PostgreSQL: **29 passed**, including a new isolated-schema two-connection ceiling
  race; empty migration round-trip/drift checks passed
  (`output/contact-admission-postgres.log`). This is not a live executor/load test.
- Earlier full UI pass: **201 passed**, before the latest strict recovery-helper tests.
  The later focused helper/contact suite passed **19** cases; counts overlap and
  are not additive (`output/contact-admission-ui-all.log`,
  `output/contact-admission-recovery-tests.log`). The final full UI suite is not verified.
- Ruff, `make lint`, mypy (391 files) and TypeScript passed at their recorded stages.
  The latest helper type guards and browser harness still require the final checks.
- Two fresh synthetic SQLite migration probes refused downgrade with a populated
  policy gate or pending claim and retained their rows/version
  (`output/contact-admission-migration-guard-actual.log`). An initial empty-path
  harness invocation failed safely and is retained separately, not a pass.
- Actual closed `2ea7b9a` networkless existing v15/v14/contact-continuation compatibility
  and pause/reconstruction audit passed (`output/contact-admission-compat.log`).
  **It did not populate the new admission ledger.** Full populated-admission and
  candidate-image/release/rollback acceptance remain open.

The only full `make verify` process (tool session `81483`, pytest PID `709947`)
was deliberately stopped by SIGINT for this owner-requested pause. It reached
**318 passed /2 deselected**, then exited 2 with KeyboardInterrupt; the parent make
also terminated. This is **not a passing full gate**, a product test failure or
permission to claim all remaining tests passed. No browser run was active at pause.
Log: `output/contact-admission-verify.log`. Do not wait for or restart this terminal
handle automatically while the goal is paused.

## Resume only when requested

1. Inspect current Git/process state and this handoff; keep the original nine-item
   acceptance scope in `docs/operation-agent-workspace.md`. Do not close the goal
   from these narrow fake/preparation results.
2. Review the WIP, regenerate/check API sync if needed and run final static gates.
   Use a short SSD `TMPDIR` and explicit repository `PYTHONPATH`; host `/tmp` quota
   previously caused harness failures. Do not load/copy secrets into fixtures/images.
3. Rerun the interrupted full `make verify` deliberately, using fakes. The former
   handle is terminal. Run the browser **serially after** that suite to avoid SQLite
   auth contention and conflicting `.next` dev/build directories.
4. The new opt-in `AUDIT_CONTACT_ADMISSION=true` block in `scripts/browser_e2e.sh`
   is **not yet run**. It tests an actual fake-backend 423, exact-request human
   re-confirmation, a lost successful preparation acknowledgement, reload and SQL-only
   recovery before the established personal peer-review/native-result flow. Review it
   before running; do not weaken actual confirmation/CSRF checks to make it pass.
5. Add/verify populated new-ledger old-reader/candidate-image compatibility and any
   missing policy/unknown-state cases. Do not downgrade populated private tables or
   restore an old DB over newer history. No contact production release is authorized.
6. Update evidence honestly, then commit a completed local increment only after the
   appropriate checks. Broader model/source/action/real consent/channel/outcome and
   production-human-browser acceptance remain separate open obligations.

An additional recovery snapshot is stored under
`output/contact-admission-pause-20261016/`: base revision, Git status, tracked binary
patch and explicitly selected untracked source/doc files. It excludes `.env`,
credentials and production data. The actual working tree remains the primary source.
