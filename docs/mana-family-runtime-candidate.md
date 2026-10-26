# Family runtime candidate — local verification, 2026-10-26

The event-to-chat system has a clean, reviewable packaged artifact. Production
remains the last confirmed family release `f8d095e`; this work performs **no
deployment or source activation**. The full original goal remains open, including
referral/rewards, supported proactive commercial targeting, broader source/model/
fleet acceptance and administrative owning-domain actions. Technical remains last.

## Exact artifact

- Source: `29c9c302f850443baab4e66f6b32de0249acd0a5`.
- Image: `mana-ai-family:runtime-29c9c30-candidate-20261026`.
- ID: `sha256:7f862707fcbc212aba5c37f3ebb1351bb1ece33750b6555d8ac87390970d3f23`.
- A clean `git archive` supplies the context, not the dirty operational workspace.
  The manifest retains the archive hash and exact source commit.
- All **271 Python application files** in the image match that export. There is
  no `.env`, private SQL, customer history, actual credential or output in the image.
- Build uses `Dockerfile.mana-ai` and pinned application requirements. This ID
  identifies the actual build; the mutable `python:3.12-slim` tag does not promise
  that a later rebuild has the same base image or resulting digest.

Private evidence: `output/family-runtime-candidate-20261026/`, mode 0700. The
migrated SQL artifact is mode 0600. Do not publish these files or send private
SQL/history to a model. Attestations: `source-manifest.json`, `image-source.json`
and `image-attestation.json`.

## Production-factory migration and HTTP

The already protected **October-25 consistent production-v6 copy** was reused;
no new SSH session, remote backup or live database query occurred. The exact
candidate ran its real production FastAPI/runtime factory with networking disabled,
read-only root, non-root UID 1000, dropped capabilities and tmpfs working storage.
Original SQL was mounted read-only. Credentials were newly fictional, including
a temporary synthetic Google signing key. A deny transport observed zero external
provider attempts.

An explicit full native manager/source/reminder/Retention/Upsell/dated-usage/GPS
profile migrated the copy **v6 -> v23**. All original cells/column fingerprints in
**16 tables** survived, including two messages, original request digest and quota
state. No historical turn acquired manager/source/action capture. New grant/
period/contact/source work stayed empty.

| Local HTTP boundary | Result |
| --- | --- |
| Liveness | 200 |
| History without the isolated backend token | 401 |
| Existing history with a fictional isolated token | 200; original two messages |
| Agent directory | 200; Parent-Touch, Child-Safety, Parent Assistant, Retention, Upsell |
| Exact historical chat replay, after original digest equality | 200; original normalized response |
| Lab-only action-card path on the product factory | 404 |

Product OpenAPI has no action-card path. Lab v24/v25 actions are exercised
separately below, not exposed as production/mobile contracts. The current closed
v23 reader returned identical history and retained every table fingerprint. This
small real-history copy is not fleet/load or working old-image rollback acceptance.
Log: `production-copy.log`.

## Packaged button lifecycle — fictional only

The same image's **Python 3.12** ran the full HTTP/SQL story in two independent
fictional fixtures: known one-time success and lost acknowledgement. Only scripts
and UI assets from the same clean export were mounted read-only; application
imports came from the verified image. No real key, customer, grant or model was
available, and the network was disabled.

Each party covers event admission (`202`) -> one assistant offer/card -> explicit
bound click -> existing owning grant claim/executor -> dated same-chat receipt.
Each has two assistant-only messages, zero model tokens and one fake gateway call.
Exact replay, closed v25 observation and reconstruction retain every row;
restart performs **zero** gateway calls. Unknown results remain unknown. This
checks populated new trial tables, not just empty v25 migration.

Preserve the two initial harness failures: the first inherited production Telegram
auth defaults into the lab's fake SDK settings and failed before the story; the
explicitly isolated run then caught an assertion expecting `200` where the actual
documented event contract returns `202`. No product permission/HTTP contract was
weakened. The corrected probe uses the isolated sidecar's Telegram-disabled context
and exact `202`; its original process exited 0 in `packaged-trial-contract.log`.
The earlier logs are not passing runs.

## Code/browser evidence and release boundary

This application commit's full gate is the previously recorded
`output/trial-action-cards-20261026/verify.log`: **1527 backend tests**, **26 admin
tests /11 suites**, **15 lab tests**, mypy **432 files**, lint/format/types/build
and zero npm vulnerabilities. One skip and two excluded live tests are not passes.
Schema sync passed. The actual browser's same-chat/lost-response/restart checks
and limited fake 90-day enquiry are in [the card checkpoint](mana-trial-action-cards.en.md),
including its negative 30-day simulation qualification. Packaging is not model
quality or business-outcome acceptance.

A separately scoped release still needs frozen sidecar settings, private credential
mounts, active features, current recipient/source authority, cost ceilings, route/
Swagger plan, backup and compatible closure. New native dated preparation requires
an explicit 360-second lease; parent **2000 raw tokens/day** and global safety
**2000 raw tokens/day** must not increase. Source/collector/contact activation is
not implied by factory migration. Bulk windows remain 09:00/15:00 Asia/Tashkent
when separately activated, never an hourly scan or replay of old occurrences.

Main API/audio, OPERATION services, existing UI, SSH and keys remain outside this
family release. Current closure preserves new state; old v6 cannot execute
populated v23/v25. Never downgrade or restore an old database over newer history.
A fake gateway, directory entry, passing copy or clean image does not complete
the full original agent objective or prove real business improvement.
