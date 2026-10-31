# Isolated MANA parent-chat production release

The owner authorized deployment and activation on 16 October 2026. This is separate
from the paused OPERATION AGENTS/contact workspace. Its dirty working tree is not
a release artifact.

## Artifact and boundary

The release branch starts at the actual main/audio production baseline `e73c10a`.
It adds only parent-chat contracts, typed service ports, adapters, persistence,
runtime/API wiring, tests, docs and isolated deployment configuration. No operational
domain, private contact migration or contact-preparation admission code is included.
The approved production UI `faf0a78` dependency manifests, licensed bounded-braces
fork and lint compatibility check are reused solely to verify the clean repository
without reviving historical vulnerable tooling. No UI image is released here.

Deploy `Dockerfile.mana-ai` as a separate `mana-parent-chat` Compose project, with
`docker-compose.parent-chat.yml`, a new backend-only token, a private named volume
and loopback `127.0.0.1:18082`. The new token never replaces an existing API/audio
key. Publish only the exact `/api/v1/mana-ai/chat` ingress through the existing TLS
server after `nginx -t`; gracefully reload Nginx. Keep all existing application,
audio, operational, scheduler, UI and PostgreSQL containers unchanged.

The chat has no Firebase/GA4 credentials or mounts, operational database or scheduler.
Only an explicitly filtered fresh MANA Parent API read precedes a new user message.
GET/replay never refresh data. The model remains the configured `gpt-5.4-nano`, not
an implicit upgrade. Default allowance is 2000 combined tokens/day per parent,
with a 512 output cap and reset in `Asia/Tashkent`.

## Release procedure and rollback

Keep the exact image revision/ID, source archive/hash, protected configuration hashes
and original container inventory in a root-only release kit/backup. Never print
provider/backend credentials or put an `.env` in Git, image or source archives.
Generate static public Swagger from the actual chat candidate and prove that its
other twelve paths/components match the unchanged main API's published contracts.
Reuse the existing pinned local Swagger assets. The manifest must distinguish the
unchanged inference runtime from the new chat runtime.

Check local fake gates and the actual image before publishing. A production GET
smoke needs no real parent read. A bounded negative Parent API filter can check
credentials without enumerating customers. A real parent POST additionally requires
an owner/test account's exact ID; never guess or choose a customer family. Synthetic
real-model diagnostics are separate from positive upstream relationship acceptance.

Rollback restores only the prior exact Nginx server contents and docs symlink after
validation/reload. Keep the new private service/history/unknown usage holds intact
for reconciliation. No database restore/downgrade, volume deletion, key rotation,
SSH change, source refresh or restart of the existing stack is part of rollback.

The token authenticates the trusted MANA backend, not individual parents. The backend
must derive `parent_id` from its authenticated session. Child profiles are included;
live telemetry is **not** automatically fetched: minimized dated observations must
be passed by that backend. Disk/backup encryption, history lifecycle, multi-host
capacity and broad model quality are not established by functional smoke tests.

## Execution evidence

The first `e2c71a7` candidate passed clean `make verify` (342 backend, 26 UI tests),
networkless image startup, private-volume/auth checks and one live negative Parent
API lookup. It was started only on loopback; public ingress was not changed.

The first two-call real-model diagnostic retained verified usage: RU 373 input/40
output; UZ 383 input/79 output. Both used the expected language and replayed without
new calls, but the RU answer incorrectly discussed phone calls instead of screen
time. This is **negative semantic evidence**, not a passing quality acceptance.
Its protected SQL/results remain in the first release kit. The prompt was then
given the missing parental-control/device-usage context before a new candidate.
Never rewrite or replay the first diagnostic as a pass.

Public deployment, final candidate and subsequent checks are recorded below only
after they are actually observed.

### Enabled production application

- Application revision: `f2c023fd924bd442e5de4017816068cfe3fefd95`, pushed to
  `release/mana-parent-chat-20261016`. Subsequent documentation/exporter commits do
  not replace the runtime application image.
- Active service: `mana-parent-chat-parent-chat-1`,
  `mana-ai-parent-chat:f2c023f`, server image
  `sha256:6ac767e27554a3c2f0a159a1e2261d07aa2d42478fca608d88aaec8b8ac874ad`.
  All ten filesystem layers and runtime configuration matched the local image;
  loading between Docker engines changed only the normalized image identifier.
- Image archive SHA-256:
  `98063e24464a06d95db817234e433eaadf465ab9a4cf163ed346b4c1e18b8bed`.
  Tracked-source archive SHA-256:
  `2bca4ecd5ff65e896c827c757da39c694fbdd3527e02f14a2534b0a8c1b64528`.
- The final application candidate passed clean `make verify`: **342 backend
  tests**, one skipped/two opt-in deselected; **26 UI tests/11 suites**, format,
  Ruff/ESLint, strict mypy (211 files), TypeScript, build and zero npm vulnerabilities.
  The exporter correction separately passed five focused tests and strict typing.
  No UI image, operational code or migration is deployed.

The second independent two-call diagnostic answered the screen-time question in
the appropriate language/topic: RU 427 input/52 output, UZ 437 input/68 output.
These narrow synthetic observations are not broad clinical, language or model-quality
acceptance. The original negative diagnostic and its costs are retained separately.

After the owner explicitly allowed choosing any database parent, a **single**
one-row MANA Parent API page selected the canary. No Firestore collection was scanned.
A fresh exact-ID source read on the actual service verified its twelve returned
child profiles. Only minimized profile context went to the model; raw parent contacts,
tariffs, media and real child identifiers did not. This verifies one relationship,
not all Firebase ID mappings or behavioral telemetry coverage.

One production-chat message, explicitly labelled a technical check, returned
`Готово`; **738 input +7 output =745 tokens** were recorded against that parent's
daily 2000. It remains in that parent's history: one user/assistant pair. It was
not erased or charged to other parents. Identical local/public POST replays returned
the exact saved response without additional usage. GET shows the same pair/quota.
A consistent private SQLite backup passed `integrity_check`; after restarting only
the new chat service, history, request replay and 745-token accounting persisted.
The store is mode `0600`, on its own named volume, with zero unresolved requests.
One early health assertion ran while that restart was still `starting`; later
healthy checks passed before publishing. This was not an outage of an existing API.

There were **five** paid generation calls across the two synthetic diagnostics and
one positive canary, not across ordinary tests. Their verified usage totals **2358
input/246 output tokens**. Using uncached standard nano rates, the model-token cost
upper estimate is **$0.0007791**, not an exact billing statement; token-count API
fees and account-specific adjustments are not established here. See
[official pricing](https://developers.openai.com/api/docs/pricing). No unknown model
receipts were discarded or retried.

### Public route, protection and integration

GET/POST: `https://ai.360rec.uz/api/v1/mana-ai/chat`.
Swagger: `https://ai.360rec.uz/docs`.
The public endpoint returned 200 for authenticated history and exact POST replay,
401 without a token, and **401 for the unchanged shared inference key**. Existing
public capabilities, main liveness/readiness and audio readiness remained 200/ready.
Backend callers need the newly issued **MANA chat** token; publishing a route does
not configure the separate mobile/backend application's session-to-parent binding.

Root-only credential handoff:
`/opt/manaai-releases/parent-chat-f2c023f/kit/backend-client.env`.
A local `0600`, Git-ignored copy is `.env.parent-chat`; it contains only the chat
URL/token, not the provider key or Manakids password. Never embed it in mobile.
All existing keys, SSH access and API authentication mechanisms are unchanged.

The initial docs switch returned HTML/schema 200, but copied public JS/CSS inherited
the private staging umask and returned 403. Browser verification caught this; it
was **not** a successful rendered Swagger check. A separate corrected artifact uses
explicit `0755` directories/`0644` public files and image-bound asset queries to avoid
cached errors. It does not relax TLS, WAF, origin restrictions or API authentication.
The original failed artifact is retained rather than overwritten.

Current docs: `/var/www/mana-ai-docs/parent-chat-f2c023f-assets`.
The networkless export uses the actual chat image; all twelve pre-existing paths
and their original components byte-match their prior contracts. There are thirteen
paths, with both chat methods and a separate `ParentChatBackendToken` scheme.
The manifest separately names unchanged inference and chat runtimes. Existing pinned
Swagger JS/CSS/license artifacts are reused with their verified hashes.

Final public JS/CSS checks returned **200**, with the exact pinned hashes and
JavaScript/CSS MIME types. An isolated headless Chrome profile rendered the Swagger
title/authorization control and, through the chat deep link, all fourteen operation
blocks including chat GET/POST. The default collapsed tag initially hides the paths;
it is not a missing-schema error. No credentials were entered into the browser or
Try it out inference submitted. The final clean repository gate, including the new
asset-version regression, passed `make verify`: **343 backend tests**, one skipped/
two opt-in deselected, **26 UI tests**, all static/build/audit gates as above.

### Retention, backup and rollback

Release kit: `/opt/manaai-releases/parent-chat-f2c023f/kit/`.
Backup: `/var/backups/mana-ai/parent-chat-f2c023f/`, including original configuration,
container inventory and the integrity-checked chat SQLite snapshot. The previous
unpublished candidate/negative diagnostic remain in the `parent-chat-e2c71a7` kit.

All **35** protected files matched, except the one precisely allowed Nginx server
edit adding the exact chat-location include. All five original containers retained
their IDs, start times, images, environments, mounts and host settings: main/audio
`e73c10a`, operational API/Goals `38cdac4`, UI `faf0a78`, scheduler `2ea7b9a` and
PostgreSQL. There was no migration, schema downgrade, source/schedule activation,
Firebase/GA4 access, new listener or resumed operational Goal. Existing scheduled
work is not paused or attributed to this release.

For an explicitly requested public-route rollback, first inspect current state:

```sh
python3 /opt/manaai-releases/parent-chat-f2c023f/kit/deploy_parent_chat.py rollback f2c023fd924bd442e5de4017816068cfe3fefd95
```

The guarded helper restores only the saved Nginx server and prior docs link after
`nginx -t`/reload, retaining the private chat service/data/holds. It never restarts
the existing stack or restores an old database. No deliberate public rollback drill
was performed. Disk/backup encryption, automated backup policy and broad quality
remain separate acceptance concerns, not claims inferred from these checks.
