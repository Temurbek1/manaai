# Retention contact review in chat: local sandbox checkpoint

This is a local, default-disabled increment after the deployed RU/UZ release
`38cdac4`. It has not been released, and migration `b47ea6c9130d` has not been
applied to production. The approval for the language release explicitly excluded
Retention contact actions and new migrations. Main/audio, SSH, keys, Firebase/GA4,
sources and schedules remain unchanged.

## Implemented boundary

`OPERATION_WORKSPACE_RETENTION_CONTACTS_ENABLED=false` is the default. The lane
also requires the existing native workspace/action prerequisites. Disabled access
stops before reading the new private contact tables. There is no schedule,
automatic customer targeting, real push receiver or source-read activation.

Only an owned, completed native MANA message in Retention or Orchestrator may
offer `retention_contacts`. The model is instructed to offer it only for explicit
fictional sandbox testing; server-side role, topic, product, turn and feature
checks remain authoritative. Orchestrator delegates the workflow to the typed
Retention service, without receiving transport credentials. Goals tools remain
read-only, and the four-agent architecture is unchanged.

The human selects one of two server-owned fictional adult aliases and one of two
fixed templates. The recipient's verified fixture language, not the interface
language, selects the exact RU/UZ body. Preparation requires its own confirmation
and saves a proposal; it does not send. A second human decision binds the saved
fingerprint and requires a reason, role/policy checks and current target validation.
No request accepts a real account, arbitrary message, language override or live
provider. Public responses omit private account refs, consent evidence and source
snapshots.

New private contact intents use version 2: the originating turn is part of the
fingerprint and SQL insert validation. Standalone version-1 fingerprints remain
unchanged. A request collision cannot return an intent from another turn. The new
chat action lives in private workspace metadata; both legacy JSON projections
retain `next_action=none`. No new physical migration beyond the foundation is added.

The owning lifecycle retains exact message hashes, approval before dispatch,
fresh consent/payment/quiet-hours and independent kill checks, durable recipient
reservation, seven-day verified-acceptance cooldown and unknown-outcome holds.
Lost acknowledgements never trigger a second send. Explicit reconciliation only
observes an exact fake receipt. Reload/status GETs observe SQL, not the receiver.
The UI blocks a second mutation after a lost response and provides status refresh.

`sandbox_accepted` is fake receiver acceptance, not delivery/opening, consent for
real outreach or improved retention. Business outcome remains `not_measured`.
Russian/Uzbek UI labels are localized; original message/history text is preserved.

## Frozen historical contact context

New chat/Goal admission may capture at most three same-owner/topic MANA contact
checkpoints from the local SQL revision journal. Only turn-bound version-2 intents
enter this context. Event timestamps, not the action's newer current status, decide
the state before the immutable capture cutoff. Target, receipt and sender ports
are not invoked. A late acknowledgement can change a new conversation's history,
not rewrite the history already supplied to an existing task.

The checkpoint keeps only action/turn identity, event time/revision/status, template,
recipient language and message hash. It excludes the body, account/recipient ref,
approval fingerprint/reason, consent/payment evidence and grants. Prompts identify
it as fictional historical context, not real delivery, current eligibility or a
measured business outcome. Unknown states are never permission to resend.

`OPERATION_WORKSPACE_CONTEXT_CONTACT_EVENT_LIMIT=400` explicitly bounds local SQL
event capture (server range 4–10000). Exceeding it refuses capture rather than
supplying a prefix as the whole history. This is not an unlimited contact catalog.
Disabled contact history stops before private-table reads; no source refresh is added.

Only new Goals with nonempty contact history use private checkpoint **v15**. Its
`contact_profile_version` binds the original v1–v14 tool/scope/review/continuation
checks, rather than changing their contracts. The continuation digest additionally
binds the frozen contact context. SQL save rejects adding, removing or modifying
that context after admission. Original tasks never silently gain it. Empty new
fields are omitted without turning the typed public schema into arbitrary JSON;
old checkpoint bytes and scope digests remain unchanged. Replays reconstruct the
original SQL context and do not recapture or generate again.

The approval design follows the host-owned request/decision/result boundary in
[Codex App Server approvals](https://developers.openai.com/codex/app-server#approvals)
and the independently enforced tool permissions described by the
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/permissions).
These are interaction references, not a claim of identical agent functionality.

## Related transcript correction

Browser testing found a quick first answer could remain hidden behind the cached
empty first page of a newly created topic. After the single message POST completes,
the UI now validates and seeds the exact owner/topic SQL first-page cache. Existing
topic paging remains intact. It does not redispatch generation, restart a Goal or
read Firebase/GA4. A deferred-response regression asserts one generation request.

## Verification and remaining acceptance

Local HTTP/SQL tests cover role/owner/product/turn binding, strict confirmations,
forbidden request fields, exact Uzbek text, replay, default-disabled admission,
self-approval denial, rejection and unknown acknowledgement reconciliation. UI
tests exercise separate preparation/approval, lost-response status observation,
recipient language preservation and observer-only reload.

The private fake browser scenario exercises preparation → review → one fake
acceptance → reload, mobile 320px layout and automated accessibility checks. The
contact screenshot confirms this case actually ran; an earlier browser pass
that skipped the contact block is not contact acceptance. Failed attempts are
retained, including an unsupported browser command and an initial cache fix.
The `/dev/shm` full-suite attempt failed with SQLite disk I/O errors and is not a
pass. Final verification uses a separate `/tmp` directory.

The isolated PostgreSQL audit covers migration round trips and the existing
contact foundation's cross-connection lifecycle/cooldown, plus a version-2 turn-bound
case and event-cutoff history from a second connection (**25 cases**). It is not
the new chat bridge's full concurrency/load/reviewer-access acceptance.

The actual local **closed `2ea7b9a` image** passed a networkless synthetic-DB
read/pause/reconstruction audit against contact v15 layered over the v14/v5
profile, new native chat action and minimized history. Old commands/claims cannot
execute it; current code retains full private context, conditions/evidence and
unknown holds. This is not a candidate-image or production rollout/rollback test.
Never select `38cdac4` as a v15 reader, downgrade populated private contact history
or restore an old database over new work.

Still required before any release or broader readiness claim:

The subsequent [single-action peer review](operation-retention-peer-review-checkpoint.md)
adds a local default-disabled, personal-session-only two-account lane and separate audit
migration. It is not deployed and does not supersede this checkpoint's historical test counts.

- Candidate-image and scoped release/rollback acceptance for the complete contact
  increment. The actual closed old-image check above is local synthetic evidence,
  not a production migration/deployment grant or a live receiver test.
- Broader contact-memory/model-quality acceptance. A fake model receiving the
  historical checkpoint is not proof of real-world reasoning or action quality.
- Owning-agent capability registry/admin kill-control integration and bounded
  proposal admission. This workspace review lane is not a loaded full operational
  contact capability or a model-selected mutation tool.
- Broader reviewer/access and production acceptance for the subsequent local lane.
  This original checkpoint alone lacked two-person review and used isolated fake
  self-approval; the later peer test preserves default author denial. Neither
  changes production settings or enables real sends.
- Real per-recipient billing/activity/consent authority, approved live channel
  executor, real outcome measurements and separate human release authorization.
  Parent aggregates, tariffs and notification OS permission cannot substitute.
- Broader real-model and authenticated production-browser acceptance. All model
  and receiver calls in this checkpoint use local fakes; paid/source spend is $0.

The overall Codex/Claude-style workspace goal remains open.

## Verified engineering checkpoint — 2026-10-15

Final `make verify` passed the current worktree: **1300 backend tests**, **181 UI
tests**, mypy **365 files**, Ruff/format/ESLint, TypeScript, production UI build
and npm audit (**zero vulnerabilities**). **25** PostgreSQL cases passed in an
isolated local container after migration round trips/drift checks. Two live suites
were deliberately excluded; PostgreSQL is separately exercised, not reported as
passing inside the default suite.

The actual closed-old-image v15/v14-profile compatibility and explicit-pause
audit passed. API schema synchronization, secret/quality-marker scans and Compose
configuration checks passed. The native private fake browser case passed RU/UZ
presentation, exact Uzbek message preservation, separate confirmations, acceptance
reload, 320px layout and automated WCAG A/AA checks. Its mobile render was visually
inspected. This does not substitute for authenticated production-browser or live
receiver acceptance. Fake application tests additionally complete a native saved-
report analysis/review after restart with the original contact context intact,
without recapture, a new source grant or another send.

Ignored receipts: `output/retention-contact-checkpoint-verify.log`,
`output/retention-contact-postgres.log`, `output/retention-contact-final-compat.log`,
`output/retention-contact-schema-security.log`,
`output/retention-contact-memory-browser.log` and
`output/retention-contact-memory-browser/retention-contact-mobile.png`.
Earlier failed engineering attempts remain separate evidence, not rewritten passes.
No paid model call, external source read, production migration/deployment or real
customer message occurred in this checkpoint.
