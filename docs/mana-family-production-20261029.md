# Single-chat commercial preference release — 29 October 2026

Application **ebcfa88ded900d4a1719a6d0637760a77f05c388** is released in the isolated
MANA parent-chat sidecar. Parent-Touch honors explicit commercial refusals across
Conversion and tariff-expiry/free-period invitations, including when Conversion
is disabled or chat quota is exhausted. See
[the behavior and evidence](mana-commercial-chat-preferences.md) and English
integration section 55. The full AI KOMANDA goal remains unfinished.

Only the parent-chat image changed. The existing family **41** schema, **5000 raw
parent tokens/day**, **2000 global Safety tokens/day**, strong role models, source
ceilings, mounts, credentials and all feature flags remain unchanged. Bulk
collection, push dispatch, trial grants and automatic conversion campaigns remain
disabled. Local owner-first routing and semantic reminder flags are not activated.
Main/audio, OPERATION API/worker, UI, PostgreSQL and SSH are untouched.

## Artifact and preservation

- Local clean image: `sha256:fcc34ed25a6d48c33af8cc8ee5e8719ea78ce9a319e1b9a28d8253cda546d0d4`.
- Server image: `sha256:1da5ad355e79b9d896f3ee44bfea411baff243c7357453bd92a6074ae9264b82`.
- Archive SHA256: `d37b5f12ba8c2c08ec5bb29a9214a93f3a91c09a040ca2a0bc3bdae5635a3ef7`.
- Active container: `61504c744c817655ecc64a667c1945d31268c87a6f7408003541da1dee26f5ca`.

Docker loading normalizes metadata; every filesystem layer and all **329 app and
lockfile hashes** match the clean source/candidate on both machines. Python is
3.12.15 and OpenAI SDK 2.53.0. The image contains no environment file or private SQL.
The clean candidate passes the full gate, actual networkless production-factory
6→41 migration/replay, authenticated history, 401 without auth and absence of lab
cards. The same-image closed reader preserves the actual 11-message model party,
4069 parent/1223 Safety costs and a separately added synthetic 612-token unknown
hold across midnight. These are bounded checks, not fleet capacity or old-image
execution rollback acceptance.

Before switching, the helper validates exactly one resolved Compose difference:
the parent-chat image. It takes a private consistent backup. All cells in all
**86 original tables** survive startup, and the other five containers preserve
their exact identities, configurations and start times. Internal/public history
return 200. The sidecar is healthy; there is no schema migration or SQL restore.

## Production chat acceptance

Only the previously designated **test parent 4** is used. One public HTTPS
`POST /api/v1/mana-ai/parent-touch/messages` with `Не присылай предложения`
returns **202 / completed**, the localized acknowledgement and **0 input/output
tokens**, with `MANA_CONVERSION_ENABLED=false`. Exact same-UUID replay and status
GET retain the identical result. History gains exactly the parent command and
assistant acknowledgement; quota and every source-cache cell remain unchanged.
No model/source/push/grant/payment is submitted. The test account's commercial
refusal remains recorded; it is not silently undone after the test.

## Protected kit and closure

Server kit, backup and receipts:
`/opt/manaai-releases/commercial-preferences-ebcfa88-20261029/`.
Local evidence: `/mnt/ssd2/mana-commercial-preferences-20261029/`.

If compatible closure is required, observe current state first, then use:

```sh
python3 /opt/manaai-releases/commercial-preferences-ebcfa88-20261029/close_same_image.py close
```

It disables execution in this same image and preserves history, counters and
unknown holds. The closure helper was prepared; production closure was not
executed. The old release helpers expect the old image/quota. Do not restore an
old database or run an older active image that lacks these cross-owner preference
checks. Static Swagger paths/schema are unchanged; no frontend deployment is needed.

The first SSH control socket was already closed before staging; its batch-mode
fallback failed authentication and changed no service. A newly authenticated
background master completed staging and the guarded release. SSH authentication
configuration and keys were never changed.
