# Tariff enquiries without a guessed currency — local checkpoint, 2026-10-26

A parent can ask for tariff options without naming a currency. Newly captured
enquiries preserve the exact parent quote, objective, duration and explicit total
budget, then publish one host-owned currency question through Parent-Touch in the
existing parent question slot. Parent-Touch remains the only speaker. No tariff,
payment, free grant, push permission or new mobile operation is created.

This is a step toward the full AI KOMANDA goal, not complete proactive conversion,
Basic/Premium feature recommendations, referral rewards or production activation.
The last confirmed production family release remains `f8d095e` / schema 6.

## Flow and authority

`MANA_CLIENT_UPSELL_CURRENCY_ENABLED=false` is the default; enabling it requires
the existing governed Parent-Touch manager and Upsell runtime. Only new admitted
turns capture private protocol `catalog-currency-v2`. Existing turns keep
`catalog-enquiry-v1`, its non-null currency schema and original replay. Enabling
the flag never upgrades an old queued turn or recaptures its terms.

The manager delegates pricing to the tariff owner even when currency is missing.
The new strict model reply can choose `currency=null`, but cannot create question
IDs, select family members or execute anything. The host validates the exact
parent quote, existing manager handoff, current priority and bounded queue before
atomically saving the assistant question, shared slot and frozen enquiry. Verified
raw input/output usage is accounted before those checks. Failed publication keeps
an unknown hold, not a free retry.

The phone sends an ordinary message containing `UZS` or `USD` and the exact active
`reply_to_question_id`. The host binds that same-parent answer once, preserves the
original language/terms, and queues the existing Upsell workflow without another
model call. Explicit unlabelled numeric budgets retain their number times 100
minor units; the chosen currency binds that amount. No currency conversion occurs.
Other replies follow normal conversation rather than silently completing or
resurrecting the commercial enquiry. A new nonce cannot answer a consumed question.

Before pricing, the existing service still obtains fresh same-parent ownership and
uses the shared bounded catalogue/cache. Its six-hour cooldown, four catalogue
admissions per rolling day and durable unknown-read refusal remain unchanged.
An exact replay only observes saved history. No source read occurs while asking
or accepting the currency. The answer/quote use the original frozen language.
Parent-Touch's 2000 raw tokens per parent/day and the separate 2000 global Safety
allowance are unchanged. Deterministic host text has zero model usage.

Urgent Safety and existing communication priorities remain authoritative. The
currency question expires after one day. Deactivation refuses newly completed
answers and cancels unsubmitted resolved enquiries; in-flight source receipts
remain recorded, while their price publication is fenced. Neither deactivation,
restart nor midnight clears unknown model/source holds.

## Persistence and compatibility

Family schema **31** adds private immutable admission/origin tables and a bounded
parent/status lookup. Existing chat/quota/manager/source rows and legacy JSON are
not rewritten. Source and collection schemas do not change. Use the current
closed v31 reader to retain history and holds while execution is disabled. An
older reader's refusal is not a functional rollback; never downgrade or restore
an older database over newer history.

## Verification

Sixteen focused cases currently exercise RU/UZ/EN terms, exact and concurrent replay,
foreign/expired answers, SDK old/new schemas and verified costs, prior v30 pending
upgrade without capture, atomic publication loss, current closed-reader/midnight
holds, late priority/deactivation, disabled queued work, unknown catalogue restart
and actual runtime construction/deactivation without idle external HTTP.

Full gates, browser, model and packaged acceptance are recorded below.
All labs use fictional providers/contact preferences and are not business-outcome
or real-source acceptance. Earlier failed logs remain evidence, not passing checks.

The nullable required field follows the official
[Structured Outputs contract](https://developers.openai.com/api/docs/guides/structured-outputs#all-fields-must-be-required).
This does not replace host validation or the strict raw terminal usage boundary.

Run the isolated fake web scenario with:

```sh
make chat-lab-upsell-currency CHAT_LAB_PORT=8107
```

Open `http://127.0.0.1:8107`, ask for tariffs without a currency, and answer the
single question with a currency code. This is not a production URL or real offer.

### Actual local acceptance

Final `make verify` exited **0**, log
`output/upsell-currency-verify-four-languages-final-20261026.log`: **1646 backend tests**,
one skipped/two opt-in live excluded, **26 admin tests/11 suites**, **15 lab
checks**, mypy **453 files**, lint/format/types/build and zero npm vulnerabilities.
Sixteen focused cases pass, including RU, Uzbek Latin/Cyrillic and English questions. The first full invocation lacked the explicit dummy
OpenAI environment key and failed during collection; its log is retained. The
subsequent pre-language-fix full gate passed too, but does not prove the later
admission correction. Sequential schema synchronization is unchanged.

Two initial real-model synthetic dialogues technically completed the owning flow:
four generations/eight OpenAI HTTP attempts, known uncached estimate **$0.00869**.
The Russian case used **1271 parent raw tokens**. The Uzbek case used **1270**, but
its host question/acknowledgement/quote incorrectly used the seeded Russian fallback.
Its original receipts and negative manual review remain in
`output/upsell-currency-model-20261026/`; technical completion is not a language pass.

The correction reuses the existing tariff-domain language helper when freezing
new v31 manager admissions, matching the already captured Upsell language. It
changes no historical admission/reference, consent or source/action authority.
A **new independent** Uzbek six-month/budget-350000 dialogue then passed through
an Uzbek currency question, UZS answer and dated 180-day/299000-UZS fictional quote:
two generations/four HTTP attempts, **1282 parent raw tokens**, zero Safety tokens,
zero unknown holds, known uncached estimate **$0.0043925**. The short answer and
quote required no additional model call; exact original/answer replay made no I/O.
Artifacts: `output/upsell-currency-language-model-20261026/`.

Combined: **six generations/twelve HTTP attempts/$0.0130825 estimated**, not an
invoice. Rates were checked against the official GPT-5.4 model page; these are
small independent synthetic cases, not arbitrary-language, live-catalogue,
business, fleet or broad model-quality acceptance. No old paid case was rerun.

Actual browser -> HTTP -> SQL -> rendered chat passed the fictional three-month
scenario with **five messages/300 simulated parent tokens/zero Safety tokens**.
History refresh did not change full state; a same-file server restart preserved
all cells in **71 family and 15 source tables** and the complete response state.
The 390px screenshot was inspected: no page errors or horizontal overflow.
Browser automation is closed; the fake lab remains on loopback **8107**.
Artifacts: `output/upsell-currency-browser-20261026/`.

### Packaged and migration acceptance

Application **`965bddd`** was exported into the external clean source directory
`/mnt/ssd2/mana-upsell-currency-source-965bddd`. The minimal image
`mana-ai-family:upsell-currency-local-20261026`, ID
`sha256:ae8942d448620cbe98fdee7ef5f7b2c1d4c5a800b4776fdcaeb9a85244e545b1`,
matches all **284 application Python hashes**. No `.env` or private SQLite is
copied. Python 3.12 probes run with no network/capabilities, user 1000 and a
read-only root filesystem; only temporary/private artifact mounts are writable.

The actual packaged application completes the fictional tariff question/answer/
quote with 300 simulated parent tokens and no Safety usage. A separate cancelled
model submission retains its **612-token unknown hold**, and a fictional lost
catalogue receipt stays blocked. Current closed-reader initialization, restart
and midnight preserve all cells in 71 family/15 source tables; no work is
redispatched. A prior actual v30 image refuses the v31 history without changing
cells/version. This is not functional execution rollback to the old image.

The same current image/factory upgrades the **already retained** private production
copy from v6 to v31, preserving every original column/cell in 16 tables, both
messages and exact old-request replay. Anonymous history 401, live/history/
directory/replay 200 and absent lab cards 404 pass. No new historical admission,
source/model/contact/grant call or production access/copy occurs. Its current
closed reader preserves the same history. A first harness run carried the old
literal application label `205d140`; preserve that metadata review and original
artifacts. The corrected probe runs in a separate directory and reports the
actual `965bddd`; no application change was needed. This small private copy is
not fleet coverage, a production release or restored old-database rollback.

Artifacts: `output/upsell-currency-candidate-20261026/`, including the original and
corrected production probes, image attestation and old-reader refusal. The full
AI KOMANDA objective remains open; commercial entitlements/approved offers,
referral integration, broader telemetry/measurement semantics and scoped release
still need their owning evidence. This increment does not activate production,
Firebase/GA4 refresh, SSH/key changes or new schedules.
