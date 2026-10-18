# Explicit current-data Goals — local checkpoint, 2026-10-18

This advances items 1, 2 and 7 of the unchanged [workspace objective](operation-agent-workspace.md):
an explicit administrative Goal must use the available agent tools, not silently
enter the older analysis path. It does not complete the overall objective or
authorize production/source/contact activation. No backend or API change is needed.

## Reproduced defect

With both availability endpoints advertising the native workspace, ordinary agent
messages created native Goals, and explicit `saved_snapshot` Goals also selected
`execution_mode=agent`. But the UI omitted that field for explicit current-data
Goals. The backend's established default is `analysis`, so those requests entered
the older path, which does not admit the native-only first-party read capabilities.
The UI also treated current scope as ready despite a native availability mismatch
or chat-availability error. This was a mode/readiness inconsistency, not a bypass
of backend authentication, cost controls or source approval.

A valid new UI regression failed on the missing execution mode. A subsequent
four-case diagnostic produced **three failures and one passing legacy case**:
the native current request was downgraded, both mismatch/error cases remained
incorrectly ready, and a genuinely legacy deployment still worked. These negative
logs remain under `output/explicit-native-goal-*-before-20261018.log` in the root
workspace; they are not overwritten by the corrected pass.

## Local correction and unchanged authority

- For a new explicit Goal, an available native workspace now supplies its existing
  `execution_mode=agent` and the exact selected `analysis_scope`, including `current`.
  The objective, language constraints, model/reasoning and original limits are unchanged.
- If either endpoint advertises native execution, mismatch/unavailability refuses
  the current-data submission. The draft remains, and **Retry check** only observes
  availability; a later explicit submission is still required.
- If neither endpoint advertises native execution, existing explicit legacy Goals
  remain available. `saved_snapshot` never falls back to current/legacy analysis.
- Existing saved Goals still receive only their existing control/steering request.
  No historical execution mode, checkpoint, objective, cost hold or source grant
  is upgraded. There is no new feature flag, migration or private protocol.
- Native tools retain server-side product/capability checks and separate human
  confirmation for fresh source reads. This correction enables neither contact
  code nor automatic Firebase/GA4 reads, schedules, budgets or writes. Russian and
  Uzbek presentation logic is unchanged; no interface text was added.

## Evidence and pending gate

- Worktree: `/mnt/ssd2/mana-explicit-goals.yWx2Nv`.
- Branch: `feat/operation-explicit-native-goals-20261018`, based on `b58dade`.
  Runtime changes only `ChatPage.tsx`. Its component tests and a deterministic
  existing backend concurrency fixture are separate test-only changes. The later
  optional browser-harness increment below adds no application configuration flag.
- Focused corrected diagnostic: **4 passed**; no fetch POST during failed preflight
  or availability retry, followed by exactly one explicitly submitted native Goal.
  The separate legacy case still omits native fields.
- Full UI suite: **217 passed /30 suites**, including the existing historical-scope,
  steering, language, stop, contact and pagination cases. Format, Ruff, ESLint,
  TypeScript and mypy **396 files** passed. No real source or paid inference was used.
- Logs: `output/explicit-native-goal-regression-after-20261018.log`,
  `output/explicit-native-goal-static-20261018.log` and
  `output/explicit-native-goal-ui-20261018.log` in the root workspace.
- A separate HTTP → SQL admission diagnostic passed in actual local image
  `mana-ai-operation:contact-tool-loop-clean-20261017`, networkless, with dummy
  configuration and the Goal worker disabled. A personally authenticated POST
  received 202 and persisted the exact native/current objective. Exact replay
  retained one Goal, another logged-in owner received 404, and no source grant,
  model attempt, target read or dispatch occurred. Original session `44482`
  exited **0**; log: `output/explicit-native-goal-api-sql-20261018.log`, synthetic
  data: `/mnt/ssd2/mga.TYj8DX`. This uses ASGI transport, not a browser, ingress,
  actual production image/configuration or completed analytical task.

The first full branch gate, original session `88324`, exposed one existing backend
test failure. After that failure was visible, the verified owned pytest PID `634338`
was deliberately interrupted to get its traceback: **1 failed /222 passed /2
deselected**, KeyboardInterrupt and wrapper exit **2**, not a passing gate.
Log: `output/explicit-native-goal-verify-20261018.log`. That process and wrapper
PID `634054` are terminal; never wait for or restart their handles.

The fixture assumed `asyncio.gather` response 0 was the final model result. Read-only
inspection of its original failed database confirmed the child actually completed
with `sample_uz`, the native result and three settled mock receipts. A duplicate
request may legally observe the admitted `thinking` child before the owning model
request returns. A new event-barrier reproduction forces that exact ordering and
failed at the original assertion, without a backend change. Its corrected test
requires the observer's truthful `thinking`/no-proposal snapshot, the writer's
completed snapshot, identical child IDs and the unchanged single-inference,
restart, cost, two-action and final-no-third-action assertions. The entire focused
module then passed **21 cases**. No retry, policy relaxation or product fix was made.
That test-only correction is isolated in local commit `86934a4`; the UI correction
and its browser regression remain a separate commit/release-selection unit.

Evidence: `output/explicit-native-goal-failed-loop-sql-20261018.log`,
`output/explicit-native-goal-loop-order-before-20261018.log` and
`output/explicit-native-goal-loop-order-after-20261018.log`. Those fixture/model
histories are synthetic; no old paid diagnostic or production call was resumed.
The root audit's separately completed original gate remains **1402 backend /214
UI passed**, recorded in local commit `5245706`, not a claim that its unforced
concurrency test exercised every ordering. Neither negative gate is relabeled a pass.

A fresh full branch **`make verify` passed** after the deterministic fixture
correction: original session `6101` returned **0**, and
`output/explicit-native-goal-verify-fixed-20261018.log` ends with durable
`MAKE_VERIFY_EXIT_CODE=0`. It passed **1394 backend tests**, **217 UI tests /30
suites**, Ruff/format/ESLint, mypy **396 Python files**, TypeScript, production UI
build and npm audit (**zero vulnerabilities**). Backend runtime was **30m40s**.
**30 PostgreSQL cases were skipped** and **two opt-in live cases excluded**, not
passed or rerun here; no application SQL/runtime contract changed. The original
wrapper PID `648057` and pytest PID `648342` are terminal; do not restart them.
The three-file runtime/test patch against `b58dade`, excluding this document, is
SHA-256 `cf20bfca03f83b0cb2c5ef9f40b9fda471ea086c836a1dd2653b6e4140859b2a`.
Its source remains separate from the completed root audit; retain the original
failure log instead of overwriting it with a new pass.

The optional `AUDIT_EXPLICIT_NATIVE_GOALS=true` block in the existing browser
harness was added while the unchanged backend/unit-test portion of this gate was
running. The three-file hash above remains exact. The four-file patch including
that shell harness, excluding this document, is
`1b423b1928e00a9cd5664af551375cbfe371c2a6c63d3a3c8a75511888461fd9`;
the harness itself is SHA-256
`aa437769492a80a5789a0b4db22968db1fd998bbfce94fd201a50ca488803574`.
It uses a fresh private topic and observes one exact native/current Goal POST,
its saved inspect/report/question tools and unchanged Goal/revision/steps/fake
cost after mobile/reload. It neither records session headers nor approves a source.
The fixture stops at an unanswered synthetic question, not a completed analysis.

Before execution, Bash syntax and **57** static JavaScript evaluation bodies
parsed successfully; fresh `make lint typecheck` passed with
mypy **396 files**. Its invalid native-off invocation refused with expected exit
**2** before starting servers/browser work. Logs:
`output/explicit-native-goal-browser-{guard,js,static}-20261018.log`.
Those checks were preparation, not browser acceptance.

The subsequent actual private browser **passed**, original session `14172` exited
**0**, after the completed full gate. Log:
`output/explicit-native-goal-browser-20261018.log`; screenshots:
`output/explicit-native-goal-browser-20261018/`. The new block confirmed exactly
one explicit native/current admission and no ordinary chat-message POST, the exact
objective and saved inspect/report/question tools, then unchanged Goal ID/revision/
steps/accounted fake cost after mobile/reload. There was no requested/approved
source or source-read attempt. The fixture intentionally ends at its unanswered
synthetic question; this is not completed analytical/model-quality acceptance.
The existing native handoff/stream/reconnection, historical scope, full saved-page/
catalog, limit-extension, Growth sandbox/receipt, 110-turn/105-Goal, owner-isolation,
CSRF and accessibility cases also passed. RU/UZ and 320px UI coverage remain.

The explicit-current desktop and 320px screenshots were visually inspected: the
objective, truthful waiting state, focused question and single composer remain
readable without horizontal overflow. Its result is explicitly labeled synthetic.
The browser closed both local servers; ports 18080/15173 have no listeners.
Its generated `next-env.d.ts` dev-type imports were restored to the original
production-type baseline, not included in the patch. No paid inference, real
source/customer data, actual Google Chrome account or real contacts were used.

Final `make lint typecheck audit-schema` passed after that restoration, including
unchanged generated OpenAPI/TypeScript contracts. The standalone production UI
passed liveness, protected root/runs/analytics placeholders and CSP; **28** client
text assets passed the credential/server-setting scan, and no-Vite checks passed.
Local smoke port 13186 also closed. Secret/quality-marker checks passed (**662**
Git-listed/unignored paths; the private venv link is excluded from the commit).
Logs: `output/explicit-native-goal-final-static-schema-20261018.log` and
`output/explicit-native-goal-production-smoke-20261018.log`. These are local checks,
not authenticated production/proxy/rollback acceptance or a new Docker image.
The four-file patch hash above is unchanged after all gates/browser checks.

This completes the stated local engineering increment, not the full workspace
objective or a production release. Do not substitute this contact-bearing UI
worktree for the separate UI-only candidate `c198132d`. That candidate and
the root peer-loop audit have their own immutable source/gate receipts.
The root audit's completed `make verify` does not include this UI fix; session
`88692` is terminal and its frozen export must not be edited or restarted.

No production service, main/audio, application parent chat, key, SSH setting,
external source or schedule was changed. Wider owning-domain/model/source quality
and separately approved release remain open under the full original goal.
