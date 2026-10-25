# Completed-day counters in the single chat — local checkpoint, 2026-10-25

The new default-disabled `MANA_FAMILY_DAY_USAGE_ENABLED` connects the qualified
[family/day source](mana-family-day-usage-source.md) to the existing Child-Safety
review and Parent-Touch chat. This is local implementation, not production activation,
full daily screen-time reporting, complete population coverage or a new agent.

## Actual path and immutable capture

The existing three chat operations are unchanged. A new eligible reviewed turn
captures native protocol 3 in family schema **18**. Its one strict
`read_child_observation` function accepts `battery`, `app_usage`, or `app_usage_day`.
Every field is required; `calendar_day` is an exact date only for the dated kind,
and null otherwise. The frozen Asia/Tashkent query-calendar date bounds the preceding
31 completed days. A model cannot change parent, aliases, date range or credentials.

Verified raw first-call usage is recorded before the host admits an exact
parent/child/request/day read. A separate schema-**5** source cache shares the
whole bounded family/day page between its permitted children. A selected child
then returns to the same specialist invocation, followed by Parent-Touch in the
same chat. Only Parent-Touch publishes a message. There are at most two specialist
generations; no automatic retries, fallback, extra chat or source listener.

Protocol 1/2 input/profile strings and old scopes omit all new fields and never
upgrade. Protocol 3 preserves the original advertised tool schema in its input
digest, but the final-only HTTP/count request carries no callable tools, with
`tool_choice=none`. The exact original call, encrypted opaque reasoning and result
pairing survive. A provisional/invalid call is not authority; verified costs still
count before output validation. This follows the strict/nullable and call-result
boundaries in [official OpenAI function calling documentation](https://developers.openai.com/api/docs/guides/function-calling).

## Shared reads, dates and failure behavior

One new acquisition uses a fresh ownership/ephemeral username lookup, shared
authentication and one fixed MANA usage GET. Another child uses the saved family
page but still verifies fresh connected-child ownership. Raw username, phone,
names, credentials and other children do not enter the selected tool result.

The request ledger is shared with the existing sources: **100 admissions per
rolling day**, including cache hits/failures, unchanged Firestore document-unit
ceiling, and a **six-hour per-parent dated-provider cooldown/cache interval**.
Choosing another date does not bypass that cooldown. No new mass schedule is
added; the existing 09:00/15:00 collector does not acquire this source yet.

Durable parent ownership and selected-child/source holds fence a lost ownership
or provider call across siblings, days, new nonces and restarts. Exact replay reads
the original SQL outcome, including after its query day ages outside the window.
Known auth/schema failure closes the dated source only. A lost local completion
acknowledgement observes the committed original result instead of reading again.

Semantic fingerprints sort children/counters and exclude acquisition timestamps.
Equal recollection retains original snapshot/fact dates; head `checked_at` records
an actual new provider check, not an observation. Snapshot hashes, parent/day,
selected row, derived child snapshot ID and receipt pairing are checked together.

`unavailable` means the selected child was absent from the bounded family page;
it is not a zero counter. A returned empty child page is separately missing evidence.
The requested API calendar label must be shown literally in Parent-Touch's answer,
but remains distinct from verified measurement day, interval and timezone, which
are unknown. Partial app coverage, overlapping durations and missing observations
must not become total screen time, trends, rankings, diagnoses or motives.

The existing **2000 raw Parent-Touch tokens per parent/day** and **2000 raw global
Child-Safety tokens/day** are unchanged. Parent-Touch's dated-result presentation
uses concise host instructions while retaining every original user message,
source fact, account context, reminder/upsell schema and owning confirmation rule.
Large/history-rich requests can still fail admission. Do not present one fitting
case as adequate capacity for the full customer population.

## Real-model evidence, including negative results

Five separately admitted fictional-source parties were run, not replays of old
calls. Each directory retains its original request admission, attempts, SQL and
result; no real family/source, push, grant, payment, Firestore or GA4 call occurred.

| Original directory under `output/` | Actual outcome |
| --- | --- |
| `day-usage-model-20261025` | One native generation, 956 known safety tokens. Exact day/source selected, second generation refused at budget admission. Original speaker admission remains waiting; not an unknown model receipt. |
| `day-usage-model-uz-postfix-20261025` | Two native generations, 2000 known safety tokens; final structured result did not complete within output allowance. Not a quality pass. |
| `day-usage-model-compact-20261025` | Specialist completed at 1852 tokens. Parent-Touch count 2141 exceeded its unchanged limit; no speaker generation. |
| `day-usage-model-en-qualified-20261025` | Specialist completed at 1845 tokens. Parent-Touch count 1960 left less than the required output reserve; no speaker generation. |
| `day-usage-model-uz-slots-20261025` | Complete same-chat Uzbek loop: 1920 safety tokens, 1964 speaker tokens, zero holds, three generations/six HTTP attempts. One fictional family/day acquisition, two messages, replay adds zero HTTP. |

The last answer preserved the exact October-20 query date, one returned app out of
three, its 3600-second counter and unknown measurement period/timezone. It did not
infer the missing apps. Across these parties: **23 OpenAI HTTP attempts**, **10
generations**, **10537 verified raw tokens**. The two earliest failed parties retain
their original pending speaker admissions; no model call is repeated to clean them.
Token counts are not an invoice. Passing this one small Uzbek case does not establish
RU/EN post-fix quality, long-session/fleet capacity, real-family E2E or business lift.

## Local lab and compatibility

Run `make chat-lab-day-usage`; enter a dated app question or ask about yesterday.
Only the fictional lab family is allowed. Its deterministic simulation is labelled
as such and is not a real-model quality test. The parent still sends messages,
observes status and reads the one history; there is no new mobile endpoint.

Disabling dated tools on an existing v18 store admits new turns with the original
v2 tool contract and refuses already captured v3 before inference; it never changes
old captures. Fully closed v18 readers retain history/quotas/unknown holds. A v5
source reader can retain the cache with dispatch off. Earlier v17/v4 refusal is
not a working execution rollback: never downgrade populated databases or restore
old copies over newer history.

## Final engineering and browser evidence

`make verify` **94904** exited **0**: **1386 backend cases**, one skip/two excluded
live opt-ins, **26 admin cases /11 suites**, **10 lab-controller cases**, mypy
**396 files**, formatting/lint/types/build and zero npm vulnerabilities. API/schema
sync, quality-marker and secret scans passed (1425 inspected files at that point).
Tests use fake/MockTransport providers only. The first full command lacked the
mandatory dummy inference key and failed collection; the configured final gate
uses an explicit fictional key. Initial invalid request-field and unfinished
failed-review test harnesses remain recorded separately, not passing evidence.

Image `mana-ai-family:dated-usage-v18-20261025-checkpoint`,
`sha256:c92073bc996c13ac4c9d78606e0be32b1a9e12d2f7f9f84ba4efda419add4035`,
passed networkless/read-only-root/user-1000 probes with `APP_ENV=production` and
unrelated Telegram auth explicitly disabled in the isolated fixture. The initial
probe omitted that fixture setting and failed before its lab started; its negative
log remains. This is subsystem compatibility evidence, not a complete production
configuration/startup test. All **19** changed application Python hashes match;
there is no `.env` in the image.

V17 -> v18 and v4 -> v5 retain every original table fingerprint. The old family
fixture keeps **150 known/1850 unknown** safety tokens. A new packaged fictional
source/chat loop, then lost model receipt, retains **three messages and 300
known/1700 unknown** tokens through the current closed reader. A disabled v5 reader
retains its unknown ownership hold. Actual previous image `8791d2946969` refuses
new family v18/source v5 with both database byte fingerprints unchanged; it is not
a working execution rollback. Receipts: `output/day-usage-image-compat-configured-20261025.log`,
`output/day-usage-actual-old-reader-20261025.log`, and the source-hash JSON.

Owned Chromium at **390 px** exercised Russian and Uzbek dated requests using the
same single chat and one saved family/day page (provider acquisition then cache hit).
The existing independently consented fictional Retention worker also published one
zero-model expiry reminder: **five messages**, **300 simulated speaker/600 simulated
safety tokens**, one expiry notice. Reload and actual server restart retained every
family/source table fingerprint, with no new read, inference or duplicate message.
Both screenshots were inspected: no page overflow or browser errors. The owned
browser/server were closed. See `output/day-usage-browser-20261025/result.json`.

Full goal work remains active: shared dated bulk collection, broader sources/GPS identity,
referral contracts, commercial eligibility, capacity and separately scoped release
acceptance are not completed by this increment.
