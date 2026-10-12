# Native administrative workspace release — 2026-10-12

Historical release record for `737b75d`. It is superseded by
[the active `9020b06` release](operation-agent-workspace-report-pages-release.md), including
its v8-compatible rollback requirements. The checks and costs below belong to this earlier
release and must not be replayed as a new diagnostic.

## Deployment at this checkpoint

The owner approved updating only the operational API/its Goals worker and administrator UI.
Published branch: `feat/operation-admin-20260929`; running application commit:
`737b75d6e3a41f2f78518a1cb40b9b174fb8bf5d`.

| Component | Actual image / revision | Release effect |
| --- | --- | --- |
| Operational API and its in-process Goals worker | `mana-ai-operation:737b75d` | Updated |
| Administrator UI | `mana-ai-admin:737b75d` | Updated |
| Independent main API/audio | `mana-ai-backend:e73c10a` | Original container and start time retained |
| Existing operational scheduler | `mana-ai-operation:2ea7b9a` | Original container, settings and start time retained |
| PostgreSQL | Existing `postgres:17-alpine`, schema `a36d9f7b802c` | Additive migrations only; container retained |

The images were built from a clean Git archive, without `.env` or private files.
Backend image ID: `13d1ca62e7fb5494868b8946c3bad7f6ff084a7a0e8390950de87fbdbb0ab40d`.
UI image ID: `a705c1024f7da60fb1e9c7ded98d6cf2746d83573c7e8f8905f5d753c9098860`.
The rebuilt Python base changes its version/hash metadata; existing application configuration,
credentials, ports and mounts were checked independently and retained.

Production explicitly enables native workspace, SQL progress events, transcript paging,
model continuation, ordinary-answer streaming and the existing typed sandbox review lane.
Repository defaults remain opt-in. Analysis tools remain read-only; the review lane supports
only verified synthetic MANA Growth experiment drafts, not live writes or Retention contacts.
Full Orchestrator/Technical domain handlers remain unbuilt. Exactly four rooms remain.

Existing source bindings, budgets, cooldowns, schedules and kill switches were not changed.
No Firebase/GA4/IAM, SSH authentication or Nginx configuration was modified. API readiness
still reports audio moderation `ready`; no real child recording was sent.

## Checks and bounded production diagnostic

- Fresh `make verify`: 800 backend tests, 127 UI tests, lint/typechecks/build and npm audit
  passed. Thirteen PostgreSQL-only tests passed separately after migration/drift checks;
  two live suites remained excluded from the ordinary fake-provider tests.
- Native real-browser local flow passed: handoff, progress/reconnection, clarification,
  reviewed result, history paging, private-owner/CSRF isolation and accessibility.
- The exact built backend passed networkless startup and supported old/new-image pause
  compatibility checks. These are not a production database-restore drill.
- Public deployed UI loaded without browser errors; unauthenticated protected routes
  returned 401. Existing registered-owner, trusted-key requests through the public UI proxy
  exercised the production native service. No user/session/role was created or forged.
  An authenticated production browser/OTP session was not automated.
- One Mini greeting stayed conversation-only. One Sol/medium native current-conversion Goal
  discovered sources, loaded the already saved minimized MANA Parent report, investigated,
  reviewed, retained the original request and correctly waited for missing current cohort/
  funnel/payment evidence. It did not redirect the administrator to a different room, infer
  payments from tariffs, or complete current conversion from a historical profile sample.
- The same Goal passed pause, explicit resume, steering continuation, idempotent controls,
  saved-state reload and owner isolation. Public model continuation remained absent.
  SSE's first frame arrived through the public frontend in 0.249 seconds; observation did
  not dispatch a task or source read.
- A diagnostic harness initially expected steering an idle paused Goal to keep it paused.
  The established contract queues that explicit clarification; production behaved as its
  existing tests specify. That assertion failure was retained. The existing Goal was then
  observed and explicitly paused/resumed; no replacement Goal or reset budget was used.
- The earlier Python urllib preflight was refused by Cloudflare with error 1010 before any
  generation. Ordinary curl requests succeeded. The diagnostic used curl's actual transport,
  passing credentials through protected stdin; no firewall or browser-signature setting was
  changed. See [Cloudflare's error definition](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/).

The diagnostic had a $0.30, eight-step Goal plus one small greeting. **Nine settled model
calls, $0.155131 by existing rate cards, zero unknown holds, zero new source requests.**
This is recorded estimated usage, not a provider invoice. The original attempt marker and
failed assertions remain protected; do not rerun the exhausted diagnostic or automatically
retry a lost request. The eight-step Goal retained useful partial work in `waiting`, not a
claimed completed business analysis or measured conversion improvement.

## Operations and rollback

Release source/configuration: `/opt/manaai-releases/737b75d/`.
Protected backup and original container/config snapshot:
`/var/backups/mana-ai/native-737b75d/`. The custom PostgreSQL dump was verified with
`pg_restore --list`; SHA256:
`d0824b970325534bf2c32d7e34f66378feade0f3d314ab2a017b2186f70dffa1`.
No schema downgrade or restore was performed.

Active sidecar definitions are the existing
`/etc/manaai/deploy/operation-release-a871ddf.yml` plus
`/opt/manaai-releases/737b75d/kit/native.yml`.
The main project's prior definitions remain, with
`/opt/manaai-releases/737b75d/kit/admin.yml` appended for **admin only**.
Never issue an unqualified whole-stack `up`, `down`, worker or main API recreation.

Application rollback follows [the workspace rollback procedure](operation-agent-workspace-release.md):
stop/drain the single Goals worker/ordinary producers; inspect and explicitly pause native
Goals with the current release's rollback tool; keep every consumed approval and unknown
cost hold. Append the protected `kit/rollback.yml` for the old sidecar with Goals disabled;
restore only the old UI image. Keep schema `a36d9f7b802c` and all native history; never run the
old Alembic head or a database downgrade. Resume paused work only through owner controls.
The running production stack was not rolled back as a diagnostic.

Final SSH synchronization of this report to `/etc/manaai/deploy/ACTIVE-RELEASE.md` was not
confirmed: the copy/interactive connections stopped returning useful output after the
successful deployment and scope checks. Public readiness still returned `ok`/audio `ready`.
Do not use an older server release record to overwrite the new runtime; inspect Docker's
actual Compose labels and consult this repository report. No SSH configuration/authentication
change, whole-stack restart or further authentication loop was attempted to repair the copy.

## Remaining acceptance boundaries

This completes the scoped application release, not unlimited Codex/Claude parity or all four
agents' business actions. Parent profiles are available as saved evidence, but current
conversion needs verified parental events/cohorts and confirmed payments. Unverified
engagement/GA4 bindings remain unverified; no scan, source activation or schedule is implied.
MANA and 360REC remain isolated. Broader model/source acceptance and owning-domain actions
still follow the canonical product direction and separate authority.
