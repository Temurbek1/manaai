# Active operational workspace release — 2026-10-14

The later [RU/UZ language release](operation-interface-language-release.md) replaces the
sidecar/UI images below with `38cdac4`, preserving this profile's flags, limits, sources,
history and schema. The checks below remain historical evidence, not newly rerun model cases.

The owner approved this release after additional checks. This supersedes the
operational API/UI versions in the earlier limit and cohort release reports,
not their source findings, unknown costs or unfinished acceptance. The complete
nine-item objective remains in [operation-agent-workspace.md](operation-agent-workspace.md).

## Actual deployed versions and scope

- Code revision: `6babf75cbac615551fc999e9ceb26b331fb292ff`, clean Git archive.
- API/single in-process Goals worker: `mana-ai-operation:6babf75`, image
  `68016549722db8eead2703940296fe52ff78ab95baeae85425fd1a6402d19e96`.
- UI: `mana-ai-admin:6babf75`, image
  `bdc8ff55c7cb105040c07454ea78b9b8076a305a2ebf61bcebaa768435dfc9c9`.
- Production-only explicit activation of saved-report discovery, exact runtime
  snapshot replacement, duplicate saved-page projection and independent bound
  review verdicts. New eligible tracked native Goals capture private v11–v14;
  old tasks retain their original tools/protocols. Global defaults stay disabled.
- Compaction trigger explicitly **24000**, unchanged 192000-byte model window,
  8192-token output cap, model/reasoning, budgets and human extension ceilings.
  Explicit HTTP/wall defaults remain **120/180 seconds**, SDK retries zero.
- Report rendering now recognizes adjacent headings/body/lists/tables without
  requiring blank lines, escapes HTML and adds no executable links/actions.

Workspace/Goals/its single worker remain enabled in the scoped sidecar with
`APP_ENV=production`; its scheduler remains disabled. No source-refresh mechanism
or permission is implied by a saved-catalog search or a completed historical Goal.

## Protection, backup and activation

Only operational sidecar/its worker and compatible UI were replaced. Main API/audio
`e73c10a`, independent worker/scheduler `2ea7b9a` and PostgreSQL retained their exact
container IDs, start times, environment/configuration, mounts and host settings.
All **35** recorded original configuration/credential/SSH/Nginx/document files
matched protected hashes. UI environment values were unchanged; sidecar environment
changed only the four approved feature flags and trigger. Generated container-ID
hostnames and image/Compose revision annotations were checked separately.

Protected root-only backup: `/var/backups/mana-ai/workspace-profile-6babf75/`.
Verified custom PostgreSQL dump: **1779909 bytes**, SHA-256
`a47ab668c02bad167ebc49cef7318ce0f49f78f3a13f16e226e6419bef39bfbb`.
Its contents were listed for validation, never restored over production.
Release kit: `/opt/manaai-releases/6babf75/kit/`.
Clean source archive SHA-256:
`27009fc335fcb931a088b57d71f84f2e6c5fa180330ba6ba2332eb77daea55d0`.
No `.env` or developer dependencies were packaged. Python dependencies were
unchanged from `a7752dc`; the candidate overlays tested application/scripts and
passes `pip check`. UI uses its locked dependency installation/production build.

Before drain/stage there were zero executing/queued Goals, active chat generations,
source runs or Goal leases. Admission and the Goals worker were disabled while
staging the new backend and UI, then enabled together after compatibility checks.
All **seven** pre-existing Goal rows and all **three** old unknown-cost reservations
retained their exact fingerprints. No old Goal was resumed, cancelled, rewritten
or regraded. The protected lost-review Goal remains waiting with its original
$0.157238 unknown hold; later success does not resolve it.

Schema remains `a36d9f7b802c`. SQL capability configuration, schedules, source gates
and controls matched original fingerprints before/after the release and new test.
No migration/downgrade/restore, Firebase/GA4/Manakids request, listener, cooldown
reset, source configuration/credential change, new schedule, auto-refresh, SSH
change, audio/main API deployment or customer-contact/provider write occurred.

Preliminary release checks rejected a missing UI OCI revision label and overly
literal generated-hostname/environment-order comparisons. The UI was rebuilt from
the same clean archive with the exact revision label. Generated hostnames are now
bound to their actual container IDs and environment comparisons use exact key/value
maps, not list order. All substantive configuration comparisons still fail closed;
the final image/runtime/protected checks passed. These were release-kit issues,
not relaxed application permissions or replayed model requests.

## Engineering and model evidence

The exact application checkpoint passed `make verify`: **1235 backend /168 UI
tests**, Ruff/format/ESLint, mypy 349 files, TypeScript, production build and npm
audit (zero vulnerabilities). Twenty-three separately isolated PostgreSQL17
migration/concurrency cases passed; two live suites remained excluded. Native
browser → API → SQL → fake-model/tool flows passed: catalog/full source, reviewed
report, long-topic conditions, controls/limits, reconnect/reload without redispatch,
questions, explicit historical scope, sandbox receipts, ownership, CSRF and mobile
accessibility. The actual generated full report was separately visually inspected.

A later documentation-only recheck encountered local `/tmp` quota exhaustion:
SQLite disk-I/O failures and Node errno122 (`EDQUOT`, with `usrquota` on that tmpfs).
It is not reported as a passing gate or a production regression. The first targeted
SQLite case passed independently; final full reverification uses a newly created
SSD temporary directory for all child processes, without deleting unrelated files,
changing quota or reducing the suite. An intermediate invocation also rejected an
incorrect temporary-directory CLI spelling before running tests. The final isolated
`make verify` completed successfully: **1235 backend /168 UI**, mypy349, all lint/
format/type/build gates and npm audit zero vulnerabilities. The full suite was not
reduced. Evidence: `output/workspace-profile-release-20261014/final-verify-recheck.log`.
The final read-only production recheck also confirmed healthy scoped/protected
containers, unchanged35 original files, all seven old Goal fingerprints and all
three old unknown holds, unchanged source/configuration/schedule/schema fingerprints,
and zero active Goals/chat generations/source runs/leases.

The actual candidate and actual `2ea7b9a` fallback passed networkless synthetic-DB
v14/v5 read/reconstruction and explicit-pause compatibility on the server, preserving
conditions, full evidence/tail, bound verdict, page provenance, consumed grants,
limits and unknown holds. No production database/configuration was mounted there.

Two independently journaled local real-model long-topic tasks completed the full
original historical synthetic catalog/funnel/payment/retention analysis and bound
review, with manually recomputed metrics: **$0.230380** under diagnostic210/240
and **$0.213756** under production 120/180 timeouts. Unknown holds/source reads zero.
Both used 24000 with zero actual compactions, retained the entire task/first-topic
condition and unchanged hard caps. This is not a randomized cost comparison,
optimal-trigger proof, broad model-quality verdict or current MANA measurement.
See [the full checkpoint](operation-long-session-deferred-checkpoint.md).

## Actual production Goal and public transport

One **new** Goal `97653fcd-eb0e-46dd-ac95-621556adfdb0`, topic
`b079b285-3904-4d51-8d5f-9b58d617a8e9`, was created through the normal authenticated
public frontend proxy using the existing registered administrator and technical
key. An exclusive protected host dispatch journal preceded the API write; no
creation, continuation, read or generation command was reissued.

It requested a full **historical** quality analysis of existing minimized MANA child
telemetry report `f1df00b3-eb6c-40f9-a221-0459198c9d18` and three safe proposals,
with explicit prohibitions on any external read/action, client contact or limit
increase. It completed all four plan positions and independent v14 review in
**five settled calls**, with one existing known-priced format correction:
**$0.083092 estimated**, unknown hold **0**, document reads/data cost **0**.
The $0.45 cap was not increased. Original source grants remain absent.
The independent ledger check selects the exact new Goal time window and closed
attribution, with all old Goals unchanged and only one new Goal; its five settled
rows sum 83092. Ledger attribution has no Goal-ID field, so this temporal audit is
not claimed to add a durable per-Goal reservation correlation contract.

Full artifact and criteria were separately inspected: collection is not sensor
measurement; ranges of server update dates are not continuous observation coverage;
100+100 prefix documents are not 200 unique children or a population; 17/99 valid
low-battery values ≈17.2% is not current device state; 6/100 qualified GPS records
are not general availability. Missing overlap/window/parent/payment/causal data
remain unknown. All three recommendations are proposed-only. No identifiers,
coordinates or call content were exposed. This is child sample quality analysis,
not parent retention or measured business improvement.

Result SHA-256:
`17a0982594fde0ce43caf6ecaf7427c1cd4fa729cc88a5c09d9a8be88f016c99`.
Independent review input SHA-256:
`a7c08bc210ae1b549f1f18cf4ca17cd39ffbd984bb34195e221b9fb4d8eac92a`.
Protected complete public receipt SHA-256:
`1e11c86b45f75a2c4276b587f82687bb21f34aa8a02eea456378ce11f445a6fe`.

Authenticated public availability, owner isolation (foreign actor 404), actual SSE
`text/event-stream` delivery and cursor-based REST replay passed without Goal
commands/source reads. Swagger, main health and frontend health return 200. Public
desktop/mobile login rendered without browser errors or WCAG A/AA violations.
The personal Chrome discovery found no connectable browser, so a real authenticated
**browser** click-through remains open; no cookie/login session was fabricated.
Public-proxy technical-key checks are not claimed to be that browser test.

The three new real-model checks together estimated **$0.527228**, not an invoice.
Each individual verification stayed below the owner-authorized $0.50 threshold.
Production retains three historical unknown reservations unchanged; current success
does not make those old calls free or authorize replay.

## Verified application fallback and remaining objective

`a7752dc` cannot execute new v11–v14. The verified fallback is **closed `2ea7b9a`**
with workspace/Goals/worker execution disabled and compatible pre-native UI
`a871ddf`. The kit includes exact overrides, not permission for an unattended
rollback. Follow [stop/drain/inspect/pause](operation-agent-workspace-release.md)
with the new compatible image first. Retain the populated schema/private state,
costs, consumed approvals and event history; never restore the old dump over new
work or select an arbitrary intermediate native image. Rolling forward does not
automatically resume paused tasks.

This release advances the full requested environment, but does not close the
overall objective: broader model-quality/current-data and authenticated-browser
acceptance and Retention-first owning-domain action families remain incomplete.
Exactly four rooms remain; full Orchestrator and Technical domain handlers are
not declared implemented. Ignored engineering receipts:
`output/workspace-profile-release-20261014/`.
