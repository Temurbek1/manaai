# Manual Retention action controls — local checkpoint

This advances the Codex/Claude-style workspace objective; it is not a production
release, new scheduled analysis capability, live contact permission or full parity.
Production remains the separately recorded RU/UZ release. All contact feature flags
remain default disabled. No new schema migration, real model/source call, customer action,
production database, SSH, key or schedule change is part of this increment.

## Owning registration and host authority

The actual enabled fictional Retention service publishes one immutable control
definition: `retention-agent / retention.contact.sandbox`, MANA,
`fake_retention_contact`, `human_review_sandbox`. The runtime registers it only
after that service is constructed with its existing effective enablement conditions.
Registration requires a loaded owning agent and rejects collisions with analysis
handlers or another manual definition. It is not a general payload/executor registry.

Manual definitions live outside persisted `AgentDefinition` JSON. They never enter
analysis capability/configuration catalogs, bootstrap jobs, schedules or Goal tools.
Existing private contact history, native invocation/result pairing, v15 Goal state,
review grants and old-task digests are unchanged; historical tasks are not upgraded.
The standard capability kill-switch API now recognizes this loaded manual control.
Disabled/unloaded registration still refuses that key.

The new `workspace/manual-action-controls` GET reads only runtime metadata and the
existing SQL control rows. It does not inspect targets, contact bodies, private
contact tables, source credentials or providers. The scoped PUT requires the admin
role and literal `confirmed: true`, rejects other fields, and delegates to the same
operational kill-switch setter/audit. Existing authentication remains authoritative:
personal cookie writes require CSRF; technical control keys retain the standard
admin-control policy, not peer-review disclosure/send authority.

Workspace routing keeps this surface on the existing operational sidecar when
`OPERATION_CHAT_BASE_URL` is separate. It does not redirect main/audio endpoints,
change the generic proxy or require the main API to load private contact features.

The interaction follows the host-owned request/decision/result boundary in
[Codex App Server approvals](https://learn.chatgpt.com/docs/app-server#approvals).
The domain-specific stop scopes and fake-only limits are MANA policy, not a claim
that Codex implements this exact business action.

## Admission, execution and recovery

New eligible contact chat turns observe the registered manual control and all three
kill scopes before supplying contact tools. Stopped/unregistered contact tools are
omitted; the model receives a dated, minimized host observation so it can explain
the stop. That snapshot is historical on continuation, never a write grant. An
already admitted old turn still replays its original saved result without recapture.

New human preparation checks the stop before reading a fictional recipient. An
existing exact request still returns its saved action while stopped. After a human
decision is durably admitted, stop is checked before the fresh target read, and
again afterwards before dispatch. Stopping therefore blocks new admission; it
does not claim to cancel/refund already in-flight work or settle unknown sends.
Exact receipt reconciliation and SQL observation remain available without resend.
Author self-approval denial and the separate personal peer lane are unchanged.

Re-arming only removes the selected control. It does not approve an intent, share
with a reviewer, renew consent, reset recipient cooldown/unknown holds, enable a
source or perform a send. Global/agent stops are independently visible and remain
effective. Fake acceptance still is not real delivery or measured retention.

## Professional interface

Retention's agent settings show a separate manual-action section, not a runnable
analysis item. It is fetched only when existing server availability advertises the
contact lane. Older/default-disabled production responses do not activate it.
RU/Uzbek Latin labels, exact scoped confirmation and admin-only mutation are retained.
Report/control observation has no polling, provider refresh or automatic write retry.
After a lost acknowledgement, another mutation is blocked until an explicit SQL
status observation; the PUT is never automatically reissued.

## Evidence and remaining work

Focused application tests exercise registration versus scheduler separation, strict
scope/role/confirmation checks, unchanged request replay, restart persistence,
no target read while stopped, sibling independence, generic audit, global defaults,
new model tool exclusion at all three stop scopes and actual cookie/CSRF denial.
UI tests exercise disabled/older-server gating, confirmation, a global stop remaining
in force, lost-ack observation and Uzbek observer-only presentation. Sources/models
are fake; these checks do not establish real-model quality or live-source readiness.

Remaining acceptance includes bounded durable proposal admission, complete owning
domain activation/status semantics and planning across action families, real individual
billing/consent/channel authority, measured outcomes, broader real-model/source
quality, and separately authorized candidate-image/release/rollback acceptance.
Only the already established closed `2ea7b9a` fallback with native execution disabled
is eligible for old-history compatibility; no populated database may be downgraded
or restored over newer history. Overall workspace completion remains unproven.

One remaining chat UX limitation is confirmed in the current code: the earlier
preparation card uses a generic unconfirmed-response banner even for the new known
HTTP 423 stop. It blocks another POST, but has no typed stopped/admission state or
explicit same-request human re-admission after re-arming. The durable-admission
increment must distinguish this known refusal from an unknown outcome without
automatically retrying either; reloading must never bypass a pending SQL reservation.

Measured focused receipts: 70 related backend tests passed, then 9 final new control
cases passed with cookie/CSRF and registry checks; these overlap, not additive new
coverage. Thirteen focused UI cases passed, and static checks passed for 386 Python
files plus TypeScript/ESLint. Logs: `output/manual-action-controls-focused-final.log`,
`output/manual-action-controls-final-cases.log`, `output/manual-action-controls-ui-fixed.log`
and `output/manual-action-controls-static-final.log`.

The actual full private fake browser passed with manual stop/re-arm, personal
cookie/CSRF mutations, Uzbek 320px layout and accessibility, then the native
contact/result, two-login review, source/Goal/cost/continuation/history regressions.
The stopped Uzbek professional screenshot was visually inspected. Log:
`output/manual-action-controls-browser-fixed.log`; screenshots:
`output/manual-action-controls-browser-fixed/`. This is not paid-model semantic
quality, real receiver or authenticated production-browser acceptance.

The actual networkless closed `2ea7b9a` read/pause/reconstruction audit passed with
v15/v14 history and consumed native contact v2 continuation
(`output/manual-action-controls-compat.log`). No current candidate image was used;
this does not establish complete populated-contact/grant rollback or production
release acceptance. OpenAPI/client sync, secret/quality scans and Compose passed
(`output/manual-action-controls-schema-security.log`).

The isolated PostgreSQL migration round-trip/drift audit and existing 28 lifecycle/
concurrency cases passed (`output/manual-action-controls-postgres.log`). These are
the existing SQL/contact/peer cases, not a new PostgreSQL HTTP-control race or
production-load acceptance. There is no new migration in this increment.

The original complete `make verify` process exited successfully without restart:
**1353 backend tests**, **197 UI tests / 29 suites**, Ruff/format/ESLint,
mypy **386 files**, TypeScript, production build and npm audit (**zero
vulnerabilities**) passed (`output/manual-action-controls-verify.log`). The
28 PostgreSQL cases skipped in that SQLite suite are separately covered above;
two opt-in live cases were excluded, not passed. The final standalone health,
protected root/runs/analytics and CSP checks, client-bundle scan and no-Vite check
also passed (`output/manual-action-controls-smoke.log`). The generated Next type
references returned to their committed production paths. No development-only
generated-file change is included.

The earlier failed browser attempt
selected an ambiguous confirmation control behind the open modal. The harness now
targets the visible open dialog, without force-clicking or bypassing confirmation.
Initial focused failures also caught a wrong existing runner status expectation,
a malformed test HTTP-body helper, and missing required synthetic topic title/type
annotations. Those failed logs remain separate evidence, not passing acceptance.
