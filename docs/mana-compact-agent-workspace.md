# Compact family workspace — local checkpoint, 2026-10-28

This increment reuses the single durable MANA chat, Parent-Touch manager, typed
Child-Safety sources and Upsell lifecycle. It captures new protocols only;
older work, receipts, unknown holds and the two negative real-model parties in
[mana-saved-observation-workspace.md](mana-saved-observation-workspace.md) remain
unchanged. All new flags default disabled. Nothing here deploys production,
refreshes a real provider, grants a tariff or raises a budget. The complete
[autonomous-agents objective](mana-autonomous-agents-plan.md) remains active.

## Child-Safety: one explicit observation tool

`MANA_FAMILY_COMPACT_SOURCE_TOOLS_ENABLED=false` requires the existing saved
observation/compact manager runtime. New family schema **41** captures native
protocol **5** with one strict `read_child_observation` function. Its arguments
include `access=saved_only|live`, child alias, source kind and nullable query-day
label. This is one explicit choice, not permission to try SQL and then Firebase.
Missing/stale/unknown results never cause fallback or another tool invocation.
Protocols1–4 retain their exact original tools, instructions and receipts.

The new initial/final instructions remove redundant static guidance while
retaining the full original request, chat, children, reports, qualifications,
questions, factual values and uncertainty. Reversible host-key renaming preserves
every nested word/value/whitespace. Final instructions specialize only after
validating the exact original call and matching own-child SQL receipt. Private
SQL retains the full prepared input, original call and full source result.

The versioned frame hash binds key mapping, initial/final instructions,
source-specific guidance and canonical result qualifications. Only exact,
validated duplicate provenance is projected away from the HTTP request. Unknown
qualification text or mismatching duplicate dates fail closed. Measurement,
provider-check, collection and inspection dates remain distinct; inspection is
not refresh. No child/family identifiers, GPS coordinates or credentials are
added to model tools. Current source limits and output floor 128 remain unchanged.

Current closed41 preserves all private state with execution stopped. An older
image refusing schema41 is not a functional rollback. Never downgrade populated
state or restore a pre-upgrade database over newer messages, costs or holds.

## Upsell: literal changes without new inference

`MANA_UPSELL_LITERAL_FOLLOWUPS_ENABLED=false` requires captured tariff follow-ups.
Family schema **40** freezes eligibility on new typed tariff enquiries, including
an exactly bound currency answer. Historical39 quotes never acquire eligibility.
New41 composes this lifecycle without changing its contracts.

Strict full-message RU, Uzbek Latin/Cyrillic and English commands may change an
exact duration, explicit total budget or currency. Examples:

- `А на 180 дней?` / `yana 180 kun` / `for 180 days`.
- `До 200000 UZS` / `byudjet 200000 UZS gacha` / `up to 200000 UZS`.

The host derives one new typed enquiry from the current same-parent quote and
exact request chain. All unchanged constraints survive. Source freshness,
ownership, urgency, pending questions, queue/command ceilings, cancellation and
unknown results still use the existing owning lifecycle. Literal changes use
zero model tokens, but do not bypass other limits or enable unlimited commands.

A currency change cannot reinterpret an existing numeric budget: an explicit
replacement amount is required. Free-form/ambiguous requests still use the strong
model path under its existing allowance. No approximate matching, invented
price/discount, grant, payment, transaction or proactive eligibility is added.
Malformed historical quote/proof returns a controlled error before admission.
Full request predecessors are bounded to 20; overflow refuses rather than trimming.

## Combined chat and practical lab

Run `make chat-lab-compact-agents CHAT_LAB_PORT=8117`. Its fictional marked
directory is `data/chat-lab/compact-agent-workspace-v41-simulation`. The v39 and
earlier lab factories/directories remain separate; never reset their state to
manufacture a new allowance. The lab uses fake models and providers, not customer
data, Firebase/GA4 reads, real pushes or tariff grants.

Three latest41 combined regressions cover Retention question -> urgent Safety
notice -> exact parent answer -> next child question, RU/Uzbek controls, known
catalog completion after urgent cancellation, replay and reconstruction. The new
captures themselves are asserted, not inferred from tests on an older schema.
An adapter-only fake defect lost renamed conversation needs and asked a duplicate
question; reversible restoration for the fake fallback fixes it. The actual SDK
still sends the captured compact envelope. No production-model defect is implied.

A browser exercise also found the fake final speaker used a generic simulation
answer for unavailable saved facts. It now explicitly says data is unknown and
the provider was not refreshed, with RU/Uzbek full-flow regressions. The original
browser history and failed narrow language-hint fixture remain retained; old
messages are never rewritten. This improves the simulator, not actual-model
quality evidence.

## Independent actual-model diagnostic

`output/compact-agents-model-20261028/` is a **new, independent fictional** party,
not replay of a failed real family. Real clock, configured GPT-5.4 manager and
GPT-5.4-mini Safety were used. All profile/OAuth/Firestore/catalog transports were
fake; only OpenAI requests used the network. The diagnostic disabled only worker
startup while explicitly processing the existing runtime, avoiding two competing
drivers. No production, source schedule, push, grant or payment changed.

- **Uzbek saved-only request, six-child scope:** one requested child was analyzed,
  not all six. The model chose `access=saved_only`; the source ledger retained
  every cell. The complete natural Uzbek answer reports exact 12%, unknown
  measurement time, no refresh and an adult-directed practical step. Parent
  used **1885/2000**, global Safety **1832/2000**, with zero holds/reserves and
  exact replay producing zero HTTP calls.
- **Russian tariff then three literal changes:** first quote used **843** parent
  tokens. The 180-day change,200000UZS budget and 90-day change used zero further model
  calls/tokens. One fake catalog read served all four turns; exact typed filters
  yielded 299000 UZS, no 180-day match under 200000, then 162000 UZS for 90 days. Safety
  used zero. All replay requests observe SQL.

Five terminal generations and five input-count requests completed. Known uncached
generation estimate is **$0.010734**, using standard short-context rates of
$2.50/$15 per million GPT-5.4 input/output tokens and $0.75/$4.50 for mini.
This is not an invoice or a count-endpoint billing finding. Primary pricing
reference: [OpenAI model pricing](https://developers.openai.com/api/docs/pricing).
Independent content and SQL review is retained in
`output/compact-agents-model-content-review-20261028.json`.

This is a qualified pass for these two fictional conversations. It does not
supersede the actual-family failure, prove fleet capacity, analyze six children,
verify real contact preferences or establish sustained same-day dialogue. One
analysis consumes 1832 of the **global** 2000 Safety allowance and leaves that
parent 115 tokens. Other parents cannot receive comparable analysis that day from
this ledger. No silent limit increase or second isolated fixture presented as
shared fleet capacity is allowed.

## Verification and release boundary

The first full `make verify` passed 1911 backend cases,26 admin tests and23 lab
controller cases, with mypy 498 files, lint/format, TypeScript, production build
and the required high-severity audit gate. Five low-severity development-path
findings remain, documented in the prior checkpoint; production dependency audit
has no findings, and the upstream patch is unavailable. OpenAPI synchronization
passed without public schema changes. The final fake unavailable-message fix also passes `make verify` with terminal
exit0: **1913 backend**, **26 admin /23 lab-controller** cases, mypy **499 files**,
format/lint/typecheck/build and the same qualified dependency audit. Logs:
`output/compact-agents-final-verify-20261028.log`; OpenAPI sync:
`output/compact-agents-openapi-sync-20261028.log`. Counts overlap, not additive.

Final local image `mana-ai-family:compact-agents-local-20261028`,
`sha256:b9e3dec5cce9a6e9af1c4a180390bbb220990f8159786eaf3867a95b01ae0ee5`,
runs Python3.12.15/OpenAI2.53.0. All313 exported files/310 application files
match SHA256. Networkless actual-production-factory rehearsal migrates the
retained v6 copy to41 while preserving all16 original tables/every cell, two
messages and exact legacy replay. Current closed41 retains all86 tables and
1885/1832 settled costs from the new paid diagnostic; another fake fixture
retains150 known tokens and1850 unknown hold through closed observation, restart
and next-day Safety-budget observation, with zero retries. Original DB/WAL/SHM
hashes remain unchanged. Earlier harness failures (missing import path, SQLite
sidecar mount and legitimate parent preparation recovery) are preserved separately;
only the corrected final probes pass. Artifacts:
`output/compact-agents-candidate-20261028/`. This is closed-reader/copy acceptance,
not active old-image rollback or production deployment.

Owned mobile browser session `mana-compact-v41` at390x844 verifies four quotes,
GPS2 labels, saved native5 inspection and an unavailable saved battery reply.
Physical server restart retains all86 family/31 source table fingerprints and
exact full REST state (13 messages); subsequent missing-battery request produces
the qualified reply,15 messages and750 simulated parent/Safety tokens. No page
errors or document horizontal overflow; screenshot visually checked. An initial
selector failure, invalid observation expression and generic fake answer are kept
as diagnostic history, not successes or redispatched original requests. Session
and owned servers are closed. Evidence: `output/compact-agents-browser-20261028/`.

Remaining acceptance includes actual-family native5 within its preserved costs
and source window, full reminder/confirmation/due-delivery/natural-reply quality,
real consent/language/timezone integration, autonomous commercial eligibility,
route history, fleet budgets/coverage and separately scoped release. Referral
remains owner-deferred pending its real contract. Administrative handlers remain
inside the four agreed OPERATION agents; Technical Reliability is last.
