# Operational workspace release record — 2026-10-12

Superseded for active versions by the
[2026-10-13 manual analytics release](operation-manual-analytics-release.md).
This dated record remains evidence for the previous release; its version and
source-activation statements are not the current deployment state.

Application revision: `9020b060979ff8546da7758948f8fcaa1a55e203`.
At publication this report superseded the old server release record for operational API/UI only.

## Actual versions and scope

- Operational API/single in-process Goals worker: `mana-ai-operation:9020b06`,
  image `85cd2623314d289569206fd5e758be3e9e049391bf36c85faf9ea05a00ec6f00`.
- UI: `mana-ai-admin:9020b06`,
  image `c15e855d7f0b75f0478f86f993dc4206f9a755c76496d528ff945d0af9fc4360`.
- Main API/audio remains `mana-ai-backend:e73c10a`; scheduler remains
  `mana-ai-operation:2ea7b9a`. Their container IDs, start times and configuration were retained.
- PostgreSQL container retained; schema remains `a36d9f7b802c`. No new migration, downgrade,
  restore, source scan, source activation, schedule change or key deletion was performed.
- The exact working backend dependency base `737b75d` was reused after the standard build's
  PyPI download timed out. Dependencies did not change; application/migration/script sources
  come from the clean Git archive. New UI was built from the same archive.

The released reader can load scoped minimized SQL reports contiguously, 4000 characters per
page/32000 per report, without silently losing the tail or charging another source collection.
Full reading is not full population coverage, current freshness, verified payments or proof
of improved retention. All four rooms and existing domain boundaries remain unchanged.

## Evidence

817 backend/127 UI checks and full `make verify` passed; 14 isolated PostgreSQL cases and
the native browser full-page/review/reload/owner/CSRF/accessibility flow passed separately.
Actual networkless current/`2ea7b9a` rollback checks retained v8 text, existing holds and
consumed source work; old readers cannot execute it. No test suite called a real provider.

After transfer/backup/drain, only the sidecar and admin containers were replaced. Both healthy;
public frontend returned 200 and API readiness `ok`, audio moderation `ready`. Configuration
and source/schedule/control/budget snapshots and SSH/Nginx checksums matched the prior state.

One bounded production historical diagnostic completed in five GPT-6.1 Sol/medium calls:
`read_saved_report` → `read_saved_report_page` → planning/investigation/independent review.
Recorded cost estimate **$0.079515**, unknown holds **zero**, new source requests **zero**.
The already saved, dated MANA Parent report is 523 characters; multi-page exact-tail correctness
is separate fake/SQL/browser evidence. Public private-receipt/model-continuation fields remained
absent; SSE's first frame arrived in 0.170 seconds. The initial current-conversion objective from
the prior release was not narrowed or completed by this separate historical diagnostic.

The real-model check is not broad statistical quality or current cohort/payment availability.
Do not replay its exclusive marker or automatically retry lost model/source reads.

## Protected records

Source/images/config: `/opt/manaai-releases/9020b06/`.
Backup/audit: `/var/backups/mana-ai/report-pages-9020b06/` (root-only).
Custom PostgreSQL dump verified by `pg_restore --list`, SHA256:
`91091d8a1e4db0590ff128093ec01b0e5708f1763709995fb82d3ef0e85241f6`.
Prior release record and full container/config snapshot are retained. This is not a
destructive production restore/rollback drill.

## Exact operational definitions

Sidecar uses these files, in this order:

```sh
docker compose \
  -f /etc/manaai/deploy/operation-release-a871ddf.yml \
  -f /opt/manaai-releases/737b75d/kit/native.yml \
  -f /opt/manaai-releases/9020b06/kit/operation-upgrade.yml ps
```

Main project retains its old base/guards/worker definitions, with UI image overrides last:

```sh
docker compose --project-name mana-ai \
  --project-directory /opt/manaai-releases/e73c10a \
  --env-file /opt/manaai-releases/e73c10a/.env \
  -f /opt/manaai-releases/e73c10a/docker-compose.yml \
  -f /etc/manaai/deploy/manaai-operation-e73c10a.yml \
  -f /etc/manaai/deploy/retention-worker-enabled.yml \
  -f /etc/manaai/deploy/worker-admin-a871ddf.yml \
  -f /opt/manaai-releases/737b75d/kit/admin.yml \
  -f /opt/manaai-releases/9020b06/kit/admin-upgrade.yml ps
```

Use only the explicitly selected operational or admin service when changing it. Never
issue a whole-stack `up`/`down` or recreate the existing scheduler/main API/audio/PostgreSQL.
Original environment/secret files are still required; do not display or overwrite them.

## Application rollback

The previously released native `737b75d` reader cannot decode v8. It is **not** an automatic
rollback target once v8 history exists. The verified fallback is `mana-ai-operation:2ea7b9a`
with Goals/workspace execution disabled, paired with the recorded pre-native UI `a871ddf`.
Keep all current source guards and additive schema; never run old Alembic or downgrade.

Follow [the stop/drain/inspect/pause procedure](operation-agent-workspace-release.md), using
the current release's rollback tool. Retain every native checkpoint, full text, original user
condition, consumed approval and unknown cost hold. Append the existing protected
`/opt/manaai-releases/737b75d/kit/rollback.yml` for the old sidecar; update **admin only** to
the recorded old image. The native flag is disabled, never permission to resume unknown work.
Rolling forward uses a compatible image; paused Goals resume only by owner controls.

Source ownership/GA4 binding acceptance, broader real-model quality, extended work and the
remaining owning-domain actions are still open under the canonical product direction.
