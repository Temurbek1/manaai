# Professional UI-only production release

Verified 16 October 2026 in Samarkand (15 October UTC). The owner explicitly approved
**UI only**, from a clean production baseline, after checks and with backup/rollback.
This is an interface increment toward the shared agent workspace, not completion of
the broader Codex/Claude-like agent objective or new domain-action acceptance.

## Released artifact and unchanged services

- UI code: `faf0a78ed7320da963ebc702da68000d0e6838bd`, branch
  `release/professional-ui-20261015`, pushed to origin.
- Clean parent: production `38cdac4`. Only the professional UI delta from `9c977ad`
  plus its synthetic UI fixtures/browser/smoke checks was applied. No private contact
  pages, controls, backend code, migrations or unfinished admission work was included.
- Active UI: `mana-ai-admin:faf0a78`; server image ID
  `7cbf944e7756889cc69f437b08468e65dc6c4cc814f7d2c03f375d1b45050edc`.
- Operational API/its Goals worker remains `38cdac4`, preserving profile `6babf75`.
  Main API/audio remains `e73c10a`; independent scheduler/worker remains `2ea7b9a`.
  PostgreSQL and schema `a36d9f7b802c` are unchanged.

The transferred image archive SHA-256 is
`452d9d98547af4b107c982bdac6b4b47af105b4a42a2ffb4669535f73b91007a`;
the tracked UI-source archive SHA-256 is
`27d376e187159736795cf2f3262d7f0e3940f52ad5e7c0419dd093259391e142`.
Loading between Docker engines normalized legacy empty/default image metadata,
so the local image ID differs. All eight filesystem layer digests and the runtime
user/environment/command/working directory/labels/ports/healthcheck/entrypoint/signal
matched after transfer. No `.env` was copied into the source archive or image.

## Visible behavior and data boundary

[Professional analytics](https://ai-frontend.360rec.uz/analytics) now has a compact
light admin layout, grouped navigation and separate saved GA4 parent-activity,
Firebase child-telemetry and Parent API account views. Chat stays the default;
Russian and Uzbek Latin, mobile layout and existing controls are preserved.

The screen uses only existing authenticated SQL report GETs, at most five saved
reports per source, without focus/reconnect refresh, polling or transport retries.
Selecting a source/window is local; **Refresh screen** reads the saved SQL list,
not Firebase/GA4/Manakids. No new provider read, model call, listener, source flag,
schedule, approval, OTP, customer contact or Goal restart was issued by this release.

Actual production proxy checks before and after switching returned HTTP 200 for:

| Saved source | Total saved reports at verification |
| --- | ---: |
| `retention.parent_activity.analyze` / GA4 | 0 |
| `retention.child_telemetry.analyze` / Firebase | 1 |
| `retention.parents.analyze` / Parent API | 1 |

Returned reports passed their existing MANA/source/population contract checks.
GA4 therefore correctly shows no saved report, not invented zeros or automatic
collection. This is not a finding that GA4 itself contains no activity. Parent
analytics identities, parent accounts and child-device samples remain distinct;
tariffs are not payment proof, and samples are not full-population measurements.

## Checks and acceptance limits

The isolated release worktree passed `make verify`: **1241 backend tests**, **181
UI tests /26 suites**, Ruff/format/ESLint, mypy (350 files), TypeScript, production
build and npm audit with zero vulnerabilities. Twenty-three PostgreSQL cases were
skipped in this SQLite run; two real-provider cases were excluded. No backend/schema
change was released and no live provider was used by tests.

Two isolated fake-backend browser runs passed: the production-like native workspace
profile and the ordinary admin workflow, both including the three analytics views,
saved GA4 windows, RU/UZ persistence, 320px layout and axe checks. Native checks also
covered Goals, result/history reload, bounded catalog paging, long-topic conditions,
scoped sandbox review, owner/CSRF protection and unknown-reply handling. Analytics
browser reports were intercepted synthetic fixtures, never production data or seeds.
Desktop/mobile screenshots were inspected. This is not broad real-model quality,
real contact delivery, live GA4 collection or business improvement acceptance.

After browser cleanup the production build/types/format, standalone smoke and client
bundle scan were rerun. Generated API contracts byte-matched the committed production
baseline. Schema generation explicitly used the clean worktree `PYTHONPATH`, avoiding
the shared editable installation; SSD `TMPDIR` avoided the host `/tmp` quota. Earlier
failed harness checks are retained, not reported as successful acceptance.

The actual transferred image ran first as a bounded localhost-only canary. Health,
CSP, login protection and authenticated existing-report/chat/Goal GETs passed through
its unchanged proxies. Rendered Compose differed by exactly the admin image field.
Only `admin` was recreated with `--no-deps --no-build --pull never`; all other
containers retained exact IDs, start times, mounts, environments and host settings.
The new UI also retained its old environment/mounts/host settings.

Public production Chrome passed login protection on `/analytics`, RU/UZ reload,
320px layout, axe and no browser errors. Same-origin stylesheet inspection confirmed
the newly served professional/analytics CSS. Curl returned 200; an additional default
Python urllib probe received an edge Cloudflare 403 and is not counted as a pass.
No WAF/security configuration was changed. Authenticated production checks used the
existing technical read key, kept inside the server, not a bypassed human login.
Authenticated human production-browser analytics acceptance remains separate from
the local fake-browser and actual production API evidence.

## Protection, backup and rollback

Root-only release kit: `/opt/manaai-releases/ui-faf0a78/kit/`.
Root-only backup: `/var/backups/mana-ai/professional-ui-faf0a78/`.
It retains the original UI/container inventory, rendered Compose, configuration
copies/hashes and the previous UI image archive `admin-38cdac4.tar.gz`, SHA-256
`a7f21e1dfefe6c83ef14ce1089ab3e1f0ee2721da8ccef969c1a261369f0c116`.
There was no database migration, restore or schema downgrade; this UI rollback
does not require restoring user data.

All **40 original configuration/document/credential/SSH/nginx files** matched their
protected hashes after deployment and canary cleanup. The fresh immediately-before/
after SQL fences matched: seven capability configurations, six schedule rows, two
source gates and controls; all **eight Goals** and **three unknown holds** retained
exact fingerprints. No queued/running Goal, active source run or active chat turn was
present at the switch. The existing scheduler remained running throughout; its earlier
natural scheduling timestamps were not restored or treated as a UI configuration edit.

The exact UI Compose files are retained in the old UI inventory. The active override
is `/opt/manaai-releases/ui-faf0a78/kit/admin.yml`, appended last. The companion server
record is `/etc/manaai/deploy/ACTIVE-UI-RELEASE.md`; older release records are historical.
For an explicitly requested UI-only rollback, inspect current state then use:

```sh
python3 /opt/manaai-releases/ui-faf0a78/kit/deploy_ui.py rollback
```

It targets the previous healthy `mana-ai-admin:38cdac4` through the exact original
Compose chain, only `admin`, without building/pulling or touching backend/DB/nginx.
The rollback image/configuration were verified and retained; no deliberate public
rollback/roll-forward drill was performed. Exclusive dispatch markers prevent blind
repeating of deploy/rollback; after a lost observation inspect the same containers.
The temporary mount-free canary was stopped and removed; no customer data was removed.

Engineering receipts are ignored under `output/professional-ui-release-20261015/`
and `output/professional-ui-release-*.log`. Private local contact/admission development
remains separate, unfinished and undeployed; this release grants it no authority.
