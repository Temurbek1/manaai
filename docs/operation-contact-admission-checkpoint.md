# Preparation admission — resumed local checkpoint, 2026-10-17

The owner explicitly resumed the original workspace objective on 2026-10-17:

> Изучи как работают агенты Codex и Claude, нужно реализовать идентичным им функционал на сайте, но связанный с нашим проектом и его данными

The nine acceptance items in [the workspace specification](operation-agent-workspace.md)
remain authoritative. This increment does not replace that objective with rate limiting,
close it, authorize real contacts or release the private contact features. The
[2026-10-16 pause record](operation-contact-admission-pause.md) remains historical
evidence; its interrupted gate is not retroactively a pass.

## Boundary

Preparation admission and recovery run only in the existing default-disabled,
two-fictional-adult Retention lane. Goals remain read-only. The original model,
source grants, unknown model holds, source cooldowns, MANA/360REC separation and
RU/Uzbek Latin presentation contracts remain unchanged.

There are no new Firebase, GA4, Manakids, paid model or real contact requests in this
increment. No production service, key, SSH setting or schedule is changed. The
separately released application parent chat and its private history/key/volume are
outside this work. Last recorded production versions are operational `38cdac4`,
professional UI `faf0a78`, main/audio `e73c10a`, independent scheduler `2ea7b9a`
and isolated parent chat `f2c023f`; this local checkpoint is not a fresh production audit.

## Durable admission and recovery

An owner/topic/turn/request/target-bound SQL claim commits before the fictional
target lookup. Claim completion, resulting action and its audit event commit in one
transaction. Cancelled/lost reads and failed result writes retain a nonexpiring
pending claim. A different nonce, owner, process or later clock cannot redispatch
that unknown target lookup. Recorded exact replay observes SQL even while stopped.

Default ceilings are three preparations per originating turn, ten per owner rolling
hour, one hundred globally per rolling day and four hundred legacy rows inspected.
SQL retains the tightest configured ceilings across processes, including controlled
refusals. Legacy scan overflow or invalid dates fail closed without rewriting old
history. These are fictional preparation ceilings, not live-read, send or model budgets.
Migration `d69ac8eb351f` is additive and refuses downgrade with either table populated.

The browser stores only the exact fixed fictional choice/nonce in strict,
owner/topic/turn-bound session storage before POST. Known typed pre-read refusal is
different from an unknown response. Only explicit SQL observation and another human
confirmation can re-admit the identical known-refused request. Unknown/absent status,
reload or a lost acknowledgement never permits automatic POST. Current owning-agent
status and all three stop scopes remain independently enforced.

The resumed review reproduced one additional defect: an existing unknown preparation
was presented as a new closed refusal if a later global, agent or capability stop,
or owning-agent pause/disable, was observed first. SQL still prevented a second read,
but the refusal classification was misleading. Pending-request observation now
precedes new-admission stop classification. Five regressions failed before the fix
and pass in the focused suite afterwards; saved action replay remains available.

This follows the host-owned, invocation-bound approval/result boundaries in
[Codex App Server](https://developers.openai.com/codex/app-server),
[OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
and [Claude's agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop).
Those references were rechecked on resumption. They do not grant unrestricted tools
or justify a framework/model migration; the existing typed Python/SQL runtime remains.

## Actual engineering evidence

- Focused backend suite: **69 passed**, including all five unknown/stop regressions
  (`output/contact-admission-resume-focused-20261017.log`). The valid pre-fix failure
  is preserved separately in `output/contact-admission-resume-regression-valid-20261017.log`.
- Ruff/format and mypy passed for **403 Python files**. OpenAPI/TypeScript synchronization,
  secret/quality-marker scans and Compose validation passed
  (`output/contact-admission-resume-schema-security-20261017.log`).
- Isolated PostgreSQL: **29 passed**, after empty migration round-trip and drift checks
  (`output/contact-admission-resume-postgres-20261017.log`). This is not real-provider,
  populated-downgrade or production-load acceptance.
- Populated SQLite admission compatibility passed against actual closed `2ea7b9a`,
  current host code and a freshly built local Python 3.12 image, both before and after
  explicit native Goal pause (`output/contact-admission-populated-image-compat-20261017.log`).
  The fixture contains one recorded preparation/action/event and one attempted,
  unknown lookup. Exact table fingerprints survive old-reader/worker observation;
  reconstructed current code reads the action and pending state with zero target
  reads/sends. Existing v15/v14 context, unknown model holds and consumed native v2
  pairing remain checked independently by the same probe.
- Local image `mana-ai-operation:contact-admission-local-20261017`, ID
  `sha256:c24764c40702b92bca297d7231940bf9858e38b45c240602eb558154238a294f`,
  built successfully (`output/contact-admission-resume-image-20261017.log`). It is a
  mixed-worktree diagnostic image, not a clean release candidate or production release.
  It received no configuration/secrets/customer-data mount and was tested networkless.
- A separate index export excludes application parent-chat code and regenerates only
  operational OpenAPI/TypeScript changes. Ruff/mypy passed for its **392 files**;
  the same focused **69 backend cases** passed without a developer `.env`
  (`output/contact-admission-clean-static-20261017.log`,
  `output/contact-admission-clean-focused-final-20261017.log`). The initial export
  collection lacked the explicitly required dummy inference key and failed before
  tests; only the subsequent explicit test-key run is a pass.
- That clean export's full UI format/lint/typecheck, **209 tests / 30 suites**,
  production build and npm audit passed
  (`output/contact-admission-clean-ui-final-20261017.log`). An initial shared
  `node_modules` symlink failed the existing vendored-module identity check; a
  private lockfile-based `npm ci` fixed the harness without changing source/dependencies.
  Python dependency audit found no known vulnerabilities; the private local package
  is explicitly not covered by PyPI auditing (`output/contact-admission-resume-dependencies-20261017.log`).
- Clean image `mana-ai-operation:contact-admission-clean-20261017`, ID
  `sha256:5edf64e993333f0d75da4eb1c76ae5ea74f8ce42d13e76dd80e9794df6bc07a9`,
  also passed the actual old/host/current-image populated-ledger read/pause/reconstruct
  probe (`output/contact-admission-clean-image-compat-20261017.log`). This is narrow
  synthetic candidate-image evidence, not a release, full peer-grant rollback or
  permission to activate the contact features.
- The full clean-export private browser passed with `AUDIT_CONTACT_ADMISSION=true`
  (`output/contact-admission-clean-browser-20261017.log`). Actual fake-backend 423,
  exact-request re-confirmation, lost successful acknowledgement, reload and explicit
  SQL observation produced **one** preparation row. Two personal reviewer logins,
  native result continuation, stop/re-arm, RU/UZ/mobile accessibility, durable stream
  reconnection, scoped Growth sandbox execution, limit extension, complete saved-report
  paging/discovery and 110-turn/105-Goal history regressions also passed. Recovery and
  Uzbek 320px result screenshots were visually inspected under
  `output/contact-admission-clean-browser-20261017/`. Both local server ports closed
  after the successful process exited. This uses a fake model and fake receivers.
  The browser ran after its own completed UI gates using a private `.next`, database
  and browser session, separate from the root suite, avoiding the shared-tree
  build/auth collisions described in the pause record.
- Clean standalone UI health, protected root/runs/analytics placeholders and CSP,
  client bundle secret/settings scan and no-Vite checks passed
  (`output/contact-admission-clean-production-smoke-20261017.log`). This is a local
  production-mode build check, not testing or updating the production website.
- The complete mixed-worktree **`make verify` passed**, and its original final
  process exited **0**: **1435 backend tests**, **209 UI tests / 30 suites**,
  formatting/Ruff/ESLint, mypy **403 files**, TypeScript, production UI build and
  npm audit (**zero vulnerabilities**)
  (`output/contact-admission-resume-verify-final-20261017.log`). The **29 PostgreSQL
  skips** are covered by the separate actual run above; the **two opt-in live tests
  were excluded**, not passed. The backend portion took 28m55s and was not restarted
  while being observed. This root gate includes the separately prepared parent-chat
  files; the narrower clean operational export checks above remain independently
  qualified, not falsely relabeled a full clean-release gate.
  The initial resumed preflight caught a new audit-helper import path in
  mypy before pytest started; it was fixed before the fresh full run. That earlier
  failure log is not a full-gate pass.

Counts overlap and must not be added together. The compatibility fixture does not
populate every contact/grant lifecycle or establish real delivery, business benefit,
semantic model quality, authenticated production-browser acceptance or release rollback.

## Remaining work

The local admission increment is verified. Unrelated parent-chat changes remain
outside its operational source/API contract; they must not be swept into
an operational release. A complete clean-candidate/scoped deployment still requires its own explicit
release scope and rollback evidence; populated private schemas must never be downgraded.

For the broader objective, continue Retention owning-domain/action coverage and
bounded multi-action planning, wider independent model/source quality and practical
end-to-end administrative tasks. Preserve explicit individual billing/consent/channel
authority before real customer actions. A successful fictional push or local test is
not that authority, actual retention improvement or complete Codex/Claude parity.
