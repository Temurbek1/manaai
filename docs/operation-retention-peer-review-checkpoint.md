# Single-action Retention peer review — local checkpoint

This advances the full workspace objective; it is not a production release or real
customer-contact capability. The deployed RU/UZ baseline is recorded separately in
[the language release](operation-interface-language-release.md). Neither local contact
migration `b47ea6c9130d` nor this checkpoint's `c58fb7da240e` was applied to production.
Main/audio, SSH, keys, Firebase/GA4, sources and schedules remain unchanged.

## Authority and interaction

`OPERATION_WORKSPACE_RETENTION_PEER_REVIEWS_ENABLED=false` is the default. Activation
also requires the existing native/contact prerequisites and personal Telegram-backed
browser authentication. Only a human owner can share an exact version-2 fictional MANA
contact proposal with one explicitly selected active registered approver/admin.
Sharing requires literal confirmation and the original proposal fingerprint. It does
not send, approve, grant a source read or enable a live executor. A model cannot create
a disclosure grant; Goals tools stay read-only and the four-agent architecture is unchanged.

The permission is for one action/body/fingerprint and expires with the original proposal.
The selected reviewer receives only its minimized action view, not topic messages, user
constraints, Goals, raw target/consent/payment evidence or provider credentials. Identifiers
in that action view do not authorize the corresponding private-topic APIs. The directory
returns at most twenty eligible account labels/IDs, with an explicit omitted-page indication;
it does not expose Telegram IDs or become an app-user audience API. Unnamed accounts still
have an opaque-ID label; production staff naming/usability is not accepted by this test.

These new HTTP endpoints require **personal cookie sessions and CSRF** for writes.
A shared technical API key or development actor/role header cannot authenticate them.
Existing general authentication/SSH is unchanged. Individual sessions demonstrate distinct
registered identities, not that two credentials could never be held by one physical person.

The owner sees selection and a separately confirmed disclosure card inside the conversation.
The resulting link opens `/reviews?review=...` for the selected employee's own login; it is
an identifier, not a bearer permission. The recipient sees the unchanged RU/UZ text and gives
their own exact typed decision. The compact dedicated review view uses the existing owning
Retention card, rather than a new top-level agent. No Telegram/email notification is sent.
The owner can revoke before a decision. Sharing/revocation are separately guarded UI writes;
a lost response only observes SQL and never redispatches disclosure. A consumed decision is
not undone by an attempted revocation, and a revoked/expired grant is never auto-renewed or
reassigned. Choosing another reviewer currently requires a new explicitly prepared proposal.

## Durable lifecycle

Migration `c58fb7da240e` adds private grant and revision-audit tables, leaving old contact,
generic action, chat and Goal JSON unchanged. A grant is immutable except one explicit
revocation; owner/request and action uniqueness prevent nonce reuse and silent replacement.
Downgrade refuses populated grant/audit history. Do not restore an old database over it.

Approval and revocation lock the action before the grant, preventing a revoked permission
from racing into a write. The owning SQL transition rechecks the exact binding, expiry,
revocation and both accounts' current status/roles before admitting a peer decision.
The service also rechecks peer authority immediately before dispatch. Default self-approval
denial is preserved; it now correctly applies to the author, not an authorized different
reviewer. Existing fresh target checks, independent kill switches, recipient cooldown,
durable decision-before-send and unknown-outcome holds remain in force.

Replays, reloads and list/detail views never resend or poll a receiver. Explicit exact receipt
reconciliation remains observer-only. An expired/revoked reviewer cannot renew access or
reconcile; the original owner retains the normal private recovery lane. Fake receiver
acceptance is not delivery, an opening, paid renewal or improved retention; business outcome
is `not_measured`. Contact-bearing Goal history remains frozen/minimized under the existing
v15 profile and cannot inherit a review grant. There is no new Goal protocol or tool set.

The request/decision/result interaction follows the host-owned, turn-scoped boundary in
[Codex App Server approvals](https://learn.chatgpt.com/docs/app-server#approvals). The
person-to-person disclosure, cookie-only transport and stricter domain limits are MANA
application policy, not claims that Codex implements this exact business workflow.

## Verification scope

HTTP/application tests use distinct actually issued fake OTP/cookie sessions and the real
ASGI → SQL → owning fake path. They cover author denial, selected/nonselected identity,
private-topic denial, strict sharing fields, exact text, one accepted write, replay,
revocation, expiry, current role/owner disable, an identity change between application and
SQL admission, disabled-table admission, technical-key denial, GET without CSRF and POST
without CSRF. Lost acknowledgement remains uncertain until an explicit receipt observation;
replays and GETs do not reobserve or resend.

The actual fake browser uses two separate logins: preparation → sharing → sign-out →
selected-reviewer login → decision → reload → RU/UZ/mobile accessibility → original-owner
login. It does not reveal the original transcript. The actual mobile receipt was visually
inspected. An earlier browser failure found the GET dependency incorrectly required a CSRF
header; this was corrected to require CSRF for mutations, not observation. That failed
attempt remains separate evidence. This is not authenticated production-browser acceptance.

The isolated PostgreSQL audit adds two cross-connection races: two copies of one approval,
and approval against revocation. Exactly one fake send wins, or revocation leaves zero sends.
Empty migration round-trip/drift checks cover both new tables. The actual closed `2ea7b9a`
compatibility probe still exercises existing v15/v14 native context; it is not a candidate-
image test of the new grant tables or a release authorization.

Remaining full acceptance includes candidate-image/complete populated-history rollback,
staff naming and broader reviewer usability, bounded proposal admission, owning capability/
admin controls and native mutation-tool integration, real individual billing/consent/channel
authority, measured business outcomes, broad real-model/source quality and an explicitly
approved scoped production rollout. Local fake passes do not close the overall objective.

## Actual engineering receipts — 2026-10-15

The current worktree passed `make verify`: **1309 backend /185 UI** tests,
mypy **374 files**, Ruff/format/ESLint, TypeScript, production build and npm audit
with **zero vulnerabilities**. **27** separately isolated PostgreSQL cases passed,
including both peer races. API schema sync and secret/quality-marker/Compose checks
passed. A preliminary schema-sync check caught the changed GET header schema;
regeneration and a fresh synchronization/security check passed, without changing
the transport rule or reducing coverage.

Ignored evidence: `output/retention-peer-verify.log`,
`output/retention-peer-postgres.log`, `output/retention-peer-focused-final.log`,
`output/retention-peer-compat.log`, `output/retention-peer-schema-security-green.log`,
`output/retention-peer-browser-fixed.log` and
`output/retention-peer-browser-fixed/retention-contact-mobile.png`.
No paid inference, live source access, real customer contact, production migration
or deployment occurred. The browser and application receiver/model paths were fake.

The subsequent [peer-loop rollback checkpoint](operation-contact-peer-loop-rollback-checkpoint.md)
adds actual old/current-image observation of a populated two-action personal-review
history and unknown model hold. It is separate SQLite/fake evidence, not a rewrite
of the narrower checks above, integrated peer-history Goal capture or release authority.
