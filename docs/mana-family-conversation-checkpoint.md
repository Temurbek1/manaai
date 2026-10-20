# Family conversation checkpoint — 2026-10-20

Subsequent evidence and explicit deferred delivery:
[specialist checkpoint](mana-family-specialist-checkpoint.md). This historical
checkpoint's pending acceptance statements are not retroactively rewritten.

Local, default-disabled application-facing increment after `1bea31c`. This is not
a production deployment, OPERATION-agent change or complete quality acceptance.
The [integration contract](mana-family-agents-integration.md) remains authoritative
for the backend API; this checkpoint supersedes earlier model/context limitations
only where explicitly implemented and verified below.

## Implemented

- Parent-Touch's compact strict schema now contains **text slots, not UUIDs**.
  Host-selected question/notice identities remain outside the provider payload,
  are revalidated against SQL and appear unchanged in public response/reply metadata.
  Invalid output never retains even a rejected foreign question identity.
- Compact JSON removes formatting/duplicate routing fields, not current profile
  observations, question meaning/reason, actual dates or assessment quality notes.
  A known notice must explicitly retain UTC observation dates in visible text.
- Parent-Touch uses 128/256-token output admission floors under the existing
  configured cap, verified exact input sizing and unchanged 2000-token allowance.
  Insufficient room is a durable pre-generation refusal. It is not an output-length
  prediction, a higher budget or a guarantee of a fixed number of messages.
- Conservative RU/UZ/EN hints are frozen with each admitted parent reference.
  Numeric/neutral replies inherit only that family's preceding reference; substantive
  language switches do not. Each output field receives language guidance; recognized
  mismatches are charged and withheld, without a second model call. Unknown languages
  remain model-directed. The heuristic is **not** universal language identification.
- Private safety context v2 captures pending information needs and recent exact
  question-bound parent answers atomically with chat admission, under an explicit
  1010-item ceiling. Before inference, fresh ownership filters them to child aliases.
  Private `typed_parent_review` captures a review-only schema: `analysis=null`,
  historical summary, optional information need. New chat reviews cannot generate
  a fresh sensor analysis through this schema. V1/earlier v2 do not upgrade.
- Explicit new-role defaults: Parent-Touch **GPT-5.4**, Child-Safety **GPT-5.4 mini**.
  New configuration keys isolate them from old `OPENAI_MODEL`, legacy chat/audio/
  stateless endpoints. Flags remain off and the separate safety token budget is
  mandatory. No dynamic router, hidden fallback, model retry or production setting
  change was introduced. These are local new-role defaults, not a model migration
  of existing production services.
- All ten protective routes are now tested through **execution**, not admission
  alone: actual SDK MockTransport -> metering -> existing semantic/evidence/proposal
  validation -> capability-specific HTTP result/replay, with no control execution.

The current SDK adaptation follows official [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
with host validation after raw terminal-usage accounting, including incomplete
responses. [GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4) and
[mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) support the existing
Responses/schema/none-effort transport. Do not infer semantic quality from schema
adherence, language-word checks or a fake workflow.

## Actual verification

Final `OPENAI_API_KEY=unit-synthetic-key make verify`, original session **20380**,
exit **0**, ignored log `output/family-role-language-acceptance-verify-20261020.log`:
**485 backend tests**, **1 skipped**, **2 opt-in live excluded**, **26 UI tests /
11 suites**, format/Ruff/ESLint, mypy **243 files**, TypeScript/build, zero npm
vulnerabilities. No test called a real provider/source. API schema synchronization,
diff checks and secret scan **405 files** passed before these documentation edits.
The first slot full gate caught a rejected foreign-ID receipt leak; its failing
log remains `family-slots-verify-20261020.log`. Later green gates do not erase it.

Candidate `mana-ai-family:role-language-local-20261020`, image SHA256
`73242e2bc08bfc14ecdeefe5f359e8a7c71922e9f798a47d7d6ee4ba76006f01`, built and
passed the packaged-app SDK smoke with a read-only filesystem, no network/capabilities,
no-new-privileges and temporary private SQLite. Four mocked generations/four fake
profile reads verified automatic notice delivery, replay and both same-candidate
closed profiles. This is not an old-image rollback or deployed ingress acceptance.
Old `1bea31c` workers cannot execute new private v2 contexts despite SQLite staying
v5; never downgrade/overwrite history or point old enabled workers at them.

## Independent paid synthetic evidence — preserve every original party

No test used a real model. Separately, 13 new local diagnostics used fictional
families and fresh ledgers, never real children/Firebase/GA4, old-party replays or
production. Each party had its own bounded call/token cap below $0.50; the strong
parties also had an explicit $0.45 worst-case admission ceiling. **79 generations**,
all known receipts, no unknown charges/holds. Conservative uncached standard-rate
estimate **$0.12265415** (not an invoice). Together with the preceding v5 parties:
**91 generations, $0.13360540**. Rates were $0.20/$1.25 nano, $0.75/$4.50 mini,
$2.50/$15 GPT-5.4 per million input/output tokens, from the official
[pricing/metrics reference](https://developers.openai.com/cookbook/examples/agent_optimization/optimizing_agents_for_cost_and_quality#metrics-helpers).

The main workspace's ignored `output/` retains each directory's exact `receipt.json`,
script, console and private SQLite ledger. Results are not interchangeable:

| Directory suffix (all dated `20261020`) | Original outcome |
| --- | --- |
| `family-slots-…-0fHKQd` | Nano: two questions; third reply correctly refused by budget. |
| `family-slots-dialogue-…-nUhgNb` | Nano: three chat turns; safety pre-reservation could not fit its test parent allowance. Harness stopped, not a failed provider receipt. |
| `family-slots-bounded-…-9t4IK6` | Nano: duplicate/compound clarification and poor text; budget stopped third turn. Negative quality. |
| `family-slots-mini-…-54WPEw` | RU sequence completed; UZ third turn refused before generation. |
| `family-slots-mini-flow-…-uIh6Rl` | Three RU turns; third generic review failed decision validation. |
| `family-slots-notice-…-kE6e1s` | Mini: synthetic Uzbek notice delivered, 1569 chat tokens. Earlier schema/prompt, not acceptance of current roles. |
| `family-typed-review-…-j2nM0n` | Both typed-review sequences completed, but manual review found an awkward/truncated-by-schema UZ acknowledgment. Negative quality. That 120-character schema restriction was removed. |
| `family-typed-language-…-PLGtbK` | RU completed; English specialist question copied into UZ. Negative language review; new hint/denial regressions cover this class. |
| `family-language-bound-…-xWl1h9` | Model deferred a question. Harness wrongly required immediate publication and stopped before its automatic-delivery path; not a complete workflow pass. |
| `family-strong-speaker-…-ha05QK` | GPT-5.4 speaker + mini safety: complete RU/UZ question -> explicit answer -> distinct next question -> answer/review, exact replay, both questions answered. 1922/1843 chat tokens, separate safety usage. Qualified local pass, not comprehensive child analysis. |
| `family-strong-notice-…-m9sezt` | Diagnostic itself missed `timedelta` import, stopped after two known calls. Not a product failure/pass; original charged party preserved, never restarted. |
| `family-dated-notice-…-IzMvYf` | Notice delivered but omitted the old observation date. Subsequent explicit-date policy/SDK test added; not retroactively a date pass. |
| `family-explicit-date-…-zdI9iy` | Old signal date retained, notice delivered within 1567 chat tokens. Manual review still found a child-directed recommendation in parent chat. The following prompt clarifies adult-parent address; **that last wording change has only fake/static acceptance**, not a fresh real-model quality pass. |

Do not call `completed_for_manual_review` an automatic quality pass. For the strong
dialogue both families had two answered needs and three completed chat reviews;
coalescing prevented a duplicate model need from creating another question. Bounded
history removal can leave only enough context for a short acknowledgment, not a full
recommendation. Current receipts do not establish broad safety/language quality,
source integration with real families, medical correctness or business outcomes.

## Next acceptance / active goal

The original two-agent API objective remains active, not narrowed to formatting.
Next verify a real-model specialist-originated new need -> automatic Parent-Touch
delivery -> bound parent reply -> Child-Safety follow-up, including deferral (a
model may validly omit a question in a normal response). Existing real-model two-
specialist tests seeded the needs; fake HTTP/worker tests cover automatic production
of a need but are not that real-model semantic proof. Recheck adult-parent wording
and an independent urgent-notice-plus-awaiting-question case in both languages.

Keep the 2000 ceiling unless the owner explicitly changes it. Known pre-generation
quota refusals stop delivery for that exact language context; automatic next-day
re-admission of that unchanged choice is **not implemented**. A new parent message
can form new communication context. Do not bypass this with nonce loops or retry
an invalid/unknown inference. A safe explicit quota-carryover policy, full release
scope/ingress and real-family ownership/channel acceptance remain separate work.
No production, SSH/key, source schedule/refresh, real contact, audio, UI or operational
agent changes were made. Do not mark the whole goal complete from this checkpoint.
