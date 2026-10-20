# MANA family-agent production release — 2026-10-20

The owner authorized production activation and automatic processing, then explicitly
set **2000 total Child-Safety tokens/day for all parents**. This is separate from
Parent-Touch's existing **2000 tokens/day per parent**. This configured family
workflow installs no unrestricted budget, historical re-analysis, Firebase/GA4
refresh or operational schedule.

## Active artifact and scope

- Application revision: `f8d095e5f870e7fdb8fac42475ef90e009081fed`.
- Container: `mana-parent-chat-parent-chat-1`, ID
  `0ee58dc8d519e89c78c8269a179c113b87258dc1706a4ea4d19a326be25fa59c`.
- Image tag: `mana-ai-family:review-first-fenced-20261020`.
- Server image: `sha256:af269c62bdd36605da4cae74331b82e1056807ccaf0e2a7c66e924e680180a58`.
- Local tested image: `sha256:d4e3af2582278abad12458626f69a1677e30abebc3ede4662998d30618a29e87`.
  Docker loading normalizes only explicitly verified empty/null/false legacy image
  metadata. All ten filesystem layers and nonempty runtime configuration, including
  Cmd, Env, User, WorkingDir and ExposedPorts, match. A strict unnormalized config
  digest comparison failed; it is not claimed to be byte-identical configuration.
- Image archive SHA256: `0f51f6b1848e250702529fea97db3c68c1ed82bb11423dea33bf643ffdd6dbed`.
- Tracked source archive SHA256: `25c378bd9ceb6f99bbd892239edf5ef7ca8b1f12fa3039974b5a2f53a341d27c`.

The initial GitHub push was refused with 403: account `samanwirst` had
pull=true/push=false on `Temurbek1/manaai`. Production therefore used the verified
tracked source/image artifacts; the initial push failure remains historical.
Later on 2026-10-20 the owner selected GitHub account `samango1`. Read-only API
inspection confirmed push=true, and a normal non-force push successfully created
`origin/feat/mana-family-agents-20261020`, including application `f8d095e` and release
documentation `813ad50`. This access-resolution record is a subsequent docs-only
increment on the same branch. No alternate credentials were searched for, no fork
or pull request was created, and production was not redeployed or restarted.

Only the isolated parent-chat service was recreated. Its existing backend token,
provider/Manakids credentials, named private volume and loopback `18082` remain.
Main/audio `e73c10a`, operational API `38cdac4`, UI `faf0a78`, independent worker
`2ea7b9a` and PostgreSQL retained their container IDs, start times, configurations,
mounts and healthy state. SSH authentication/settings and all old keys are unchanged.

## Enabled configuration and real limits

`MANA_PARENT_TOUCH_ENABLED`, `MANA_CHILD_SAFETY_ENABLED` and
`MANA_PARENT_TOUCH_REVIEW_FIRST_ENABLED` are enabled in this scoped sidecar. They
remain default disabled in code. Models are GPT-5.4 /GPT-5.4 mini; main/audio's
model configuration is unchanged. Child-Safety's explicit limits are:

```json
{"server_daily_tokens":2000,"parent_daily_tokens":2000,"job_tokens":2000}
```

The safety output ceiling is 1024; ordinary queue/attempt/history/lease bounds
remain. The worker polls **private SQL**, not Firebase, every second. New parent
messages or explicitly submitted child observations alone create new work.
Unchanged observations and exact request replays do not regenerate. Unknown
submitted costs retain their holds across restart/day changes.

**This is a very small global budget.** The worker reserves a whole 2000-token
job before source/count/model work. A typical short paid review consumes about
1000–1400 combined tokens in the recorded synthetic parties; the remaining daily
pool then cannot admit another 2000-token job. Large protective inputs may not fit
at all and must fail before generation rather than dropping safety context. This
profile is not full-population continuous analysis or unlimited chat availability.
Review-first messages can wait until their five-minute preparation expiry when
safety budget is unavailable; they do not silently fall back to independent speaker
analysis. Reset retains the configured Asia/Tashkent midnight (Uzbekistan time).

The application backend must submit new observations to the typed Child-Safety
endpoints. No mobile/backend code was changed to produce those events. Automatic
handling after receipt is enabled; automatic collection from every external source
is not implemented or claimed. The sidecar has no Firebase/GA4 credential mount,
source listener, operational scheduler, audio worker, push sender or control writer.

## Public endpoints / documentation

- Base: `https://ai.360rec.uz/api/v1/mana-ai`.
- `POST /parent-touch/messages`: recommended review-first message admission (`202`).
- `GET /parent-touch/messages/{request_id}?parent_id=...`: SQL-only status/result.
- `GET /parent-touch/chat`: the one shared history and hidden question/notice IDs.
- `/agents`, `/parent-touch/requests`, `/parent-touch/deliver` and the ten typed
  `/child-safety/...` capabilities are published to the same isolated service.
- Legacy `GET,POST /chat` stays compatible; it does not silently become review-first.
- Swagger: `https://ai.360rec.uz/docs#/mana-ai`.

Nginx's existing parent-chat snippet was extended only with exact `/agents` and
scoped `/parent-touch/` /`child-safety/` routes, tested and gracefully reloaded.
All other API/audio/admin routing stays unchanged. Static Swagger comes from the
actual image, has 32 paths/35 operations, and retains all thirteen earlier paths
and existing component contracts exactly. Existing pinned JS/CSS/license files
are reused with public permissions and image-specific asset queries.

Use the **existing isolated parent-chat backend token**, not the general inference
key and never a token embedded in mobile. The original protected credential handoff
remains `/opt/manaai-releases/parent-chat-f2c023f/kit/backend-client.env`.

Cloudflare initially rejected Python urllib's default client with 403/1010, including
the unchanged public health route. Curl, Chromium and an explicitly identified
`User-Agent: MANA-Family-Release/1.0` succeeded. Its meaning matches the official
[Cloudflare 1010 description](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/).
The observer now identifies itself; no WAF, TLS or origin protection was disabled.
Backend integrations should identify their HTTP client explicitly as well.

## Actual checks and limitations

- Fresh full `make verify`, original session **88188**, terminal exit **0**:
  **509 backend tests**, one skipped/two opt-in live excluded; **26 UI tests /
  11 suites**, lint/format/types/build, mypy **247 files**, zero npm vulnerabilities.
  Log: main workspace `output/family-release-2000-verify-20261020.log`.
- A consistent root-only copy of production's v1 private SQLite migrated to v6
  inside the exact candidate with network disabled. Both legacy table fingerprints
  stayed exact, integrity passed, two current closed readers worked and zero old
  events were recaptured. Eight mocked generations/ten fictional profile reads
  passed the actual packaged-app SDK/HTTP lifecycle on the production host.
- Before switching, one bounded negative Manakids exact-ID lookup verified current
  login/filter access. No family enumeration or real child profile was fetched.
- The actual live private volume migrated to v6 after a second consistent snapshot
  with only the old chat service stopped. Old history/digests/quota hashes stayed
  exact. No database was restored, downgraded or erased.
- Private and public checks verified directory/worker availability; missing/shared
  inference credentials returned 401; invalid authenticated requests to all ten
  protective routes and the new message contract returned 422 without admission.
  Main liveness/readiness/capabilities remained healthy.
- Exact replay of the already approved historical canary returned its original
  response and usage with no new source/model call or safety event. At verification,
  safety used/reserved tokens were **0**, remaining **2000**, new jobs/events **0**.
  No new paid production dialogue was generated to avoid consuming that small pool.
- Two authenticated provider metadata GETs returned 200 for the configured
  `gpt-5.4` and `gpt-5.4-mini` using the actual sidecar key, without generation or
  model input/output tokens. This uses the official
  [retrieve-model endpoint](https://developers.openai.com/api/reference/resources/models/methods/retrieve/),
  not a claim to have tested a new production generation, available balance or
  every inference permission.
- An isolated Chromium profile rendered the authorization control and all **35**
  operations, including review-first messages/Child-Safety, with no fetch error.
  No browser credential or Try it out inference was submitted.
- The first observer wrongly compared the historical status/response envelope
  with a raw response; the corrected observer validates/unwraps it. The second
  public observation stopped at Cloudflare 1010; the identified third observer
  passed. Both original failures/scripts are retained, not retroactively passes.

This is scoped infrastructure/API acceptance, not a new paid production inference,
real-family semantic review, complete Firebase coverage, emergency delivery,
device-control execution or business improvement. The earlier RU/UZ real-model
receipts and their negative/qualified observations remain authoritative.

## Backup and compatible deactivation

Release kit: `/opt/manaai-releases/family-f8d095e-20261020/kit/`.
Backup: `/var/backups/mana-ai/family-f8d095e-20261020/`.
The kit retains source/image checksums, exact Compose overlays, original/corrected
observers and bounded acceptance receipts. Backups retain both consistent SQLite
snapshots, the old chat/container configuration and 38 protected-file hashes/copies.
Only the intended Nginx snippet changes among those files; the docs link advances.
Secrets and personal history remain root-only, outside Git/images/public Swagger.

If separately requested, close safety execution with the current compatible image:

```sh
python3 /opt/manaai-releases/family-f8d095e-20261020/kit/release_family.py close
```

This disables Child-Safety/review-first processing, retains current Parent-Touch
history/legacy chat and v6 state, and never restores an old DB. A populated v6
volume **must not** be reopened by old `f2c023f`/v5 images. Closed-mode compatibility
was checked on protected copies and synthetic candidate workflows, not by deliberately
closing/reopening live production. Never automatically retry a dispatched release,
unknown model call or failed source admission from these helper filenames.
