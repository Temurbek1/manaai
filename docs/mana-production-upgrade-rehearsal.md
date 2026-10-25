# Production family copy: v6 -> v21 rehearsal — 2026-10-25

The latest application remains the committed local `ced2964` Parent-Touch manager
checkpoint. This rehearsal uses the real deployed database shape/history on a
private consistent copy, through the actual current image and HTTP factory. It
closes a migration/compatibility evidence gap; it does **not** deploy that image,
enable sources, finish the full agents objective or approve a release.

## Current production observation

Read-only Docker inspection confirmed all six existing containers healthy, with
the same IDs/start times/images as the previous release records:

| Component | Actual image |
| --- | --- |
| Isolated parent chat | `mana-ai-family:review-first-fenced-20261020`, application `f8d095e` |
| Main API/audio | `mana-ai-backend:e73c10a` |
| Operational API/Goals worker | `mana-ai-operation:38cdac4` |
| Professional UI | `mana-ai-admin:faf0a78` |
| Independent operational worker | `mana-ai-operation:2ea7b9a` |
| PostgreSQL | `postgres:17-alpine` |

The parent sidecar's actual configured SQLite path is
`/app/data/mana-parent-chat.sqlite3`; do not substitute `/data/...` from a guessed
mount convention. The first copy attempt used that obsolete path and failed in
read-only mode before opening a source database; its original log is retained.
The distinct corrected attempt derives/checks the actual inspected setting.

SQLite opened the active file with `mode=ro`, backed it into **remote memory only**,
then serialized the consistent **217088-byte** copy over the existing SSH session
to a local exclusive mode-0600 file. No backup/configuration file was created on
the server, no service was stopped, and no raw history or credential was printed.
Both remote/local ceilings were 8 MiB. `quick_check` returned `ok`, schema **6**,
with one historical chat turn/quota row, no safety jobs/events or reviewed-message
rows. This small actual state is not a load or populated-native-history fixture.

Raw SQL and configuration hashes stay private under
`output/production-upgrade-rehearsal-20261025` (mode 0700; files 0600), outside Git,
images and public documentation. Do not send this history to a paid test/model or
repeat the copy merely to get a more convenient receipt. Reuse the existing copy
for a new justified offline verification. The temporary owned SSH control session
was explicitly closed; server authentication/configuration was not changed.

## Actual candidate and HTTP flow

The current candidate is
`mana-ai-family:parent-manager-v21-final-20261025-local`, image
`sha256:4422280bffcaaa51ce5e0cf0332251db46815318b7a5d6bdf3d348e2f3f3dda4`.
The exact image ran with **network disabled**, read-only root, UID/GID 1000 and
tmpfs working storage. The original consistent SQL copy was mounted read-only.
The only Google/provider/backend credentials were newly fictional test values;
the synthetic signing key existed only in tmpfs. No actual production keys were
mounted or copied into an image.

The production FastAPI factory and real Parent-Touch runtime were exercised with
an explicit full manager/source-review/reminder/Retention/Upsell/day-usage profile.
Collection, push, free grants, commercial offer activation and proactive contact
were not enabled. Empty approved commercial offers are not replaced by a fake
production offer. A deny transport additionally recorded/refused any unexpected
provider request; its count remained **zero**.

| HTTP boundary on the local copy | Result |
| --- | --- |
| Container liveness route | 200 |
| History without backend authentication | 401 |
| Single Parent-Touch history with fictional isolated backend token | 200; both historical messages retained |
| Agent directory | 200; Parent-Touch, Child-Safety, Parent Assistant, Retention, Upsell wired |
| Exact historical `/mana-ai/chat` request, reconstructed only after stored digest equality | 200; exact normalized saved response, no generation/source call |

All original cells in **16 old tables**, including history, request digests,
quota state and sequence, retained their original fingerprints through **v6 ->
v21**. Nothing was recaptured as a manager/safety/reminder/offer admission.
`quick_check` remained `ok`. The current closed v21 reader returned the same two
messages and retained every new/old table fingerprint. Original production was
not migrated, written, replaced or downgraded.

New native day-usage preparation needs an explicit **360-second SQL lease** for
the default 30-second SDK timeout plus its bounded model/source steps; keeping the
old 300-second lease with all dated features fails configuration validation.
This future-profile timing choice is **not applied to production**, alters no
old task capture and leaves **2000 raw Parent-Touch tokens/parent/day** and **2000
global Child-Safety tokens/day** unchanged. It is not a capacity increase or a
guarantee that every complex question fits those very small financial limits.

The original probe session **2653** exited **0**. Receipt:
`output/production-family-upgrade-http-20261025.log`; private upgraded artifact:
`output/production-upgrade-rehearsal-20261025/artifacts/production-upgraded-v21.sqlite3`.
The historical code gate remains `ced2964`'s passing **1456 backend /26 admin /
10 lab** `make verify`; this increment changes documentation/evidence, not the
application or test code. No new paid-model quality pass is claimed.

## Release and rollback limits

After the rehearsal, another actual server inspection matched the original
six-container snapshot **exactly**, including IDs, start times, runtime-config
hashes and healthy states. No deployment/restart, key/SSH change, cloud source
read, contact, grant or payment followed this check.

The earlier v20 synthetic unknown-hold/candidate checks remain separate evidence:
they cover states absent from this particular production copy. The old v6/v20
images are not supported execution readers of a populated v21 file. Current
closed-reader preservation is **not a tested functional production rollback**;
never restore an old database over newer history or downgrade schema.

A separately scoped release still needs its exact configuration/credential mounts,
data/recipient permissions, public ingress/Swagger checks and compatible closure
procedure. Source-wide cost/capacity acceptance, location identity, referral/reward
contracts, autonomous paid targeting, broader model/channel quality and the four
administrative owners remain open in
[the complete active objective](mana-autonomous-agents-plan.md). This rehearsal
must not be used to call the full agent system or live source integration ready.
