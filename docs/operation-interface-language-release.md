# Verified RU/UZ language release — 2026-10-14

The owner approved operational API/its single Goals worker and UI only, without new
migrations, source reads, schedules, main/audio/SSH/key changes or Retention contact activation.

## Deployed artifact

- Clean code revision `38cdac47b934e07f7f3dd99687a7facc31ba1600`.
- Operational image `mana-ai-operation:38cdac4`, server image ID
  `a262c23a34a25295a337cd26384569f0573dbe142cb6e9995e6f150e2e53c379`.
- UI image `mana-ai-admin:38cdac4`, server image ID
  `d18b75e93d24ee00e6776a5737730841c13bb133d2fb2c91911951cef539b7ee`.
- Source archive SHA-256 `c9016293dfb76c0091499c785f32433e53abe36cd70de5fd24de4e324c50670b`.
- Transferred UI archive SHA-256 `647525c92050426a37d244f216ebdf2d45d2edd74a6d63798df5aec4810460f0`.

The language-capable runtime advertises `ru/uz`, freezes response language on admission
and passes Uzbek output conditions into new original Goals. It preserves exact requests,
evidence, permissions and old history. See [language contracts](operation-interface-languages.md).
The full goal remains open; this is not Codex/Claude parity or broad Uzbek model acceptance.

## Protection and rollback

Protected root-only backup `/var/backups/mana-ai/workspace-language-38cdac4/` contains
a validated custom PostgreSQL dump, **1813498 bytes**, SHA-256
`661db61029bbdd34a1609a62415c2dd257b8e78d75920a713379002779d29463`.
Release kit: `/opt/manaai-releases/38cdac4/kit/`. No original file was overwritten.

All **37** original configuration/credential/SSH/Nginx/document files matched their
protected hashes. Main/audio `e73c10a`, independent worker/scheduler `2ea7b9a` and
PostgreSQL retained their exact container IDs, start times, mounts, environment and
host settings. Sidecar/UI final environment maps and host settings are unchanged;
only image/revision/Compose annotations and generated container hostnames changed.
Admission was temporarily disabled for ordinary chat, native workspace, Goals and its
worker during replacement, then restored together after matching health/protection checks.

Schema stays **`a36d9f7b802c`**. No Retention contact code/private tables or `b47ea6c9130d`
migration were included in the clean release archive. The separate contact foundation
exists only in subsequent local/repository work, not this deployment.

All **eight** preceding Goal rows and **three** unknown reservations retained exact
fingerprints. Source gates, seven capability configurations, six schedules and controls
retained their fingerprints. No old Goal was resumed/regraded or cost hold refunded.
Catalog/projection/review flags, 24000 compaction trigger, hard caps, timeouts and source
settings from [the preceding profile release](operation-agent-workspace-profile-release.md)
remain unchanged. No Firebase/GA4/Manakids request, auto-refresh, listener, cooldown reset,
customer contact, key edit or SSH access change occurred.

The actual new image and actual **closed `2ea7b9a`** image passed a networkless synthetic
DB read/reconstruction/pause check, including private Uzbek chat metadata, v14/v5 evidence,
conditions, consumed grants and unknown holds. Keep native workspace/Goals/worker disabled
on that fallback and use `a871ddf` UI. Do not choose `6babf75` as a language-metadata reader
or downgrade/restore the populated database. This was not a destructive production rollback.

## Checks and one real greeting

The tested worktree passed `make verify`: **1276 backend /176 UI**, mypy359, Ruff,
ESLint/format, TypeScript, production build and npm audit zero vulnerabilities. The counts
include the separate unexposed contact foundation, not proof that it is deployed. Isolated
PostgreSQL checks passed **24** cases after migration round-trip/drift validation.
API schema sync and secret/quality-marker checks passed. Seven committed fake credential
values were marked explicitly `test-synthetic-*`; no real credential or scanner rule changed.

Local authenticated fake-browser flows passed RU/UZ selection, unchanged drafts, reload,
320px layout, WCAG A/AA checks and the existing chat/Goal/approval/owner/CSRF flows. The
public production login passed desktop/mobile Uzbek rendering, reload persistence, zero
browser errors and WCAG A/AA checks. It was not an authenticated production-browser test.

One short **new** native conversation was sent once through the normal authenticated
public proxy, using the existing registered administrator. An exclusive root-only host
dispatch journal preceded the write; no request was retried. Topic
`e516c8ec-3630-433d-95a2-2f17a197dde2`, turn `0376e013-98a9-4bcb-8a09-701ce84b2458`:

> Salom! Qanday yordam bera olaman?

`response_language=uz`, completed, `plan=[]`, `next_action=none`, no Goal created.
The saved response matched the returned response. One settled model receipt records
**1652 input /55 output tokens**, estimated **$0.001487**, document reads/data cost **0**.
The preflight existing-server upper reservation was $0.186864, below the authorized $0.50
diagnostic limit. This is configured-rate accounting, not an invoice or full language-quality
evaluation. The diagnostic topic is retained; old unknown calls were not repeated.

Final SSH observation stalled on an old client multiplex connection although public health
responded. A fresh authenticated connection confirmed healthy deployed versions, exact
protected state and no active source/Goal work; deployment was **not** reissued. Only the
agent's stale client connection was closed, not SSH server configuration or other sessions.

Ignored engineering receipts: `output/uzbek-release-20261014/`, `output/uzbek-verify-release.log`,
`output/uzbek-browser.log`. Broader source/action, long analytical Uzbek quality and actual
authenticated production-browser acceptance remain open under the original full objective.
