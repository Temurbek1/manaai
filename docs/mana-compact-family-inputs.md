# Compact family input presentation — local, not released

`MANA_FAMILY_COMPACT_INPUTS_ENABLED` is default disabled and requires the
existing typed tariff handoff runtime. Family schema 35 captures presentation
version 1 only for newly admitted native turns. Source/collection schemas,
ownership, tools, models, languages, limits and schedules are unchanged.

## Exact scope

Remove generated JSON Schema `title` annotations, preserving constraints,
descriptions, literal values and properties actually named `title`. Encode the
native host-owned JSON envelope without insignificant whitespace; every quoted
user word, history value, child alias, date and uncertainty remains. On the
final-only Safety continuation, omit callable tool definitions while preserving
the original input/call/result digest pairing and `tool_choice=none`. This follows
the [official OpenAI function-calling contract](https://developers.openai.com/api/docs/guides/function-calling#tool-choice).
No instruction rewrite, context summary, model downgrade or quota increase occurs.

The original native profile and its exact presentation marker/hash are captured
atomically in `family_input_presentations`. Old admissions retain their original
schema/input/digest; migration never backfills them. Missing/changed captures or
disabled presentation refuse execution. Late verified costs are still settled;
unknown submissions retain their holds across restart/midnight. Current closed
v35 preserves history, pending pairings and holds with execution disabled. An old
image refusing v35 is not functional rollback; never downgrade a populated database.

## Actual paid diagnostic: partial improvement, full path still fails

Preserve the earlier [actual-source failure](mana-real-source-chat-budget-checkpoint.md)
unchanged. The independent new four-case party is
`output/compact-family-model-20261027/`; its original admission, attempts, SQL and
negative results must not be replayed, reset or replaced with a pass.

Only OpenAI used real network transport: **8 generations and 10 input-count
requests**, all HTTP 200. MANA, OAuth, Firestore and catalogue responses were
fictional. No customer data, real cloud reads, contacts, grants, payments,
collector, production setting or schedule was involved. Every declared case had
its own unchanged 2000/2000 ledger; this is not global fleet-capacity evidence.

| Case | Parent raw usage | Safety raw usage | Result |
| --- | ---: | ---: | --- |
| RU, six children, battery with unknown measurement time | 1022 | 1783 | Safety completes; Parent-Touch final admission fails |
| UZ, six children, same source qualification | 1035 | 1802 | Safety completes; Parent-Touch final admission fails |
| RU, exactly 365 days / 700000 UZS | 1091 | 0 | One typed handoff, one fake catalogue quote, exact replay |
| UZ, 180 days / 350000, currency absent | 1068 | 0 | One currency question, exact UZS reply, no second inference |

The child cases used the actual product factory and nine-lane worker, six exact
fictional connected children, GPT-5.4 / GPT-5.4-mini and production-size Safety
output ceiling 1024. Their final Parent-Touch input counts were 901/926; with the
unchanged minimum 128 output tokens, required reservations 1029/1054 exceeded
remaining 978/965. No final generation was submitted; no answer was published.
There are no unknown model holds. Safety completion alone does not satisfy the
parent's request, and smaller byte size does not establish financial or semantic
quality acceptance. Different fixtures prevent a causal percentage-saving claim.

The two catalogue outputs preserve the requested terms, dated catalogue basis,
total price and unverified account/payment eligibility. Their figures are fake
catalogue facts, never live prices or paid outcomes. Known standard uncached
generation estimate is **$0.016305**, using the previously verified model rates;
this is not an invoice or a claim about count-request/cloud billing.

## Engineering acceptance

`output/compact-input-verify-20261027.log` completed with exit 0: **1721 backend
tests**, one skip, two opt-in live exclusions; **26 admin tests / 11 suites**,
**23 lab tests**, Ruff/format/ESLint, mypy **463 files**, TypeScript, production UI
build and npm audit with zero vulnerabilities. Counts overlap the focused 16
cases and must not be added. Earlier import-order/test-helper errors remain in
their original logs; they are not product model failures or passing gates.

The focused cases cover exact schema/data preservation, native count/generation
pairing, full fake workflow, old-admission noncapture, atomic capture rollback,
disable/tamper fences, known late costs, unknown parent/native holds, closed
reader/restart/midnight and the actual idle runtime factory. These mechanical
passes do not make the two failed real-model child conversations ready.

Candidate-image, populated migration and browser checks are recorded separately
when completed. No production deployment is authorized by this local increment.

## Integration and next work

The three mobile chat operations stay unchanged. No new mobile field, source
approval or financial executor is required for this presentation option. A
separate model-free lab is available without upgrading existing lab directories:

```sh
make chat-lab-compact-inputs CHAT_LAB_PORT=8112
```

Full child-chat completion under the fixed allowance remains open. Future work
must preserve every failure/cost, original context/pairing and historical captures;
do not lower the output admission floor, retry the source or increase allowances
merely to relabel these cases successful. Further manager/presentation design
needs a new explicit admission protocol and independent quality checks. Referral
remains deferred until its actual API contract arrives; the complete autonomous
agents objective in `mana-autonomous-agents-plan.md` stays open.
