# Parallel specialist increment — local, 2026-10-28

Three implementation agents worked on independent Retention, Upsell and
Child-Safety paths. The primary agent integrated configuration, actual runtime
selection, Parent-Touch presentation and the practical lab. A second agent
reviewed the shared catalog and GPS changes without authoring them.

Parent-Touch remains the only speaker in the parent's one durable chat. These
specialists are not additional top-level OPERATION agents. This is local work;
it does not update production or activate a source schedule.

## Retention: parent-controlled resumption

The parent can explicitly undo their own local check-in refusal in the normal
message API, without a new endpoint or model call:

- RU: `возобнови напоминания об этом чате`
- Uzbek Latin: `bu chat haqida yana eslatib turing`
- Uzbek Cyrillic: `бу чат ҳақида яна эслатиб туринг`
- EN: `resume chat check-ins`

This changes only that preference. Independently verified Retention consent,
quiet hours, fresh ownership, priority and existing limits still apply. The
control creates a durable audit and assistant acknowledgement, with zero model
tokens. It cannot resurrect suppressed intents or pushes, repeat an old anchor,
answer an unrelated pending question, or clear an unknown hold. Replaying an
older stop/resume request observes its exact result without changing a newer
preference. Resume uses existing host-command ceilings; stopping remains available.

## Upsell: one shared catalog request, several waiting families

An enquiry that meets an already submitted catalog read now observes that exact
SQL claim instead of immediately reporting unavailable. Every family retains its
own choice, ownership check and original reply turn. Waiting performs no provider
read, model call, new admission or financial action.

Waiting ends at the original source, enquiry or ownership-freshness deadline,
whichever comes first; a monotonic timeout also bounds a stalled wall clock.
Cancellation or expiry affects the waiting enquiry, not the source owner.
Unknown/lost/expired source outcomes stop waiting and remain blocked; they are not
retried on restart. Exact claim/expiry/hash validation protects observation. No
schema, public request, model protocol, token budget or source ceiling changes.

## Child-Safety: two saved GPS observations

`MANA_FAMILY_LOCATION_COMPARISONS_ENABLED=false` is a new explicit setting. It
requires the existing location and compact-publication runtime. Only new source
admissions capture eligibility and one prior same-parent/child indexed snapshot,
atomically before provider dispatch. Old in-flight reads never acquire it.

Source schema **9** adds admission/head companions; family schema **37** records
eligible Safety jobs. The source result binds the exact new snapshot and the
saved prior source/child/fingerprint. A review publishes a minimized typed view
through the existing Safety -> Parent-Touch -> single-chat path. It adds no
external read: both observations are already in the shared cache.

Both original measurement, update and collection dates remain distinct. Only
strictly ordered known measurement times permit an equal/different stored-point
relation; missing, unknown, equal or regressed times remain not comparable.
Mock/sample and accuracy qualifications survive. Models receive neither point
hashes nor coordinates or family identifiers from this comparison. Two records
do not establish actual movement, a route, distance, speed, presence, arrival,
geofence crossing or danger.

Disable fences apply before Safety/Parent-Touch submission, after verified
usage and to unsent notices/pushes. Stopping cannot refund known charges or clear
lost in-flight holds. A stopped comparison never silently degrades into a
different single-point analysis. Current closed family-37 readers retain all
private state. Do not downgrade or restore an older database over new history;
the older family-36 image cannot execute this new schema.

## Practical lab

Run `make chat-lab-location-comparison CHAT_LAB_PORT=8115`. This is an isolated,
model-free workspace at `data/chat-lab/location-comparison-v37-simulation`; earlier
lab directories and their captures do not upgrade. Select “Две GPS-записи
(симуляция)” for two explicitly fictional saved points and one assistant-first
report. Other supported single-chat scenarios and Retention control messages
remain available. Repeating the fixture observes the same source UUIDs.

The artificial fixture clock and source have no live adapter, key, push or tariff
executor. They cannot run with a real model. A simulation demonstrates workflow,
not semantic quality or actual child movement.

## Real-model evidence and remaining scope

One independent actual-runtime Uzbek first-contact case used real GPT-5.4 /
GPT-5.4-mini, real wall time and two fictional dated SQL observations. It completed
Safety -> Parent-Touch -> one assistant-only message with **1560 parent /1209
Safety raw tokens**, no unknown holds and zero extra calls on exact replay.
Two generations/two input counts used an estimated **$0.0068705** in standard
uncached generation pricing; this is not an invoice or count-endpoint billing.
No live Firebase/GA4/MANA source, push, grant or payment was called.

This is a **workflow pass with a negative content review**: the answer collapsed
two exact measurement instants to one UTC calendar date without time/zone,
which is ambiguous across the recipient's midnight; opening wording was formal.
It correctly avoided inferred routes/current location/danger and suggested a map
check or calm discussion. Preserve the original receipt and review, not a general
model-quality pass. A preceding settings-only harness failure made zero external
calls and is retained separately. Evidence is in
`output/location-comparison-model-setup-fixed-20261028/` and the original setup log.

The full goal remains open. Exact natural date presentation, wider real-source/
model acceptance, automatic commercial eligibility, actual route/geofence
coverage, fleet capacity, referral API and separately scoped production release
remain unfinished. Parent-Touch retains **2000 raw tokens per parent/day**;
Child-Safety retains **2000 globally/day**, not per family. No budget or old
diagnostic was reset to obtain this evidence.

## Completed local checks

`OPENAI_API_KEY=fake-test-key make verify` exited **0** in
`output/parallel-agents-final-formatted-verify-20261028.log`: **1792 backend cases**,
one skip/two live exclusions, **26 admin cases /11 suites**, **23 lab-controller
cases**, mypy **475 files**, formatting/Ruff/ESLint/TypeScript/build and zero npm
vulnerabilities. OpenAPI synchronization passed separately. The earlier full
pre-browser gate also passed; the intervening format-only refusal is retained.

The 390px browser covered the new assistant-first report, RU opt-out, Uzbek
resumption and a 90-day fictional quote in one chat. Seven messages, **300/150
simulated parent/Safety tokens**, full REST state and every cell of **79 family /
29 source tables** survived fixture replay and a deliberate server restart.
Document width remained 390px, with no page JavaScript error. The owned browser
and port 8115 are closed. A caught prototype shared-fixture-clock issue was fixed
before the final full gate; the GPS lab now exposes only its own artificial-time
fixture. Initial startup/cookie/evaluation harness observations are retained and
were resolved without a replacement message POST.

Clean staged-index image `mana-ai-family:parallel-specialists-local-20261028`
(`sha256:eaa9dc20ec5b04f415d94b4ae2605f23681088d9f2bfa93940edb74b5ca3ee4d`)
contains **295 application Python files**, all matching both the clean export
and current sources. Its real production factory ran networkless against the
retained read-only production-v6 copy: **v6 -> v37**, every original cell in 16
tables, two original messages, exact historical replay, 401 without authentication
and 404 for lab cards. No historical turn gained a capture or provider call.
The same image's closed reader preserves all 79 tables of the paid-case copy,
one assistant message and both settled model costs. The first closed probe
incorrectly called a method intentionally absent from closed readers; its failure
is preserved. The corrected probe inspects retained SQL costs without introducing
an execution API. These are local upgrade/closed-observation checks, not an active
old-image rollback, production rollout, load study or complete semantic acceptance.
