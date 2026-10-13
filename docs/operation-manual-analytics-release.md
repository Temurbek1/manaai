# Manual analytics operational release — 2026-10-13

API/UI versions below are superseded by
[the confirmed Goal-continuation release](operation-goal-limit-release.md).
Source outcomes, cooldowns and the outstanding fresh GA4 acceptance remain as recorded here.

This record supersedes [the 2026-10-12 versions](operation-agent-workspace-report-pages-release.md)
for operational API/UI only. The owner approved connecting confirmed sources on
production; the prior prohibition of automatic refresh remains in force.

## Versions and boundaries

- Operational API / single in-process Goals worker: `mana-ai-operation:38292de`,
  application revision `38292defee188210c3c42f1bb09a4b2ab587a64e`, image
  `9855a8ba6fefb61a061b1d13a431acea5d3c5ebb975e8404231aa571383154cb`.
- UI: `mana-ai-admin:04048d7`, revision
  `04048d721356665347975465ef75feb5359c806d`, image
  `aa6bae579c90bd3e5df6312160d318fc4b4408975ea1f5e6e220bd965401fe15`.
- Main API/audio: unchanged `mana-ai-backend:e73c10a`; existing scheduler:
  unchanged `mana-ai-operation:2ea7b9a`; PostgreSQL and schema `a36d9f7b802c` retained.
- Three protected container IDs, start times, configuration and mounts matched
  the pre-release backup. All 19 original configuration/credential/environment/
  SSH/Nginx files matched their SHA256 values. No migration, restore, key removal,
  SSH authentication change or Firebase data/IAM mutation occurred.

The sidecar explicitly enables the two otherwise default-disabled manual
capabilities. GA4 binds only property `424940486`, parent Android stream
`8216695933`, timezone `Etc/GMT-5`; child telemetry binds owner-confirmed MANA-only
`battery` and `children_location`. A new private read-only credential mount was
added without overwriting the original key or `.env`. No new schedule/listener/
scan/pagination/transport retry was added; the sidecar scheduler is disabled.

Validated minimized SQL reports can inform all MANA rooms. Source approvals and
budgets are not shared. Parent behavior and child telemetry remain separate;
360REC receives neither report. This does not implement the full Orchestrator,
Technical Reliability or the remaining owning-domain action families.

## Checks and real-source outcomes

Final code verification: **881 backend / 127 UI tests**, lint, format, typecheck,
build and dependency audit passed. Sixteen isolated PostgreSQL cases, native
browser regression and actual networkless `2ea7b9a` / deployed `38292de` image
compatibility checks passed separately, preserving private v9, unknown holds
and paused Goals. Automated tests used no real model or data provider.

Authenticated public-proxy API checks and production health passed; frontend
returned HTTP 200 and independent main API reported audio moderation `ready`.
Availability advertises the two scoped MANA read tools; their schedules are empty.
An authenticated deployed-browser test of the exact new approval interactions is
still outstanding; existing fake browser tests/API checks are not that proof.

### Firestore: live collection passed

Run `fc873947-f7d7-4fe3-95c5-f233dff016af`; saved report
`f1df00b3-eb6c-40f9-a221-0459198c9d18`, collected 2026-10-13 12:24:09 UTC.
Exactly two collection requests, 100 documents each, plus one OAuth request.
No continuation page was followed; no coordinates or document IDs were saved.

Battery: 99 valid fields / one invalid; 17 stored values ≤20%; all 100 client
timestamps lack usable time/timezone. Location: 100 valid coordinate observations;
six pass the recent, non-mock, accuracy ≤100 m quality filter. These are prefix
samples, not 200 unique children, full-population statistics or current device state.

### GA4: access passed, corrected publication needs another manual acceptance

Run `f7fad8dd-bfb8-47b9-8c01-68a3ec69e2ad` failed while parsing acquisition groups
after **four successful GA4 responses and one OAuth response**. Normalizing
unknown/whitespace labels produced ambiguous groups; strict validation refused
publication. There is no successful saved parent report from that collection.

Revision `38292de` withholds every ambiguous group with explicit partial coverage;
it never sums distinct users or silently keeps the first duplicate. Dedicated
duplicate/sentinel/whitespace tests passed. The local parser circuit was cleared
in one guarded transaction with audit event
`manual-ga4-parser-circuit-repair-38292de`; its exact binding, failed run, settled
costs and six-hour cooldown were retained. **No failed source read was retried.**

Earliest separately approved manual GA4 refresh: **2026-10-13 18:13:15 UTC /
23:13:15 Samarkand**. The Firestore gate is separately held until 18:24:08 UTC.
These are admission times, not scheduled jobs. Fresh corrected GA4 publication
and the fifth report-batch path remain unverified against production data.

### Native Goal: real saved-evidence analysis passed

Using the existing registered administrator and normal technical-key authentication
through `https://ai-frontend.360rec.uz`, a native Orchestrator-room Goal assessed
the already saved child-telemetry report. No session/auth setting was fabricated.

Goal `1f4f0296-859e-4584-aaa9-2ad470b07774`, topic
`127aca2e-b00f-4feb-91a9-f7cc072b374c`: completed at 12:43:20 UTC in four
`gpt-6.1-sol` model steps, including full saved-report load, analysis and independent
review. Budget $0.45; accounted estimate **$0.069386**; new source reads **zero**;
no read approval or customer/provider action. Unknown global cost receipts: zero.

The result correctly separated observation freshness, device measurement time,
children and parents, and warned against population/payment/retention claims.
It also identified that the report text does not spell out the GPS recency cutoff
or exact validity rules. The adapter currently requires both server/client GPS
timestamps within six hours; improving explanatory metadata is a follow-up, not
a fact retroactively added to this saved report. One successful narrow Goal is
not broad model-quality acceptance or complete Codex/Claude parity.

## Costs — estimates, not invoices

This release's collection ledger has eight known provider receipts: two OAuth,
four GA4 and two Firestore; **200 document reads**, no unknown receipt or retry.
Under the configured rate card, Firestore document/body transfer estimate is
**$0.000135**. GA4 reporting has no per-request monetary charge; quota and OAuth
accounting are separate. AI verification cost above is additional.

The [planning calculation](../output/pdf/mana-data-availability-20261012/cost-forecast.md)
reserves ~$0.000369 per capped child collection including response-body headroom.
Four hypothetical collections/day: ~$0.00148/day, $0.0443/30 days, $0.539/365 days
for those reads/body transfer assumptions, not the full Cloud bill. **No automatic
collections are running**, so this is not an enabled recurring expense. Model
cost depends on Goals; the four-step example is not a full-analysis price guarantee.

## Protected backup and exact service definitions

Backup: `/var/backups/mana-ai/manual-analytics-04048d7/`, root-only, including
original container/configuration records. Custom PostgreSQL dump verified by
`pg_restore --list`, SHA256
`460ea0317b5480f3e9e88e29bece6dc1c732cefe2c93cc3f9ee571e63a834eff`.
Release material: `/opt/manaai-releases/04048d7/` and `/opt/manaai-releases/38292de/`.
Local sanitized checks: `output/manual-analytics-release-20261013/` (ignored).
Protected originals contain credentials; never print or commit them.

Sidecar definition, in order:

```sh
docker compose \
  -f /etc/manaai/deploy/operation-release-a871ddf.yml \
  -f /opt/manaai-releases/737b75d/kit/native.yml \
  -f /opt/manaai-releases/9020b06/kit/operation-upgrade.yml \
  -f /opt/manaai-releases/04048d7/kit/operation-manual.yml \
  -f /opt/manaai-releases/38292de/kit/operation-collision-fix.yml ps
```

Admin retains the exact main-project definitions recorded in the prior release,
adding `/opt/manaai-releases/04048d7/kit/admin-manual.yml` last. Change **admin only**;
for the sidecar change **operation-chat only**. Never issue whole-stack `up`/`down`
or recreate the main API/audio, existing scheduler or PostgreSQL.

## Application rollback and remaining work

Private new-source Goal state uses v9. Previous native readers `9020b06`/`737b75d`
are not compatible fallback executors. The verified fallback is `2ea7b9a` with
Goals/workspace execution disabled, paired with recorded pre-native UI `a871ddf`.
Preserve additive schema, source gates, consumed approvals, full private state
and unknown holds. Follow the existing
[stop/drain/inspect/pause protocol](operation-agent-workspace-release.md); no
database downgrade or destructive production rollback drill was performed.

Do not bypass cooldown, reuse old read grants or automatically repeat the failed
GA4 collection. Complete fresh GA4 publication and exact deployed-browser approval
acceptance with separately scoped manual checks. The broader active workspace
objective and canonical owning-domain implementation sequence remain open.
