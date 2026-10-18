# Saved Goal evidence viewer — local checkpoint, 2026-10-18

This advances truthful cited output and practical source inspection under the full
[workspace objective](operation-agent-workspace.md). It is not a deployment,
source activation, contact grant or completed broad agent/model-quality acceptance.
The UI-only production-release question remains unanswered.

## Clean scope and observed problem

Worktree `/mnt/ssd2/mana-ui-controls.KbB3wt` is now on
`release/ui-current-goal-evidence-20261018`, based on verified local UI commit
`54612a2` → `c198132d` → released `faf0a78`. Those earlier branches, commits,
images and receipts remain intact. No private contact/backend or parent-chat code,
production `.env`, real user data or key is imported. Backend, schemas, dependencies,
Docker/Compose and production configuration compare unchanged with `54612a2`.

The separate new real-model synthetic parent-journey diagnostic produced a complete
analysis with `[label](report:id)` citations. The UI deliberately treated all model
links as plain text and showed only report IDs in the Goal history. The Goal API
already returns the exact scoped saved evidence; no provider read is needed to
inspect that same snapshot. A UI regression reproduced the missing source control
before this increment; its failed receipt is retained, not relabeled a pass.

## Read-only interaction

- Only exact `report:id` references whose IDs are in the current Goal's own evidence
  and whose host supplied an observation callback become inline source buttons.
  Unknown IDs, external/relative/javascript URLs, HTML and code-literal citations
  stay escaped plain text. No model URL becomes navigation, a provider call or action.
- Activating a known reference opens the existing history and exact source details,
  transfers focus to its summary and scrolls it into view. Sources can also be
  expanded manually; no new top-level controls or explanatory blocks are introduced.
- The source view shows **only the returned snapshot**, preserving exact whitespace,
  dates, shortening status, limitations and complete returned tail. A shortened
  projection is explicitly marked, never described as the entire original source.
  Reading a full report text does not establish currentness or population coverage.
- Text is rendered escaped in a keyboard-focusable, named scroll region with bounded
  viewport height and wrapping. RU/Uzbek Latin labels are provided; evidence itself
  is never translated or treated as instructions. No fetch/POST/source grant is
  issued by the source-viewing handler. Existing server authentication, topic/product
  scope, cost holds, cooldowns, source approvals and schedules are unchanged.

Runtime changes are `GoalReport.tsx`, `GoalWorkspace.tsx`, styles and the language
catalog. Two component test files and two existing fake/browser harness files are
the other initial changes. The initial eight-source-file increment against
`54612a2`, before this documentation or the artifact fixture below, was SHA-256
`945faadb4279723368833467967e89a1dad61aa53cc277252b906da809fba570`.
Frozen staged tree: `dcca12bb89288683c5e463315e82e732d605c53a`.

While the unchanged backend portion of the full gate was running, the component
test was extended with one minimized **synthetic** real-model artifact fixture.
It contains only the complete answer and two public saved-evidence projections,
never provider windows, review receipts, owner/session/Goal IDs, keys or customer
records. Fixture `admin-ui/src/test/fixtures/native-parent-journey.json` is SHA-256
`8c9c4d0e36789be2240ec00a741f82c1951b2362943da434f9e67cc682f1671f`.
The resulting exact nine-source/test/fixture patch, excluding this document, is
`50813ae5850bd4419952f762a339ab10da667be8e07a2bc7d7bdc37841ea7418`.
Runtime code did not change after the first full gate started. This fixture/test
addition was made before that gate's UI test/build stages, not relabeled as covered
by its earlier format/type preflight; those checks were run separately again.

## Checks so far

- The before-fix focused browser-component regression failed because the source
  button did not exist. Log: `output/goal-evidence-viewer-before-20261018.log`.
- After the fix, **30 related cases** passed; the expanded source/security/language
  group passed **39 cases**. The full clean UI suite passed **195 tests /26 suites**.
  Counts overlap and are not additive. Exact whitespace/tail, focus/reopen, unknown
  source refusal, escaping, no new fetch/POST, partial-text qualification and RU/UZ
  are covered. Logs: `output/goal-evidence-viewer-focused-*-20261018.log` and
  `output/goal-evidence-viewer-ui-all-20261018.log` in the root workspace.
- The complete 10811-character real-model synthetic answer renders its three
  calculation tables, both bound citations, noncausal/unknown-outcome qualifications
  and exact final clause. Activating both citations shows their original complete
  saved text and footer without a new source/control request. That component file
  passed **27 cases**; the subsequent full UI run passed **196 tests /26 suites**.
  This is artifact rendering, not repeating the paid party, HTTP/source admission,
  real MANA evidence or browser acceptance. Logs:
  `output/goal-evidence-viewer-real-artifact-20261018.log` and
  `output/goal-evidence-viewer-ui-artifact-all-20261018.log`.
- Ruff/format, mypy **350 Python files**, ESLint/TypeScript and generated API sync
  passed with explicit clean-candidate `PYTHONPATH`. An initial formatting preflight
  refused the new browser-fake lines; it was fixed, not bypassed. Log:
  `output/goal-evidence-viewer-static-schema-fixed-20261018.log`.
  Fresh `make lint typecheck audit-schema` also passed after the artifact test;
  log: `output/goal-evidence-viewer-artifact-static-schema-20261018.log`.
- `AUDIT_SAVED_SOURCE_VIEWER=true` is an audit-only shell flag, not application
  configuration. It requires the native workspace and catalog browser audits;
  the invalid combination refused with expected exit **2** before server/browser
  startup. Bash syntax passed. Its new actual source/citation/focus/RU/UZ/mobile/
  reload/accessibility block has **not run yet**.
  All eight JavaScript bodies in the new block parsed successfully
  (`output/goal-evidence-viewer-browser-js-20261018.log`).

The independently built local image
`manaai-admin-nextjs:goal-evidence-viewer-candidate-20261018`, ID
`sha256:b7923dedd809b8e83ef3e1d9aacf5e7e37bfbad11f66eeae61efa3506e0889e2`
(209619513 bytes), passed its actual non-root UID 1001, networkless/read-only-root
smoke with only a private 32 MiB `/tmp` tmpfs. Liveness, protected root/runs/analytics
placeholders, CSP and all four exact released `operation-chat:8000`/`api:8000`
rewrites passed. Its **27** client text assets contain the new source-viewing UI,
with no detected credentials/server-only settings or private contact code; there
is no `.env` file. Logs: `output/goal-evidence-viewer-image-{build,smoke}-20261018.log`.
This isolated build used no host data/config mount or host ports and made no
backend/provider request. It is not authenticated production/proxy or browser
acceptance; the full gate and browser below still remain prerequisites.

## Final gate, actual browser and remaining release acceptance

The original full **`make verify` passed**: session **29810** returned **0**, and
`output/goal-evidence-viewer-verify-20261018.log` ends `MAKE_VERIFY_EXIT_CODE=0`.
It passed **1241 backend tests**, **196 UI tests /26 suites**, Ruff/format/ESLint,
mypy **350 Python files**, TypeScript, production UI build and npm audit (**zero
vulnerabilities**). Backend runtime was **44m53s**. **Twenty-three PostgreSQL cases
were skipped and two opt-in live cases excluded**, not passed or rerun here.
Wrapper PID **906128**, make PID **906176** and pytest PID **906467** are terminal;
do not restart them. The exact nine-file source/test patch above remained unchanged.
The separate parent-journey diagnostic's 1410/218 full pass uses another clean
worktree/database/dependency tree and does not replace this UI candidate's gate.

The actual serial fake browser run, original session **89897**, returned **0**
with `BROWSER_EXIT_CODE=0` in `output/goal-evidence-viewer-browser-20261018.log`.
Native current-Goal, catalog, source-viewer, continuation, projection/review,
streaming and limit-extension audit flags were explicit; all sources/model are fake.
Source controls opened the exact complete SQL text, transferred focus, preserved
RU/UZ and 320px accessibility, and reload retained Goal/revision/steps/fake cost
without a source grant or new work. Existing handoff, stream/reconnection, full
catalog/report paging, Growth sandbox, lost-acknowledgement, limit-extension,
110-turn/105-Goal, owner-isolation and CSRF browser flows also passed.

Visual review caught a harness-only problem: its first "desktop" source screenshot
inherited the catalog flow's 320px viewport. That first pass is not desktop visual
acceptance. The audit now explicitly restores 1440×1000 before the source interaction
and uses an actual citation activation again after switching to mobile/Uzbek.
That fresh full run, session **99519**, also returned **0**; corrected desktop and
mobile screenshots were inspected under
`output/goal-evidence-viewer-browser-fixed-20261018/`.

The mobile source is a nested keyboard-scrollable text region inside the transcript;
its full end is not all simultaneously on screen. An additional audit-only check
scrolls that same source to its final text and asserts the footer's actual Range
rectangle is inside the transcript and above the composer. The subsequent full
browser run, session **66929**, returned **0**, with `BROWSER_EXIT_CODE=0` in
`output/goal-evidence-viewer-browser-footer-20261018.log`. Its actual
`saved-source-footer-uz-mobile.png` was inspected: `EXACT CATALOG FOOTER` is visible,
without horizontal overflow. This proves reachable saved text, not real source
freshness, full-population coverage or business/model-quality acceptance.

Only audit Bash changed after the completed full gate: viewport/click/geometry and
footer-observation checks, not runtime code, Python, tests, APIs or schemas. The
full gate's nine-file patch hash above still identifies its exact source stage;
it is not retroactively changed. The final nine-file patch, excluding this doc, is
`2ecc46f76ad90af912bd767baf61ef08bc3aafcfea75ea5405d6b155fd34e1cf`.
The independently built runtime image remains applicable because those Bash
changes are outside its `admin-ui` build context and application source is unchanged.
All browser sessions closed their local servers; ports 18080/15173 have no listeners.

Browser-generated `next-env.d.ts` dev imports were restored to the production-type
baseline. Final lint/typecheck/schema and production build/bundle/standalone checks
passed, original session **69404** returned **0**. Logs:
`output/goal-evidence-viewer-final-{static-schema,build,smoke}-20261018.log`.
Mypy checked **350 files**, generated API contracts are unchanged, **27** client text
assets passed the credential/server-setting scan, and no-Vite checks passed.
Standalone liveness, protected root/runs/analytics placeholders and CSP passed;
smoke port 13188 closed. Secret/quality-marker checks passed (**594** Git-listed/
unignored paths). Bash syntax passed after both audit-only follow-ups. No generated
type change or private venv symlink enters the commit. The earlier `54612a2`
image/gate receipts do not replace this increment's independent checks.

This completes the stated local UI engineering increment, not the overall objective.
Deployment still needs separate approval, a fresh compatible config/
service/Goal/unknown-hold fence, retained image/config backup, UI-only canary and
rollback verification. No database restore/downgrade, backend/Goals worker restart,
real source/contact request, paid inference, main/audio, parent chat, SSH/key or
schedule mutation is included. Keep the broader goal active.

## Root integration — verified local checkpoint

The clean UI increment is local commit
`032a0eda996abf10d5283fa5598361eefab338d6`, on verified `54612a2`/`c198132d` and
released `faf0a78`. It was selected into the main local operational branch as
`80746b7`, after the independently verified parent-journey diagnostic `d8e2ebf`.
The unrelated dirty root delta retained exact SHA-256
`f4b205e5bfe8cc650416eac2f351c39dc60fb74cab460e800c24cf9280427559`
before and after the pick. Parent-chat source, configuration, dirty API contracts
and keys were not included. No Git push or production change occurred.

The combined committed operational-only export is
`/mnt/ssd2/mana-evidence-integrated.iacTAS`, source tree
`f236801f536602f25027814e2a0d5e694987e9c2` before this documentation update.
It excludes `.env` and all unrelated application-parent-chat changes and uses its
own lockfile-installed UI dependencies with explicit clean `PYTHONPATH`.
Its original final **`make verify` passed**, session **36578** returned **0**;
`output/goal-evidence-integrated-verify-20261018.log` ends `MAKE_VERIFY_EXIT_CODE=0`.
It passed **1410 backend tests**, **224 UI tests /30 suites**, Ruff/format/ESLint,
mypy **400 Python files**, TypeScript, production UI build and npm audit (**zero
vulnerabilities**). Backend runtime was **31m27s**. **Thirty PostgreSQL cases were
skipped and two live cases excluded**, not passed or rerun here. Wrapper PID
**958214**, make PID **958276** and pytest PID **958789** are terminal. The earlier
independent gates still cover their own exact source versions, not this combined run.

The actual integrated browser, session **8293**, returned **0** with
`BROWSER_EXIT_CODE=0` in `output/goal-evidence-integrated-browser-20261018.log`.
It explicitly enabled only local fake audit lanes: two personal fake OTP/cookie
identities, two separately prepared/reviewed fictional contacts, native result/next-
decision/final loop, manual stop/re-arm, durable preparation refusal/reconfirmation,
lost acknowledgement and SQL-only recovery. Source-viewing, native current Goal,
catalog/paging, review, 110-turn/105-Goal context, stream/reconnection, sandbox Growth,
limits, owner isolation, CSRF and accessibility also passed together. The new desktop
source, 320px Uzbek reachable footer and final fictional contact result screenshots
were visually inspected. No real model/source/contact call occurred in this browser.

After both local servers closed, the generated dev-type imports were restored.
Final `make lint typecheck audit-schema`, production build, standalone liveness,
protected root/runs/analytics placeholders, CSP, **28**-asset bundle/settings scan
and no-Vite checks passed; original session **22656** returned **0**. Logs:
`output/goal-evidence-integrated-final-{static-schema,build,smoke}-20261018.log`.
Ports 18080/15173/13189 have no listeners. Root secret/quality-marker scans passed
(**683** Git-listed/unignored paths at that stage). No integrated private-contact UI
image was substituted for the independently verified clean production-baseline image.

The read-only Goal archive is a subsequent separate WIP branch; its new API/UI is
not covered by, merged into or deployed from this checkpoint. A documentation-only
correction records the existing runtime's opt-in manual source allowlist and single
external-read ceiling; no source permission or read limit was changed. Two public
read-only production health GETs returned `status=ok` during this work; that is
liveness only, not authenticated production/new-UI or provider acceptance.

This main branch contains undeployed private contact code and must not replace the
clean UI-only release branch/image. Production scope/authority is unchanged; full
workspace acceptance and explicit UI rollout approval remain open.
