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

Release is prepared locally. Fill this section only after the actual deployment,
health, shared-key rejection, history durability and invariants are observed.
