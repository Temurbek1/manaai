# Source-driven tariff expiry reminders — local, 2026-10-25

Retention now has a second executable scenario in the single parent chat:
a newly observed selected paid tariff approaches its recorded end -> Parent-Touch
publishes one exact, dated reminder -> the parent replies -> normal Child-Safety
review and Parent-Touch continue the conversation. No parent message is needed
before the reminder. Parent-Touch remains the only speaker.

The reminder is deterministic because it communicates an exact source date. It
makes **zero model calls and consumes zero provider tokens**; the later parent
reply uses the existing real models and quotas. There is no payment, renewal,
transaction, free-day grant, invented discount, new feature entitlement or
unmanaged question. The selected tariff ending does not prove every entitlement
ends or that protection is being lost. Automatic charging is not inferred.

## Acquisition and boundaries

`MANA_RETENTION_EXPIRY_ENABLED=false` stays the default and requires the current
full Upsell/Retention/reminder/native profile. It is not independently executable
on older family profiles. Production and all existing schedules are unchanged.

After a v17 database exists, turning only this flag off keeps the compatible
Parent-Touch, Child-Safety, Upsell and chat-gap Retention services available. It
removes the profile observer and expiry worker, refuses expiry publication and
suppresses pending expiry pushes. Cached facts, saved messages, consumed outreach
counts, deduplication and circuit state remain intact. Re-enabling resets none of
them; an older v16 image is still not a compatible execution reader.

`RetentionProfileSource` observes successful existing exact-parent profile reads.
The runtime passes the same observed source to Parent-Touch, Child-Safety and
family-source ownership checks, including those performed by the existing
09:00/15:00 collector. It adds **no profile, Firestore or GA4 query** for this
capability. Raw MANA authentication remains a separate server-only adapter port.
This is not a new hourly scan, listener or automatic retry. UI/status/history GETs
still observe SQL only.

By default the collector feeds this cache only through its existing targeted
ownership reads. The subsequent default-disabled [inventory-tariff increment](mana-inventory-tariffs.md)
adds durable collection-v2 batches from known completed bulk pages, including
parents without child targets. It does not publish from a pre-completion adapter
callback or expand existing collection/source ceilings. Neither path proves whole
population coverage, and enabling expiry alone does not activate bulk fan-out.

Only new observed reads enter the minimized cache: canonical parent ID, collection
time, selected record's `is_paid` and `valid_until`. No child identity/name, phone,
location, tariff description, `created_at`, payment history or recipient consent
is captured here. Collection is acquisition time, not a verified purchase event.
Semantic history records changed facts, not another event for every equal refresh.
No old saved source event, chat, Goal or profile is recaptured at initialization.

A failed/stale/foreign profile read invalidates its parent's cached fact before
propagating the error; known authentication failure durably closes this expiry
source across restart. It does not retry the read or reset other capability
budgets. Storage capacity or detected projection corruption closes expiry
publication without turning stale records into current evidence. Other ordinary
chat/profile use continues under its owning policies. There is no automatic
circuit reset/recovery endpoint.

## Contact and ordering policy

Defaults in `MANA_RETENTION_EXPIRY_POLICY` are:

- End time is in the next 72 hours and strictly later than now; paid must be true.
- Source collection is no older than 180 seconds. No fresh source means no notice;
  the worker does not fetch again merely to become eligible.
- Existing Retention ceiling **20 outreach admissions globally/rolling day** is
  shared with chat-gap check-ins; one parent's Retention outreach has a 24-hour gap.
- Active questions, notices, parent turns and queued/in-flight/unknown safety work
  have priority. A recent urgent safety notice also defers expiry for 24 hours.
- Cache limits are 10,000 parent heads and 50,000 semantic changes; overflow closes
  this consumer instead of deleting history, raising limits or sending from old data.

Fresh backend-verified Retention chat consent, recipient language/timezone, contact
validity, quiet hours and the existing persistent opt-out are mandatory. Paid
status grants none of them. Exact localized templates state the recorded term and
offer help checking available tariffs; they ask no new question and make no claim
about charges, access loss, checkout, features or renewal.

One notice per parent/canonical UTC deadline is immutable, even when the provider
returns that deadline in another timezone or refreshes collection time. Notice,
assistant-only history and a separately permitted neutral push outbox entry share
one transaction. Lost local acknowledgement, restart or another worker observes
that transaction, not a new dispatch. The stored notice binds its exact source
collection instant and semantic hash. The actual next parent message remains in
the same ordered chat; temporal adjacency is not causal retention/conversion lift.

Push is optional and independently consented/one-shot under the existing provider
contract. Changed/unknown/stale tariff facts suppress an outdated queued expiry
push without deleting the dated chat message. Queueing is not delivery or reading;
unknown external push outcomes never auto-retry. No new device contact is authorized
by this local implementation or its fake tests.

Parent-Touch stays **2000 raw model tokens per parent/day**, Child-Safety **2000
raw tokens globally/day**. Static reminders have no model receipt. Actual parent
reply analysis still uses those same meters; there is no new AI allowance.
Source/push/backend charges are separate from model-token usage; zero reminder
inference does not prove that an entire deployed system has zero cost.

## Practical lab and evidence

Run `make chat-lab-expiry`. Click “Скоро истекает тариф (вымышленные данные)”.
A declared fictional profile read starts the chat with one assistant reminder.
Repeat the button, reload/restart, and ask `Mening tarifim qachongacha amal qiladi?`.
The template and reply use the same persisted fixture deadline. That fixture is
created once; restart never moves its end forward or renews a quota.
`chat-lab-expiry-live` is a separate explicitly paid-reply mode, with fictional
profiles/catalog/permissions and no live family/push/grant adapter. Never use a
synthetic clock or reset its original receipts to repeat a paid attempt.

Twenty-four fake/MockTransport lifecycle cases cover first contact, two-worker
single publication, restart, eligibility/consent/quiet/freshness, unknown profile
reads, revoked auth, exact source invalidation, old-message opt-out, safety priority
including communicated urgent notices, shared quota/cooldown, capacity, index
corruption, source changes, push suppression, lost local ack and parent continuation.
The production factory's v17 combination is lazy with zero HTTP and shares one
observed source across consumers. Independent stop/re-enable preserves history,
facts and deadline deduplication; a stopped v17 runtime retains the core chat
services without an observer or provider I/O. No automated test uses a real provider.

One separately admitted **actual-model synthetic family** party in
`output/retention-expiry-model-20261025` completed profile -> zero-model notice ->
parent question -> real Child-Safety -> real Parent-Touch. The full v17 native
profile used **1902 speaker /935 safety tokens**, zero holds, two generations/four
OpenAI HTTP attempts, one notice and one semantic profile change. Replay added
zero model/source calls. There were three history messages, zero pushes/grants,
zero real family/Firebase/GA4 reads and no payment or renewal. The response retained
the correct dated term, treated automatic charging as unconfirmed and respected
the parent's request to connect nothing. Estimate **$0.0068975** at standard uncached
generation rates, not an invoice or count-endpoint billing proof. This one RU
fictional loop is not broad model/UZ, real-consent/channel, fleet or business lift
acceptance. Its nearly exhausted speaker allowance does not prove long-dialog capacity.

A distinct **actual read-only test-parent 4** diagnostic in
`output/retention-expiry-profile-live-20261025` made exactly login +filtered Parent
List GET, saved one minimized head/change, and created zero chat turns, contacts or
contact permissions. No model or direct Firebase/GA4 call occurred. This proves the
live adapter-to-cache bridge, not real proactive publication or source coverage.

Family schema **17** adds only expiry policy/head/change/notice tables; child-source
schema stays **4**, collection schema **1**. Schema changes are additive and preserve
old holds/history. Current closed v17 is the supported retained-history reader;
actual v16 refusal is not a working execution rollback. Never downgrade populated
state or restore an old database over new messages. Final gates/browser/image
results are recorded below. The full original goal remains active; proactive
upgrade/conversion/referral/loyalty actions, wider child sources, fleet capacity,
broader quality and a separately scoped release still require work.

## Final local checkpoint

`make verify`, session **93346**, exited **0**: **1307 backend cases**, one skip/two
live opt-ins excluded; **26 admin cases /11 suites**, **10 lab-controller cases**,
mypy **383 files**, formatting/lint/types/build and zero npm findings. The 24
expiry cases and v17 lazy-runtime combination are included, not additional real
model studies. API sync and marker/secret scans pass; the latter inspected 1233
tracked/unignored files at that point. The final gate is recorded in
`output/retention-expiry-stop-final-gates.log`. Initial annotation/import/formatting
diagnostics and a misplaced stop-test block were fixed before this completed gate;
original failure logs remain. No paid or live-source party was repeated.
A regression also removed the profile simulator's old hardcoded deadline: it now
renders the actual fixture/context date, rather than the earlier November sample.

Owned 390px Chromium showed one assistant-first reminder with **0 speaker /0 safety
tokens**, then an Uzbek parent reply and matching term in that same chat. Repeating
the fixture button, reload and server restart retained exactly **three messages**,
**150 simulated speaker /150 safety tokens**, one notice and no overflow/browser
error. The screenshot was inspected; owned browser and port 8097 are closed.
These simulated UI receipts are distinct from the actual-model party above.

Candidate `mana-ai-family:retention-expiry-v17-20261025-local` / `8791d2946969`
passed a networkless/read-only-root v13 -> v17 upgrade/closure probe. Every original
table fingerprint, **150 known /1850 unknown safety tokens** and zero historical
outreach capture were preserved. Current closed v17 retained the actual-model
party's three messages with every table fingerprint unchanged. Critical cache,
application, policy, runtime and lab source hashes match the final host files.
Actual previous v16 image `658b61059504` refuses v17 with unchanged bytes; it is not
a working execution fallback. No populated schema was downgraded or old backup
restored. These are scoped candidate/closed-history checks, not production release,
all-state rollback, real-contact or all-agent readiness acceptance.
