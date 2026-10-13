# Active operational release — 2026-10-13: confirmed Goal continuation

This scoped release supersedes the API/UI versions in
[the manual analytics release](operation-manual-analytics-release.md), not its
source findings or remaining acceptance gaps. The owner approved release after
verification. Only the operational sidecar, its single in-process Goals worker
and administrator UI were replaced. Unfinished local inference-diagnostics code
was excluded by building a clean Git archive of the tested commit.

## Versions and activation

- API/Goals worker: `mana-ai-operation:0d27000`, image
  `77fd0d1472c9c3ff310a875bacf3ce6cf476e986666bc47212a92c705079904a`.
- UI: `mana-ai-admin:0d27000`, image
  `e2f2974e33d1f337eb0284a55cc930c22d5ad7e6242053778042ce6334d10dec`.
- Application revision: `0d270008b217f3d2978e34621f93c6f0226c7aa7`.
- `OPERATION_GOAL_LIMIT_EXTENSIONS_ENABLED=true` in this sidecar only;
  extension ceilings: 120 total steps and 500000 microusd ($0.50) for the
  entire Goal. Initial creation remains limited to twelve steps. Increasing
  limits requires an exact owner-confirmed command; no automatic replenishment.

Newly tracked native Goals use private checkpoint v10. Existing histories are
not rewritten or retroactively assigned cost certainty. The original objective,
constraints, scope, model continuation, usage, consumed reads and recovery caps
survive a grant. Unknown model holds block further generation and continuation.
See [the contract](operation-goal-limit-extensions.md).

## Protected state and backup

Main API/audio `e73c10a`, scheduler `2ea7b9a` and PostgreSQL retained their exact
container IDs, start times, configuration and mounts. All 23 original protected
configuration/environment/credential/SSH/Nginx files matched their saved hashes.
SQL capability configurations, controls, schedules and source gates matched
their pre-release fingerprints; schema remains `a36d9f7b802c`.

No live Firebase/GA4 read, listener, auto-refresh, source permission, cooldown
reset, new schedule, SSH authentication change or database migration/restore
was performed. The operational sidecar scheduler remains disabled.

Protected backup: `/var/backups/mana-ai/goal-limits-0d27000/`, root-only,
including the existing configurations, container inventory and a verified custom
PostgreSQL dump (1646486 bytes), SHA256
`df0d4f03fec63664af4c928cf8e1c84d3aa2fa97c6520ad78cdfb2f11d449e77`.
The dump was listed for validation, never restored over production.
Release kit: `/opt/manaai-releases/0d27000/kit/`.

Admission/worker execution were disabled in the staged new sidecar after checking
zero queued/running Goals, leases, active chat turns and source runs. The compatible
UI and API were then activated together. Existing waiting Goals were not resumed.

## Evidence and outstanding acceptance

The exact code checkpoint passed `make verify`: 901 backend / 135 UI tests,
lint/format, mypy, TypeScript, production build and dependency audit
(npm zero vulnerabilities). Separately: 17 isolated PostgreSQL cases and the
native browser regression, including mobile confirmation, lost command receipt
without redispatch and same-Goal reload. These tests use fake providers.
The released Git archive also passed a fresh complete `make verify` with its own
UI dependency installation and a placeholder OpenAI key: 901 backend / 135 UI,
mypy 316 tracked source files and zero npm vulnerabilities. No developer `.env`
or unfinished diagnostics was included. The preliminary clean-copy checks found
setup-only issues (a shared dependency symlink and absent required test key);
isolating dependencies and supplying the fake key resolved them without code changes.

On the server, the actual deployed API image and actual `2ea7b9a` fallback passed
a networkless synthetic-database compatibility audit before/after explicit pause:
private v10 grants, unknown holds, consumed reads and complete context are retained.
No production database was mounted in that audit.

Both changed containers are healthy. Authenticated deployed API availability
advertises continuation with the exact configured ceilings. The public frontend
renders the normal protected login without browser errors; main API health still
reports audio moderation ready. A real authenticated browser click-through of the
new form remains outstanding: the private browser had no login, and the existing
Chrome discovery endpoint returned 404. No production session was fabricated.

### Real model: continuation passed, completed review did not

Goal `cd91c5e9-07fd-4959-ba4b-15ed51498e66`, topic
`7e280ee6-c399-4a5a-97c5-f2f7663f229a`, used the existing registered administrator
and normal technical-key authentication through the public frontend proxy.
It read only saved report `f1df00b3-eb6c-40f9-a221-0459198c9d18`.

After three `gpt-6.1-sol` decisions it stopped before independent review with
`limit_stop=steps`, no unsettled usage, and known accounted estimate $0.058609.
The full report, original request, constraints and dated evidence remained saved.
The exact owner-approved command increased the total limit from three to six
steps; the budget stayed $0.45. One durable grant, request
`bd8b86f1-f960-41dd-88e5-9d33d4502542`, continued the **same** Goal in review.

The initial SSH transport expired before authentication, so that attempt never
reached the application. Before dispatching the confirmation, the existing
exclusive server marker was checked: no extension had been dispatched. No
uncertain application command was reissued, and no second Goal was created.

The fourth model step did not produce a usable usage receipt/validated result.
The Goal is **waiting**, not completed: known estimate remains $0.058609,
unknown hold **$0.157238**, conservative accounted total **$0.215847**. Unknown
usage is not a confirmed invoice or free call. The grant and original request
remain intact; automatic retry, resume and additional extension are blocked.
No source read/approval or customer/provider action occurred.

Thus deployed SQL/API continuation and unknown-cost fencing passed, but terminal
real-model review/quality acceptance remains **failed/open**. The existing generic
error did not retain the original provider cause; do not guess it from health,
catalog access or later diagnostics, and do not repeat the lost inference.
The ordinary protected frontend and independent audio service remain healthy.
Final SQL inspection found one unknown global receipt, zero executing Goals,
chat turns/source runs and zero live leases; the exact source/configuration/
schedule/schema fingerprints remained unchanged. Allowlisted runtime-log inspection
provided no model HTTP status for the failed review, so its cause remains unknown.

The separate local eight-case quality party stopped after its first inference
lost a usable receipt. Known priced usage: zero; **unknown reserved cost $0.09612**,
not proof of zero expenditure. No remaining case, source read or retry ran.
That failure is not presented as fixed by this release; unfinished diagnostics
and broader model-quality acceptance remain separate work.

Ignored release evidence: `output/goal-limit-release-20261013/`.

## Application-only fallback

After any v10 Goal exists, **do not use `38292de` as a native executor fallback**.
The verified fallback is `2ea7b9a` with Goals/workspace/worker execution disabled,
paired with the recorded pre-native UI `a871ddf`. The release kit contains exact
image overrides, not permission to roll back without checking active work.

Follow [stop/drain/inspect/pause](operation-agent-workspace-release.md), preserve
schema, unknown holds, private metadata, source gates and consumed grants. Never
restore the backup over current history or downgrade a populated workspace.
Rolling forward does not automatically resume paused tasks.

This is one operational checkpoint, not complete Codex/Claude feature parity,
full-population telemetry, confirmed business improvement, GA4 publication, or
implementation of unbuilt Retention/Orchestrator/Technical action families.
