# Parent-Touch as the single-chat manager — local checkpoint, 2026-10-25

Parent-Touch can now handle ordinary conversation independently of Child-Safety's
global token balance. On a newly admitted message it makes one compact, metered
decision: reply to a greeting/general application question, or hand that same
pending message to the existing child, tariff or reminder workflow. It remains
the only parent-facing speaker. The router adds no acknowledgement message,
second chat, mobile agent picker or new public endpoint. The existing catalog
workflow still publishes its preparation acknowledgement and then the exact quote.

This is a **local, default-disabled implementation**, not a production release.
`MANA_PARENT_TOUCH_MANAGER_ENABLED=false` is the default. Enabling it requires the
existing complete native family/Retention-expiry runtime and an available worker;
it does not enable missing providers, source refresh, contacts or another budget.
The last recorded production family release remains `f8d095e` with review-first
admission. Do not call this checkpoint full fleet or agent-system readiness.

## Flow and ownership

The application keeps the same three operations: message POST, message-status
GET and single-history GET. Only new eligible admissions capture manager v21.
Historical reviewed turns never upgrade when the flag changes. Replies bound to
an existing specialist question and priority safety work retain review-first
handling rather than passing through a new classifier.

The initial decision offers exactly three strict, zero-argument native functions:

- `request_child_safety_review`: child safety/health/parenting, behaviour, location
  and child-data analysis belong to Child-Safety.
- `request_tariff_help`: current account facts or an explicit price/duration
  enquiry use the existing scoped account/Upsell path.
- `request_reminder_help`: an explicit reminder request uses the existing draft
  and separate exact-parent-confirmation lifecycle.

Only one handoff is admitted for that root turn. The model cannot supply another
parent/child ID, arbitrary SQL, URL, credentials or provider payload. A handoff
does not itself read Firebase, grant access, activate a tariff or schedule a
reminder. Native accompanying prose is not published. Invalid/multiple/unavailable
calls retain verified usage and dispatch nothing. Parent-Touch's ordinary reply
is statement-only; it cannot invent an unbound follow-up question.

For a child handoff the original frozen review context enters the existing
Child-Safety event/job lane exactly once. The original message remains pending,
without a synthetic reply. After the specialist receipt, Parent-Touch receives
all existing profile, guidance, evidence and date qualifications, the admitted
question/notice bindings, and a publication-only schema. Reminder/Upsell schemas
and callable handoffs are absent from this final generation. No evidence or user
word is shortened to make it fit; existing hard context/quota checks still refuse
an input that is too large.

Tariff and reminder handoffs make a second Parent-Touch generation under the same
root, using only the selected typed scope, without a Child-Safety job. Exact prices
still come from the owning catalog adapter and a reminder remains a draft until
the parent confirms it. Unknown eligibility, checkout or renewal stays unknown.
Mixed requests currently select one owner, not an unlimited multi-agent loop.

The initial model receives the exact message and bounded historical conversation,
but no child telemetry/profile or control authority. The host still performs the
existing fresh ownership-filtered profile read before inference. Specialist/final
preparation independently rechecks ownership; this change does not eliminate
those existing API reads or promise that model classification is infallible.

## Costs, stop fences and continuity

All initial/final Parent-Touch raw input plus output tokens count against the
same **2000 tokens per parent/day**. The final response usage aggregates the
manager and publication calls without charging either twice. Child-Safety retains
its separate **2000 tokens globally/day**. A greeting/catalog enquiry can proceed
with the safety pool exhausted; child analysis still cannot bypass that pool.

Initial usage commits before validating/dispatching a handoff. The continuation
uses the remainder of the original quota day and preserves other durable holds;
midnight does not create an extra allowance for an old root. Unknown submitted
calls retain their reservations and are never repeated by a new nonce, GET,
restart or replay. Known late usage is reconciled after a stop, but its decision
cannot publish or dispatch work. Model/configuration changes, disabled capture,
new priority work and expired preparation also fence decisions.

Private family schema **21** adds `parent_touch_manager_turns`: original root/
parent, frozen language/model binding/context, selected target/call and the first
raw receipt. It does not put native calls in legacy public history or change the
source/collection schemas. The current closed v21 reader preserves all state.
Actual previous v20 refuses v21 without changing rows; refusal is **not a working
execution rollback**. Never downgrade a populated file or restore an old database
over new history.

When this manager is enabled, an unsolicited expiry reminder also waits until
the parent's existing conversation-idle interval has passed (default ten minutes).
After waiting it still needs independently fresh existing profile facts; this
does not grant a refresh. Other expiry consent, quiet-hours, safety priority,
deduplication and contact rules remain unchanged.

## Practical checks

`make chat-lab-manager` runs this profile at loopback in its own
`data/chat-lab/manager-simulation` directory. Try a greeting, a 90-day price
enquiry, a child question and a reminder through the ordinary composer. The model
is explicitly simulated; real routes, application services and SQLite run.
No Firebase/GA4, external push, grant or payment adapter is attached to that lab.

The focused manager/SDK/legacy/runtime set passed **79 cases** after the
publication-scope fix; a subsequent owning-scope regression and all **17** manager
lifecycle cases also pass. It covers the same pending child message, one-speaker
history, budget independence, reminders remaining unconfirmed, replay/concurrent
workers, bound-question legacy admission, stop/model/priority fences, idle expiry
and unknown/late receipts across restart/day changes. SDK MockTransport verifies
the actual pinned OpenAI 2.53.0 count/generation contract, strict zero-argument
tools and usage-before-native/text validation. Pytest makes no real model calls.

Owning-scope checks also run at the SQL publication boundary: a selected child
reply cannot create a reminder/Upsell intent, a tariff reply cannot draft a reminder,
and an ordinary/helper reply cannot introduce specialist question/notice IDs.
The negative regression preserves the priced invalid result and creates no draft.
Its first fixture used a UTC offset contrary to the typed reminder timezone and
therefore produced an unknown fake call; the corrected valid-offset fixture is
the passing scope check, not a rewrite of that initial diagnostic.

The first independent actual-model party correctly selected Child-Safety and
completed its review, but the legacy all-capability final prompt exceeded the
remaining parent allowance. A separate fictional Uzbek greeting completed with
zero safety jobs. Preserve this negative party at
`output/parent-manager-model-20261025`; it was not replayed or relabelled a pass.
Its first cost summary omitted the separately stored manager receipt; the
append-only `usage-audit.json` corrects the estimate to **$0.003459**, with **782
speaker /867 safety** raw tokens and no unknown holds. Seven HTTP attempts,
three generations; the refused final generation was never submitted.

After limiting the final publication schema/instructions to the selected owner,
a **new** Uzbek fictional party completed route -> Child-Safety -> same-chat reply:
**1322 Parent-Touch /925 Child-Safety** tokens, six HTTP attempts, three generations,
zero unknown holds, exact replay and no duplicate response. The initial count was
401; final publication count 785, with all original context retained. Saved
receipt: `output/parent-manager-model-scoped-20261025`. Its concise Uzbek answer
relayed the bedtime advice without claiming live phone measurements. A small
comparative preference in the final wording was not directly established by the
specialist; this is qualified single-case evidence, not broad semantic quality.

The second party's conservative standard uncached generation estimate is
**$0.00618625**; combined known estimate **$0.00964525**, not an invoice or proof of
token-count endpoint billing. Existing GPT-5.4 / GPT-5.4-mini roles were preserved.
Rates were checked against the official [GPT-5.4 documentation](https://developers.openai.com/api/docs/models/gpt-5.4)
and [GPT-5.4-mini documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
Native/schema conventions follow official [function calling](https://developers.openai.com/api/docs/guides/function-calling)
and [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
Neither paid party accessed a real family, source, contact, grant or production.

The network-disabled candidate probe upgrades the actual earlier v20 fixture,
preserving every original table fingerprint, **150 known /1850 unknown safety
tokens** and no historical manager capture. A separate new tariff root retains
**150 known manager tokens /1850 unknown second-call hold** through the current
closed reader. The actual old v20 image refuses both resulting v21 files unchanged.
These are compatibility/closure checks, not exercised production rollback.

An owned 390px Chromium session exercised greeting -> real application tariff
workflow -> Uzbek child question -> bound answer -> unconfirmed reminder, using
fake providers/models through actual HTTP routes. All **11 messages /6 SQL turns**,
four manager captures, two safety jobs, **1200 simulated speaker /300 safety**
tokens, question resolution and the reminder draft survived an actual server
restart. Every family/source table fingerprint remained unchanged. An exact old
POST replay returned its original turn/usage and changed no table; navigation
admitted no work. There was no horizontal overflow or JavaScript console error.
The first reminder wait searched for a nonexistent “Confirm” button and timed out;
the actual composer-based confirmation state and saved draft were then verified.
No reminder was confirmed, push queued or tariff granted. Artifacts are in
`output/parent-manager-browser-20261025`. This checks mechanics, not model quality.

## Final engineering checkpoint

Final `make verify`, original session **36983**, exited **0**:
**1456 backend tests**, one skipped/two opt-in live cases excluded, **26 admin
tests /11 suites** and **10 lab controller tests**. Ruff/format/ESLint, mypy
**411 source files**, TypeScript, production UI build and npm audit with **zero
vulnerabilities** passed. The source/schema synchronization check passed without
an API artifact change. Final log: `output/parent-manager-verify-final-20261025.log`.

Candidate `mana-ai-family:parent-manager-v21-final-20261025-local`, image
`sha256:4422280bffcaaa51ce5e0cf0332251db46815318b7a5d6bdf3d348e2f3f3dda4`,
passed the networkless upgrade/unknown-hold/closed-reader probe after the final
owning-scope fence. All **13 changed application Python files** match host hashes;
`.env` is absent. Fixture production configuration explicitly disables unrelated
Telegram login; no real keys or family data are mounted. The previous actual v20
image `a652d0ed9e02…` refuses both final v21 fixtures with unchanged fingerprints.
This is a packaged engineering check, not complete production configuration or
a working execution rollback.

Secret and quality-marker scans passed. The ordinary `make audit-security`
Compose step first lacked required database variables; the explicit dummy-variable
attempt then correctly refused the worktree's absent `.env`. Neither failure is
called a passing full security target. Actual Compose structural validation then
passed with explicit dummy values and `--no-env-resolution`, without reading or
creating a production environment file or starting a container. Diff checks pass.
Only the owned browser and loopback server were stopped; production, SSH/keys,
source schedules/limits, audio and customer tariffs were untouched.

## Remaining full objective

This does not finish GPS ownership/measurement semantics, verified screen-time
periods, referral/reward contracts, autonomous paid-offer eligibility, renewal or
whole-fleet capacity under the global safety allowance. The four administrative
owners and their remaining actions, broader model/channel/source acceptance and
separately scoped compatible production rollout remain open in
[the complete active plan](mana-autonomous-agents-plan.md).
