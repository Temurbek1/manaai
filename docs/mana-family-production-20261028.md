# Family-agent production release — 2026-10-28

The owner explicitly requested releasing the already verified work. Application
**40189716022791f0f60db1c5989f14feb0930246**, source/docs **b0330f5**, replaces
only the isolated parent-chat sidecar. The unfinished zero-linked-child setup
work (family42/collection5) remains local and is not part of this release.
The broader autonomous-agents goal remains active; release is not its completion.

## Exact running artifact

- Service: `mana-parent-chat-parent-chat-1`.
- Container: `fbb59ea63f38393a0f6cea74afbb24e484383ead6c9cea152a13d7608e7682dc`.
- Server image: `sha256:1f978e9051bf3f519496a02c0f7df20ba15baab33b9fcf0bfcac2d838d064957`.
- Local verified image: `sha256:b9e3dec5cce9a6e9af1c4a180390bbb220990f8159786eaf3867a95b01ae0ee5`.
- Image archive SHA256: `b0629a9a2e4db6b93271b498a3f8cd02b00a3acf929f9f8f201395c8e8237837`.
- Source archive SHA256: `97dc2344ddc033b2802be4c1e0978012bffbaae6aca58322d722c4b059bf8b15`.

Docker loading normalizes empty legacy configuration metadata and therefore
changes the image identifier. All filesystem layers, nonempty image configuration
and **310 application-file SHA256 values** match the verified local candidate.
No environment file, private SQL or real credential is included in the image.

The release retains the existing backend/OpenAI/Manakids keys and named private
chat volume. A separate read-only mount uses the exact already installed analytics
key; no existing credential file or SSH authentication configuration is changed.
The source cache lives separately at `/app/data/mana-family-sources.sqlite3`.

## Enabled scope and hard limits

The sole Parent-Touch speaker/manager, Child-Safety, parent reminders, Retention
chat support/expiry checks and explicit Upsell enquiries use their existing typed
owning lifecycles. New eligible turns capture compact source native5, saved-only
inspection and literal tariff refinement. Old histories never acquire new tools,
model receipts, grant eligibility or source approvals.

- Parent-Touch: **2000 raw input/output tokens per parent/day**.
- Child-Safety: **2000 raw tokens globally/day**, also bounded per parent/job.
- Models: **GPT-5.4 / GPT-5.4-mini**; no model downgrade.
- New native SQL lease: **360 seconds**. The parent sidecar explicitly uses the
  tested **30-second model timeout**; other services' timeouts are unchanged.
- Targeted child-source ceiling: **100 admissions /200 conservative document
  units per rolling24h**, with **21600-second** per-child/source cooldown.
  This is an enforced source ceiling, not an exact billing statement.
- Bulk collection, source auto-refresh schedules and window collectors remain
  **disabled**. Existing independent production schedules are unchanged.
- Push dispatch, automatic trial grants, account-driven conversion campaigns,
  trial-period/end features and payment/transaction actions remain **disabled**.

Proactive chat publication requires current independently verified language,
timezone and purpose-specific contact permission. Configuration does not invent
those facts. Source tools can inspect saved SQL or request one policy-bounded
own-child observation; they cannot scan collections or retry uncertain results.
There is no per-family GA4 identity join or mixing MANA with360REC data.

## Migration, acceptance and operational corrections

The original private schema6 copy first passed a networkless probe in the actual
server image: every cell in16 original tables, two messages and exact legacy
replay survived schema41 migration, with zero provider calls. The local full gate
was **1913 backend /26 admin /23 lab cases**, mypy499 files, lint/format/types/build
and OpenAPI sync. Five low-severity development dependency findings remain;
they are not part of the runtime image or a claim of zero vulnerabilities.
See [the exact local checkpoint](mana-compact-agent-workspace.md).

Initial activation inherited an old model timeout that did not fit the new
source-cycle lease. Settings correctly refused startup; this briefly interrupted
the chat sidecar. The release helper moved to the same image's closed reader,
retaining history while the actual environment was checked networkless. The
corrected configuration explicitly sets the tested30 seconds before activation.
No model/source call, history reset or change to another service resolved this.
The first correction attempt stopped before recreation on a backup-path harness
error; its failed result is retained. The validated third helper uses a distinct
new snapshot path. The original initial backup remains intact.

The generated Swagger directory initially inherited0700 from private staging,
causing403. Its public root/subdirectories now have explicit0755 permissions,
files0644; no API authentication, WAF or Nginx protection was relaxed. Public
HTML/schema/assets return200, exact42-path schema matches its committed export,
and an owned browser rendered Swagger with no page errors. That browser is closed.

A preliminary Python-urllib public GET was rejected by the **existing** user-agent
filter, before any message/model submission. A named backend user agent
`MANA-Backend/1.0` and ordinary curl both return200 with the isolated token.
Use an explicit backend user agent in integrations; changing it grants no access.
The earlier negative HTTP and directory-permission observations are preserved.

Final live migration preserved every original cell in16 tables and reached
family **41** / source **10**, integrity `ok`. The released container is healthy
with **zero restarts**. Main/audio `e73c10a`, operational API `38cdac4`, UI `faf0a78`,
independent worker `2ea7b9a` and PostgreSQL retain their original container IDs,
images, start times, runtime configurations and mounts, all healthy. Original
credential/SSH file hashes match. No old database was restored over new history.

## Real production chat smoke

Only the previously designated test **parent4** was used. Through the public
HTTPS message/status/history routes, a real strong-model enquiry returned:

1.90 days, total budget350000UZS -> catalog tariff8, **162000UZS**.
2.`А на 180 дней?` -> catalog tariff9, **299000UZS**, retaining the same budget.

Both turns are `completed` and both owning tariff intents `published`. The first
used **790 input +71 output =861** parent tokens. The literal follow-up used
**zero**, as did exact idempotent replay of both completed requests. No Child-Safety
analysis, external child-source read, push, free grant or transaction occurred.
Approximate uncached generation cost is **$0.00304**, not an invoice/count fee.
This is a real tariff-chat acceptance, not a real-family child-analysis or
fleet-capacity pass. Previous failed source and full reminder-dialogue parties
remain unchanged; the2000-token limits still constrain meaningful daily dialogue.

Unauthenticated history and the unchanged shared inference key return **401**;
the isolated backend key returns **200**. Never embed that key in a phone or
copy its value into integration documents.

## Handoff and compatible closure

- Swagger: `https://ai.360rec.uz/docs#/mana-chat`.
- Message admission/status/history retain the same minimal application API.
- GitHub branch: `feat/mana-conversion-agent-20261021`, pushed normally by the
  owner-selected `samango1`; the earlier `samanwirst`/connector403 failures remain
  recorded, and no force push, fork or main-branch merge was performed.
- Protected kit: `/opt/manaai-releases/family-4018971-20261028/`.
- Backup: `/var/backups/mana-ai/family-4018971-20261028/`.
- Protected local evidence: `/mnt/ssd2/mana-release-4018971-20261028/` and
  `output/family-production-4018971-20261028/`.

If an explicitly required operational rollback is needed, first inspect live
state, then use the guarded compatible closure:

```sh
python3 /opt/manaai-releases/family-4018971-20261028/release_sidecar_validated.py close
```

It disables owning execution while preserving the same41 reader, full private
history, source counters and unknown holds. It neither restores an old DB nor
selects the old schema6 image. Closed41/copy/unknown-state acceptance is recorded
locally; a deliberate post-release closure drill was not performed. Do not
reapply a completed release or restart historical tasks to test rollback.

Parent setup help, typed reminder-handoff optimization, verified contact-source
integration, broader live child analysis/retention/commercial eligibility,
referral/rewards and administrative owning actions remain separate unfinished
work. Technical Reliability stays last.
