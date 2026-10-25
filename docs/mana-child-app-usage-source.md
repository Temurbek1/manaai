# Own-child app counters in the single chat — 2026-10-25, local

The subsequent [completed-day family source port](mana-family-day-usage-source.md)
confirms that the documented **bulk** endpoint can filter calendar labels. It is
not runtime-wired and does not upgrade this detail tool's captured scope. Neither
path proves foreground screen-time units or provider timezone. The shared parser
also now accepts the observed one-empty-page convention without treating missing
evidence as measured zero use; original failed diagnostics remain retained.

The active [autonomous objective](mana-autonomous-agents-plan.md) now has a second
runtime-wired source: the existing exact-child Manakids usage API. Child-Safety
can select battery or app counters, receive their qualified facts and return its
review to the sole speaker, Parent-Touch. The mobile API remains the same three
chat operations. No backend webhook or manual approval is needed for an admitted
read within the configured family/source/budget scope. No production setting,
source schedule, customer contact, tariff, key or SSH access changed here.

## Facts established by actual source reads

The existing `manakids-ai-docs.md` documents
`GET /api/v1/admin-panel-child/app-usage-statistics/<child_pk>/`. Three distinct,
one-shot diagnostics used only designated test parent `4` and fresh connected-
child ownership: initial shape discovery, a date-filter probe and actual new
adapter/cache acceptance. Each used one login, one filtered Parent List GET and
one exact-child usage GET: **nine HTTP attempts total**, three child-usage reads,
zero retries, Firestore calls, generations, contacts or provider mutations.
They are manual diagnostics, not live calls inside automated tests.

The provider returns a first page of app names and counters with
`daily_usage[].date`, `total_time`, plus page/count metadata. The first two reads
returned ten of 26 apps; the later implemented-adapter read returned ten of 24.
That difference does not establish uninstall events or a complete change feed.
Two observed app counters sum beyond 24 hours; they must not be summed into daily
screen time or treated as mutually exclusive durations. Percentages/average-time
text/icons/provider row IDs are not evidence for those conclusions and are omitted.

The provider timestamp is a **naive string**, such as `2026-10-23 23:43:43`, without
a verified timezone or measurement interval. The date-filter probe requested
October 23 while the local date was October 24 and returned October-23 labels.
The initial and probed payloads matched, but this does **not** establish how the
filter is implemented. The provided document says detail requests do not apply
the listed bulk parameters. The adapter therefore sends no assumed date filter
and keeps `observed_at=null`, `source_updated_at=null`, quality `unverified_period`.
Collection time never becomes the counter's measurement time.

The adapter reads exactly one bounded first page, at most ten apps and 64 KiB,
without pagination, cursor following, retries, redirect, guessed fallback URL or
date/identity join. It validates count/page coherence, actual calendar labels,
duration syntax and uniqueness. Partial coverage is explicit, not a complete
inventory, full ranking, activity trend or diagnosis. Unknown/unusable data does
not become zero use. Keys/JWTs remain on the server; app names are quoted data,
never instructions or permission.

Original private artifacts (do not replay them):

- `output/child-usage-contract-20261024/`: schema-only discovery.
- `output/child-usage-period-contract-20261024/`: safe counter/date examples.
- `output/child-usage-adapter-live-20261025/`: one actual completed v3 cache receipt,
  ten of 24 apps, no verified period; exact replay added **zero HTTP attempts**.

The October-12 Firestore schema audit independently shows location coordinates,
accuracy/mock flags and unreliable future dates, but no child-ID field in the
sampled location documents. Its document-ID-to-child mapping remains unverified.
This is not proof that every location document lacks ownership metadata. A parent
location tool is not implemented by guessing that join; actual mobile/backend
storage code or another authoritative binding must establish it. Administrative
aggregate GPS availability does not authorize a per-parent identity guess.

## Shared acquisition and private schema 3

`SqliteMultiFamilySourceStore` extends the existing source cache additively from
v1/v2 to **v3**. Battery tables, payloads and existing unknown holds remain intact.
App counters have separate head/snapshot/circuit tables; both providers share
the original rolling **100 request admissions/24h** ceiling. Firebase retains
the **200 conservative document units/24h** ceiling. App API reads reserve zero
Firestore document units, which is not a claim of zero backend resource cost.
Failed/cache/unknown requests still count toward shared request admission.

Six-hour provider cooldown and unknown single-flight are scoped by child **and
source**. Every new request, including a cache hit, checks fresh ownership;
exact UUID replay only observes its original SQL receipt. A usage authorization
failure closes usage durably without reopening it after restart; it does not
reset another source or restart a whole batch. Unknown battery/usage claims do
not clear at midnight or permit replay under another nonce. Shared source changes
preserve their source kind and fingerprint; recollection alone is not a new fact.

The battery safety consumer explicitly selects only its event kind through an
indexed SQL cursor. App counters do not contain the verified observation period
required for a fresh automatic protective finding. They can inform a parent-
intent review but are not forced into a battery or screen-time signal.

The first browser run exposed a real integration bug: the consumer scanned the
shared app-change event as a battery event, stopped its worker, then rejected the
second message before SQL admission. The original negative screenshot/log and
pre-fix failing two-message regression are retained. Source-kind filtering and
its v3 index fix the issue; no worker auto-restart or failed-message redispatch
was added. A separate simulation fix selects the latest parent's intent rather
than a keyword in old chat. Neither fix changes the real model protocol.

## Captured native protocol and family schema 12

`MANA_FAMILY_APP_USAGE_ENABLED=false` is the default. Explicit enablement requires
the existing family-source/native-review configuration and its own MANA auth
port. Initialization performs no provider call. The combined runtime still
requires its explicit confirmed Firebase configuration; a usage-only read does
not call Google. The Manakids token port is shared with ownership reads.

New family **v12** turns capture `source_contract=2`. One strict
`read_child_observation(child_alias, kind)` function accepts only `battery` or
`app_usage`. No provider URL, arbitrary query, parent ID or action is model input.
Its source-specific result is bound to the exact original native call, input,
scope, model/serving/limits and SQL claim. Raw terminal usage is durably recorded
before interpretation or source dispatch, with at most two generations in the
same job. The **2000 global safety tokens/day** and separate **2000 speaker
tokens/parent/day** remain unchanged; unknown continuations keep the unused hold.

Previously captured v11 turns retain their battery-only protocol, original prompt,
scope serialization and digest even under the v12 worker. Old requests/results
never acquire another source. Frozen app facts reach Parent-Touch with child IDs
removed and partial/unknown-period constraints retained. Facts never become tool,
contact or device-control permission.

Close v12 with `SqliteClosedObservationToolSafetyStore` and execution disabled,
retaining its populated private history. Use the same current code to observe
source v3 without dispatch. Actual older v11/v2 images refuse v12/v3 without
changing database bytes. This is **refusal**, not a working old-image rollback.
Never downgrade tables or restore old databases over newer history.

## Web lab and real-model evidence

```bash
make chat-lab-observations
# Explicit paid inference; all family/source data still fictional:
make chat-lab-observations-live CHAT_LAB_ENV_FILE=/path/to/server.env
```

Use the ordinary composer: “В каких приложениях ребёнок проводит время?” or
“Farzandim qaysi ilovalardan foydalanadi?”. No extra source button is required.
The separate mode-marked directories are `data/chat-lab/observation-simulation`
and `data/chat-lab/observation-real-model`; previous lab modes cannot silently
upgrade their history. There are no live family, push or grant adapters in them.

One actual RU three-generation party used a fictional family and one fictional
app counter. The model selected app usage, received its record and returned to
Parent-Touch with correct name, 3600 seconds, one-of-three coverage, provider date
and unknown period. The literal-second wording could be more natural. This is a
narrow synthetic source-choice/qualified-answer pass, not a full real-family,
multi-page, Uzbek quality or business-outcome pass. It did not run the background
consumer and does not retroactively validate the later worker fix.

| Actual generation | Raw input | Raw output |
| --- | ---: | ---: |
| Specialist chooses source | 727 | 28 |
| Specialist receives counter | 901 | 138 |
| Parent-Touch communicates | 1029 | 90 |

Safety total **1794**, speaker **1119**, all settled, no unknown reserve.
At the checked standard uncached rates, generation estimate **$0.00589050**;
admission worst bound $0.039. This is a calculation, not an invoice or count-API
charge determination. [Primary pricing reference](https://developers.openai.com/api/docs/pricing).
Original `output/observation-real-model-20261025/` is immutable evidence, not
permission to replay/reset a party or claim production capacity. Only 206 safety
tokens remain in that day's isolated diagnostic; this does not expand production's
shared allowance or prove that a ten-app page fits the same model budget.

## Engineering evidence and remaining scope

Final **`make verify` session 91229**, terminal exit **0**:
**1185 backend tests passed**, one skipped, two opt-in live tests excluded;
**26 admin tests /11 suites**, **seven lab controller tests**; format/Ruff/ESLint,
mypy **333 files**, TypeScript, production UI build and npm audit (**zero
vulnerabilities**) passed. Evidence: `output/observation-verify-final-20261025.log`.
Earlier 1183/1184 gates predate the last worker/simulation fix and are retained
as such. All automated provider calls are fake/MockTransport-only.

The actual pre-fix two-message regression failed because the worker stopped;
the corrected focused source/worker suite passed **38** cases. The final latest-
intent/source workflow suite passed **32**; counts overlap the full suite.
The browser then resumed the same fictional SQL history after an explicit owned
server restart. A fresh browser context manually submitted the next UZ message;
the old pre-read 503 UUID was not automatically replayed. Two successful turns,
four native raw receipts, one fictional usage query plus one cache hit, 600
simulated safety/300 speaker tokens and four messages survived reload. No push/
grant row or post-fix worker stop existed. Desktop and 390px UZ screenshots were
visually inspected; no horizontal overflow. Owned browser/server are closed.
Evidence: `output/observation-browser-20261025/postfix-result.json`.

Frozen local image `mana-ai-family:app-usage-v12-20261025-final`,
`sha256:c2bc5654cb9d81fdb794524f9af64e683bc5f25f0659b3d433dfb1ddd77fd970`,
passed networkless populated v12/v3 closure/reconstruction: all table fingerprints
unchanged, 150 known tokens plus 1850 unknown reserve retained through midnight,
and the independent unknown battery source claim retained alongside a completed
usage receipt. No provider client was constructed. Evidence:
`output/observation-final-image-compat-20261025.log`. Actual v11/v2 image
`0d2c5034e15a` separately refused those schemas with database bytes unchanged
(`output/observation-old-image-refusal-20261025.log`); it is not a working rollback.
Pre-fix images/checks are not relabelled as this final candidate.

Final secret scan passed **690 tracked/unignored files**; quality-marker and diff checks
passed. The original negative browser, one bad test helper attribute and pre-format
lint/mypy failures remain in private artifacts. They were corrected before the
final gate; no real diagnostic or unknown cost was replayed to produce a pass.

Remaining full-objective obligations include authoritative GPS ownership, further
telemetry/GA4 tools, cross-purpose analysis coalescing, common 09:00/15:00 collection,
durable reminders, retention/upsell/referral/provider actions, verified channel/
consent semantics, broader real source-plus-model E2E, throughput/cost acceptance
and separately scoped deployment. The original goal remains active and complete
success has not been established by this source increment.
