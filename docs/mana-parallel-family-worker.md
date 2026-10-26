# Independent family processing — local, 2026-10-26

The former single worker awaited source preparation, Child-Safety inference,
Parent-Touch, reminders, tariff preparation, Retention, Conversion and push in
sequence. A slow model or network call delayed unrelated families and even a
push for an already saved message.

`MANA_FAMILY_PARALLEL_WORKER_ENABLED=false` keeps that serial behavior by default.
The explicit parallel profile requires the existing reviewed Parent-Touch and
Child-Safety runtime. It is implemented locally, not enabled on production. It
does not create an agent, endpoint, database, collection schedule or permission.

## Scheduling and authority

One supervisor owns nine fixed async lanes: source-change dispatch/preparation,
Child-Safety, ordinary conversation, specialist delivery, reminders, Upsell,
Retention, Conversion and push. Each awaits one owning workflow at a time, then
waits the configured poll interval. There is no per-event fan-out, unbounded task
creation, extra retry or automatic restart. Source preparation still shares its
existing dispatch/review stage; the independent collector retains its existing
09:00/15:00 Asia/Tashkent windows and source meters.

Lanes poll local SQL. Only an existing owning durable claim can authorize I/O.
The same parent's unique pending turn, safety/urgent-question priority, fresh
ownership, contact consent/quiet hours, current offer facts and all idempotency
checks still decide whether a workflow may proceed. Parent-Touch alone publishes.
Concurrent workers use those same SQL claims, not process-local permission locks.

An unrelated family's ordinary manager reply and an allowed push for saved chat
can proceed while Child-Safety waits. A message for the family actually awaiting
safety still waits for its review; concurrency does not bypass it. Urgent priority
does not imply cancelling an unreceipted model or refunding its unknown usage.

No token/read/send allowance increases. Parent-Touch remains 2000 raw tokens per
parent/day and Child-Safety 2000 global/day. Existing native per-job reservations
can still exhaust admission after one analysis even when some raw daily tokens
remain; parallelism is not fleet capacity or a remedy for that budget constraint.

## Failure, shutdown and compatibility

An unclassified lane failure marks the worker unavailable, stops admission,
cancels sibling lanes and awaits their owning cancellation cleanup. An independently
cancelled lane is also a failure: `TaskGroup` must not silently leave the remaining
worker running without safety or another required workflow. Logs contain fixed
lane labels/error codes, never exception/provider text. Existing typed source
denials continue to use their owning source circuit/receipt handling.

Shutdown retains the original five-second grace. If a submitted call has not
finished, cancellation records its existing durable unknown hold. Restart, new
nonces, GETs and clock passage never repeat that call. A failed supervisor does not
restart itself. Known, verified usage and existing publication fences remain in
the owning services.

There is **no schema or stored model/source protocol change**. Historical tasks
are neither recaptured nor upgraded. Disabling this scheduling flag selects the
serial worker with the same original records and budgets. Other feature-specific
schema/rollback restrictions still apply; this flag does not make an older image
capable of reading unsupported family/source versions.

## Practical verification

The focused real-service/SQLite suite passed **69 cases**, including the earlier
review-first, manager, evidence and lab regressions (counts overlap later gates).
New tests use declared fictional families and fake models/gateways, with an
explicitly blocked response rather than a timing-only performance assertion:

- Two workers claim one slow safety analysis once; another family completes its
  greeting and receives one permitted push for a saved question before release.
- The original family remains awaiting review; actual graceful shutdown preserves
  the submitted unknown hold across reconstruction and never reinfers it.
- Unclassified source-lane failure and independent lane cancellation stop siblings
  and new admissions, preserving unknown usage and omitting raw exception text.
- Default serial ordering remains; the real runtime factory selects parallel
  processing explicitly and makes no external request while idle.

The first focused iteration lacked an `Any` import and also observed the valid
intermediate `metered` status too early. The corrected test waits for a terminal
status and still requires `completed`; application outcome checks were not relaxed.

Run `make chat-lab-parallel CHAT_LAB_PORT=8101` for existing fictional single-chat
scenarios under the new scheduler. Other lab profiles retain their original
worker mode and storage marker. A fake pass does not establish model quality,
fleet throughput, current child measurements or actual retention/conversion lift.

Final **`make verify` exited 0**: **1559 backend tests**, **26 admin tests /11
suites**, **15 chat-lab tests**, mypy **437 files**, formatting/lint/typecheck,
production UI build and zero npm vulnerabilities. One skip and two excluded live
tests are not passes. Sequential OpenAPI/schema synchronization passed unchanged.
Logs: `output/family-parallel-{focused,verify,schema}-20261026.log`.

Actual Chromium -> API -> SQL exercised coalesced battery first contact, a 90-day
fake catalog quote and explicit reminder confirmation in one chat. It retained
one safety job and one scheduled reminder, **750 simulated parent /150 safety
tokens**. Reload and actual server restart preserved every cell in **56 family
and 15 source tables**; no external request, grant or actual push was made. The
390px screenshot was inspected without overflow/script errors. Three CLI text
waits guessed the wrong literal labels (`12%`, a confirmation button and "saved")
and timed out. SQL/browser showed completed qualified source text, the existing
text-confirmation flow and "scheduled"; those waits are not passing checks or
product failures. The final actual confirmation/restart used the observed text.
Evidence: `output/family-parallel-browser-20261026/`.

No paid model party is repeated for this scheduler-only change. The earlier
catalog diagnostic remains negative with its original unknown source hold.

## Exact packaged checks

Clean source **fc4846a** built `mana-ai-family:parallel-local-20261026`, ID
`sha256:e547de3be43d4a8e222af2bdef1e6b36ad02446515c42f25f9c1dc36fa1f2f2b`.
All **274 Python application files** match that `git archive`; no `.env` or private
SQL is in the image. Its source export is outside the checkout at
`/mnt/ssd2/mana-family-parallel-source-fc4846a`. The digest identifies this actual
build, not a guarantee about later builds from a mutable base tag.

- Networkless Python 3.12 ran the two-fictional-family worker story. Parent 456
  completed one 150-token simulated reply while parent 123's fake safety model
  was blocked. Graceful shutdown/reconstruction retained **all 56 tables** and
  the **612-token unknown safety hold**, with one fake model attempt and no replay.
- The first probe omitted required profile `limitations`, so ownership/context
  validation correctly refused the fixture before inference; its wait timed out
  and the unclosed harness produced shutdown noise. The original script/log
  remain. The corrected complete fixture prevalidates before starting the worker;
  application validation was not relaxed.
- The actual preceding **1ab7afe** image's closed v21 reader observed the new
  fixture, returned the two messages and preserved every cell/unknown hold. This
  checks old-image **closed observation**, not full old-image execution rollback.
- The current image's production factory explicitly enabled parallel processing
  against the retained October-25 production-v6 copy, locally with synthetic keys.
  It migrated 6 -> 26, retained every original cell/column in 16 tables, two
  messages and exact legacy replay. Live/history/directory/replay were 200;
  missing auth 401; lab-card path 404 and absent from public OpenAPI. Independent
  worker tasks were live and **zero external attempts/historical captures** were
  observed. The current closed v26 profile retained the complete resulting state.
  No new server copy or SSH was needed.

Evidence: `output/family-parallel-candidate-20261026/` (0700); SQL artifacts 0600.
No key, private database or diagnostic output belongs in Git/images. These small
fixtures are not population load, real-source/model quality or release acceptance.

The full agent objective remains open, including supported commercial/referral
contracts and broader source/model/capacity/administrative acceptance; Technical
remains last. Production, keys/SSH, real grants/contacts, sources and schedules
are unchanged by this local increment.
