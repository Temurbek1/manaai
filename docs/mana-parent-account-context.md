# Current account tariff in Parent-Touch — local, 2026-10-25

Parent-Touch can now answer a parent's own current-tariff questions using the
existing ownership-filtered MANA Parent List response: display name, selected
record's paid flag, expiration, source payment date and lifetime agent-trial flag.
No new chat, public endpoint, billing request, source schedule or model generation
is introduced. The existing **2000 raw speaker tokens per parent/day** and
**2000 global Child-Safety tokens/day** remain enforced; the extra context itself
still consumes input tokens within those limits.

The profile adapter collects these optional fields from the **same bounded
Parent List GET** it already makes for child ownership. This is not a claim that
the complete reviewed conversation makes only one GET: safety and speaker still
perform their existing fresh ownership checks. No additional account API GET is
added by this feature. Exact replay and history/status observation do not reread
sources or infer again.

## Scope and uncertainty

`ParentTariffContext` is a minimized internal value, not an application-supplied
write grant. It carries `scope=selected_current_tariff_record` and a collection
instant shared exactly with its parent profile. Only the matching parent's fresh
profile reaches Parent-Touch; mismatched collection or data over 180 seconds old
is omitted. The existing exact parent/child coverage checks run before billing
projection. No phone, avatar, other family, referral code, raw provider record or
unconfirmed `created_at` meaning is passed through this projection.

Strict bool/null and explicitly zoned dates are required. Missing, numeric,
naive, malformed or future-payment metadata omits the optional tariff while valid
child ownership remains usable. It never turns unknown into false, unpaid into
proof of eligibility, or a selected record into every active entitlement.
`payment_date` is not a bank receipt or confirmed free-period start;
`agent_trial_used` is not a referral counter, consent or new grant authority.
No auto-renewal, payment path, feature entitlement, refund or discount is inferred.

Parent-Touch presents the exact facts in the parent's language, using a readable
expiry and UTC offset. The app showing this record is the basis; internal SQL
terminology and invented app menus/payment links are not useful user guidance.
The owning conversion/action policies still independently govern all writes.
This is not proactive subscription-expiry outreach or completed upgrade eligibility.

New profile tariff fields are excluded from both ordinary and native Child-Safety
prompts. Child-Safety is told to leave account questions to Parent-Touch rather
than invent a child information need when billing data is absent. The ordinary
bounded chat history may naturally contain earlier account discussions; those
remain historical prose, never fresh billing evidence or child-risk signals.
The separate proactive Retention prompt is not given new account targeting authority.

## Test chat and engineering evidence

Run `make chat-lab-profile`. It uses an explicitly fictional paid profile and
existing single-chat SQL/API/worker path. Try:

- `Какой у меня тариф и когда заканчивается?`
- `Mening tarifim qachongacha amal qiladi?`

`chat-lab-profile-live` is a separate explicitly paid-model directory; its profile,
children, catalog and offers remain fictional, with no live source/push/grant
adapter. A different mode cannot take over an existing marked directory. Do not
reset a paid party's quota/history or use synthetic time with a real model.

Twelve fake/MockTransport cases cover strict true/false/null facts, the unchanged
one-login/one-profile-read contract, minimized fields, malformed optional metadata,
ordinary/native specialist exclusion, replay, stale/mismatched collection and a
moving-clock integration. No automated test contacts a real provider.

The first real-clock browser exposed a fixture defect: profile and nested tariff
used two separate clock calls, so their collection instants differed by microseconds.
The actual API adapter already captured one shared instant. The lab now does the
same, and the moving-clock test guards the defect. The original two generic
simulation answers/screenshots are retained, not rewritten into successful quotes.
New explicit fake requests after that fix do not replay earlier model work.

## Limited real evidence, including qualifications

One separately admitted actual test-parent **4** party in
`output/parent-tariff-real-profile-20261025` completed the existing **review-first
v10** source -> Child-Safety -> Parent-Touch path. It used real current Parent List
profiles and real GPT-5.4 / GPT-5.4-mini, not a simulated family. Exactly seven HTTP
attempts completed: login + two existing ownership GETs, two model counts and two
generations. No extra account GET, native source tool, Firebase/GA4, push, grant,
payment, transaction or production change occurred.

The response preserved the actual `1-Month` paid record and exact November-23 expiry,
and treated automatic charging as unknown. It had a **presentation qualification**:
raw ISO/microseconds/internal record wording and an unverified subscriptions/payments
menu suggestion. Guidance was subsequently corrected; this original response is
not a postfix real-family UX acceptance. No source/model request was repeated.

The diagnostic harness itself raised `AttributeError` while inspecting history
after the answer had already completed. Its original result is retained. A
separate **SQL-only** reconciliation with refusing source/model ports verified
the original completed replay, two history messages, no active child question,
**1184 speaker /1213 safety tokens** and **zero holds**. Reconciliation made zero
provider calls. Standard uncached generation estimate: **$0.005441**, not an
invoice or proof of count-endpoint billing.

A separate new **synthetic UZ ordinary Parent-Touch presentation** case in
`output/parent-tariff-uz-presentation-20261025` tested the corrected wording and
explicitly unknown paid/renewal state. The actual GPT-5.4 response used readable
23 November /16:00 /UTC+05:00, preserved unknowns and invented no app screen or
renewal/payment promise. **772 input +99 output tokens**, zero holds, one model
generation/two HTTP attempts. Replay kept its single synthetic profile read and
original response. Uncached estimate: **$0.003415**. This case has no real family
source, Child-Safety inference or native-tools acceptance and does not replace
the original qualified real-parent party.

The internal optional profile contract is not persisted as new chat/source JSON;
family/source schemas remain **16/4**. There is no migration, automatic historical
recapture or action/protocol upgrade. Current tests and closed-reader/browser
evidence below do not establish all-parent throughput, broad RU/UZ quality,
full-agent completion or production readiness. The original full goal stays active.

## Final local checks

Final `make verify`, session **18364**, exited **0**: **1282 backend cases**, one
skip/two live opt-ins excluded; **26 admin cases /11 suites**, **10 lab-controller
cases**, mypy **379 files**, formatting/lint/types/build and npm **zero findings**.
API/TypeScript synchronization, marker scan and secret scan (**1161 files**) pass.
The twelve new context cases are included in that total, not an extra model study.

One full intermediate gate exposed the older collection lab test calling a
composite SQL projection directly while its worker was committing. The existing
HTTP contract correctly returns typed `409 lab_state_busy`; the test now observes
through GET and explicitly exercises one such busy response before convergence.
It retries only observation, never collection/source/model POSTs, and still checks
one acquisition/publication. The initial annotation and line-length gate failures
remain in their logs; only the final terminal gate above is the completed pass.

Owned 390px Chromium verified corrected RU/UZ tariff replies, reload and retained
history across the fixture server restart. The original four messages remain;
two subsequent explicit requests produced correct replies, for **eight messages**,
**600 simulated speaker /600 safety tokens**, zero holds and no page overflow or
browser error. The corrected screenshot was visually inspected. Browser and owned
port 8097 servers are closed. These are simulated replies, distinct from the two
actual-model cases described above.

Actual previous image `mana-ai-family:upsell-v16-20261025-local` / `658b61059504`
read a consistent copy of this new v16 history with its **closed** reader under
no network/read-only root: all eight messages, 600 speaker tokens, zero holds and
every table fingerprint were retained. This proves scoped closed-history
compatibility, not new-feature execution, a fresh candidate image or production
release/rollback acceptance. No populated database was downgraded or restored.

Next full-goal work remains real referral integration when its contract arrives,
source-driven commercial eligibility/expiry outreach, wider child-data coverage,
fleet budget/capacity, broader independent quality and a separately scoped release.
