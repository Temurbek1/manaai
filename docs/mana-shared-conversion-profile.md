# Shared tariff observations for Conversion — local, not released

The existing profile/09:00–15:00 inventory acquisition can now feed both Retention
and Conversion in the same SQL transaction. A new paid, unknown or changed selected
tariff can cancel a queued commercial proposal without another backend conversion
event, profile GET, Firebase/GA4 query or model call. Parent-Touch remains the only
speaker. Already saved chat messages are preserved; unsubmitted marketing pushes
are checked independently against the originating proposal's captured source scope.

This is a stricter source veto, **not a complete autonomous paid-conversion agent**.
A selected non-paid tariff does not prove absence of other paid entitlements,
free-period start, app activity, contact consent, renewal or approved billing terms.
The existing authoritative `ConversionSnapshot`, approved offer and all owning
policies are still required. No grant/payment/transaction is created and no
business conversion is inferred from `is_paid=true` alone.

## Capture, sources and budgets

`MANA_CONVERSION_SHARED_PROFILE_ENABLED=false` is the default. Enabling it requires
the existing Conversion and profile-observation runtime. The immutable
`MANA_CONVERSION_SHARED_PROFILE_POLICY` defaults to **180-second freshness** and
**10000 minimized heads**. Policy changes cannot reset historical checks/circuits.
No production source or schedule was activated by this local increment.

Family schema **20** adds only a policy/circuit, minimized shared profile heads and
event-bound check captures. Source cache **6** and collection **3** remain unchanged.
Existing profile reads and known tariff inventory batches call the same typed sink;
the sink now writes both consumers atomically. It adds no provider request, model
budget, new mobile endpoint or mandatory backend webhook.

Only new conversion events capture the enabled bit, exact original snapshot digest,
revision and expected free-access deadline. Old events/profiles are not recaptured
on upgrade, flag changes or idempotent replay. Fresh non-paid evidence can only
allow the **remaining existing checks** to run. It cannot create eligibility,
replace the independent account verifier or turn chat inactivity into app analytics.

Captured checks refuse missing/stale/unknown facts, paid status, incompatible terms,
closed sources or disabled consumers. An older ignored profile cannot replace a
newer paid observation. Conflicting payloads at one exact observation time close
the Conversion consumer without resetting Retention's circuit. Capacity/corruption
also close the consumer. Source/auth failures and disabling stop captured work;
there is no permissive fallback, automatic read, retry or circuit reset.

The exact event replay retains its original admission receipt; current proposal
status is obtained separately through the existing proposal GET. Replay cannot
reopen a proposal cancelled by later facts. A positive paid record is a veto,
not a payment receipt or a measured paid-conversion outcome. Existing unknown
model/source holds, token/source budgets and consumed trial history are unchanged.

Marketing notifications retain the original proposal/revision/event binding,
current contact/quiet-hour/opt-out checks and source validation. Captured check
digests must match the originating event. A saved message is not deleted when
payment is later observed. Submitted/unknown sends are never cancelled by rewriting
their receipt or retried automatically.

## Practical local chat

Run `make chat-lab-shared-conversion`. This separate fictional profile has no real
provider, grant or push gateway. Its fixed clock starts at 09:00 Asia/Tashkent;
the simulated paid-profile button advances to 15:00. Observed clock state restores
from private SQL on restart, without reapplying a profile or event.

Use “Профиль: не оплачен (симуляция)” and the existing “7 дней бесплатного доступа”
scenario to admit a fictional, explicitly approved catalog offer. The profile
button itself creates no eligibility or message. “Профиль: оплачен (симуляция)”
updates the shared source rather than sending another conversion backend event.
Observe the cancelled proposal or retained original message in the existing lab
state/history. Unknown/stale sources refuse a new proposal; they are never free
or paid by default. Real contacts and grants remain disabled.

The local-only `/lab/conversion-profile` requires the existing cookie, CSRF and
exact fictional parent. Boolean status is strict; numeric zero is rejected.
This debug route is not mounted on the product app or advertised as a mobile API.
All new phone integration still uses the existing message/status/history operations.

## Recorded evidence and limits

Final `OPENAI_API_KEY=fake-verification-key make verify`, original session **14649**,
exited **0**: **1424 backend cases**, one skip/two excluded live opt-ins, **26 admin
cases/11 suites**, **10 lab-controller cases**, mypy **406 files**, formatting/lint/
types/build and zero npm vulnerabilities. The focused new suite passed **18 cases**;
the two additional real-factory configurations are covered by the full matrix.
API/TypeScript synchronization passed without adding a production route.

The focused suite covers one profile acquisition feeding both consumers, paid
veto, unknown/missing/stale/mismatched facts, source closure, absent activity or
consent, equal-time conflicts, older evidence, original-event replay, push fencing,
flag stop/reconstruction, immutable old captures, current closed history and actual
local HTTP authorization/CSRF/family isolation. It also checks fixed-clock restart.
The runtime matrix includes the actual factory with and without dated collection;
startup makes no provider call. Automated providers/models are fakes.

The initial test fixtures used an obsolete contact revision, wrong old-reader
exception type, disabled fictional outbox and an absent approved fixture catalog.
Their negative logs are retained. A mixed-kwargs typing issue and import formatting
were fixed before final gates; no test bypass or production policy was weakened.

Packaged probes use network disabled, read-only root, user 1000 and production
configuration with unrelated Telegram auth explicitly disabled in the fixture.
They preserve every original v19 table fingerprint through upgrade, create no
historical source/event capture, and retain **150 known/1850 unknown safety tokens**.
A different fictional parent receives one existing host-owned offer at **zero new
model tokens**; a later shared paid observation suppresses its unsubmitted push.
Original-event replay cannot republish. Current closed v20 retains all tables.

Actual previous v19 image `8ed752964ac3` refuses v20 with database bytes unchanged.
This is not a working execution/production rollback; never downgrade populated
schemas or restore an older database over newer history. The first image harness
omitted `PYTHONPATH=/app` and failed before application setup. Its original log is
retained; the configured probes made no external request.

Final image `mana-ai-family:shared-conversion-v20-20261025-replay-postfix`,
`sha256:a652d0ed9e027024e7f36f593a419f9181b7490c23decad4d256d3a7481d5093`,
matches all **six** changed application Python hashes and contains no `.env`.
Receipts: `output/shared-conversion-profile-image-compat-replay-postfix-20261025.log`,
`output/shared-conversion-profile-image-hashes-replay-postfix-20261025.json` and
`output/shared-conversion-profile-actual-old-reader-20261025.log`.

Owned **390 px** Chromium exercised a profile observation that created no offer,
the existing separately authoritative fictional conversion scenario and one
assistant-only offer, then a paid profile and a new contradictory free-account
event. That event was refused as `shared_profile_paid`, with no new proposal.
The original message remains. The independently consented existing Retention
expiry notice ran at 15:00: final **two assistant messages**, one per purpose,
with **zero simulated model tokens** and no external requests. Reload and an
actual server restart retained every family/source table fingerprint, without
duplicate messages. Both screenshots were inspected: no overflow/browser errors.
The owned browser and port 8097 server were closed. Result:
`output/shared-conversion-browser-20261025/result.json`. The initial browser
inspection used unsupported top-level `await`; its syntax error dispatched no
request. Subsequent SQL-only inspection used an async expression, not an action retry.

The browser and earlier **1423-case** gate preceded a final independent replay
regression. That test correctly failed: repeating an old profile after enabling
the consumer could create a shared head. The fix checks the preceding Retention
head in the same transaction, ignores exact old observations and closes on
equal-time conflicting legacy facts. The original negative log remains at
`output/shared-conversion-profile-old-observation-negative-20261025.log`.
The final **18-case/1424-case** gates and final image also prove that replaying
the actual old v19 profile cannot recapture it. The earlier passing logs/image
are not relabeled as covering that regression; the UI was not repeated for this
additional source-only edge case.

No new real-model party was run for this deterministic source-policy change.
The prior qualified/failed model receipts remain unchanged; this does not improve
their presentation findings or broaden their acceptance.

This increment does not establish live source-to-offer/real-channel acceptance,
broad language/model quality, full-parent coverage or commercial improvement.
Autonomous eligibility from independently authoritative free-start/activity/approved
offers, referral integration, broader sources/admin owners and separately scoped
release/rollback remain in the original active objective. No production, cloud
data, source schedule, key/SSH, main/audio, customer tariff or real contact changed.
