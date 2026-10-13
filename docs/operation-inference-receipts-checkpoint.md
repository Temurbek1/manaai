# Verified inference receipts and safe failures

Status: **deployed to the operational API/Goals sidecar on 2026-10-13**, commit
`b81f45848d43a8b4e48496fac6234f74af44e7b8`. It builds on the scoped
[Goal-continuation release](operation-goal-limit-release.md). This checkpoint
strengthens the existing four-agent workspace; it is not a new agent or a claim
of complete Codex/Claude parity.

## Receipt before answer

Ordinary budgeted non-streaming chat now reads and validates raw provider usage
before the SDK parses `ChatReply`. A malformed structured answer cannot hide a
valid invoice estimate. Goal responses also separate pricing fields from output,
status/error metadata and continuation validation: known expenses remain known
when those later checks fail. Native tools are still handled before accompanying
text, and the existing bounded known-priced format-recovery rules are unchanged.

Both adapters share strict integer usage contracts. Booleans, fractions, missing
usage, unpriced model names and unverified service tiers retain unknown holds.
Pricing is an estimate under deployment-owned rates, not a provider invoice.

The ordinary stream uses the **pinned OpenAI 2.53.0 SDK's SSE decoder** through
`AsyncStream._iter_events()`. It consumes the same HTTP stream once and checks
terminal raw JSON before the normal SDK event model can coerce token counters.
This is a deliberate private-SDK dependency, not custom SSE framing. An SDK
upgrade must retain/reverify that boundary, one-byte UTF-8/CRLF framing, midstream
failure classification and receipt settlement. No SDK or application retry is
enabled, and observation/reconnection never dispatches generation.

## Safe failure behavior

Typed application failures distinguish authentication, permission, quota,
rate limit, unavailable service, timeout, connection, invalid request/response
and unknown usage. The adapter translates only allowlisted SDK facts; raw
messages, bodies, headers, parameter values and credentials are never persisted
by this error lane. Controlled HTTP status integers and static Russian messages
explain that work stopped and history was retained. Incomplete-reason metadata
accepts only `max_output_tokens` and `content_filter`, not arbitrary provider text.

Chat failure replay observes the saved turn without another model call. A tracked
Goal with unknown usage remains waiting, retains its original objective and hold,
and rejects resume or an additional limit grant. No failure creates read/write
authority or automatically retries a source. No schema/checkpoint version,
approval, schedule, source binding or budget-renewal contract was changed.

The mypy artifact exclusion covers only ignored `output/` files, whose repeated
operator-script basenames collided during local checking. All tracked application,
test and script modules remain strictly checked; this is not a typing relaxation.

## Verification

- Forty real-SDK/mock-HTTP chat/Goal fault cases cover valid, malformed, incomplete,
  unknown-priced/usage and HTTP/network failures. Two application/SQL cases cover
  durable unknown holds, control denial and chat idempotent replay.
- Streaming regression additionally covers raw boolean usage, missing receipts,
  provider failure, one-byte multilingual UTF-8, CRLF/comments, SSE errors and
  midstream timeout/connection loss. Every synthetic boundary dispatches at most
  one HTTP request; no real provider is called by tests.
- Four diagnostic-runner tests verify its offline default, exclusive attempt,
  matching admission/usage and safe quota failure. Combined fault/stream/runner
  suite: **63 passed**.
- Full code, UI, PostgreSQL, browser and old-image checks are recorded in the
  final verification section below; fake workflows are not real model-quality proof.

Final `make verify`: **955 backend / 135 UI**, Ruff lint/format, mypy (322 tracked
source files), TypeScript, production build and dependency audit passed; npm
vulnerabilities zero. Separately, **17 isolated PostgreSQL cases** and migration
round trip/drift checks passed. No production migration was performed.

Native browser regression passed with fake providers: handoff, durable stream/
reconnect, tool/question controls, reviewed results, explicit historical scope,
long transcript/task/report paging, owner isolation, CSRF and accessibility.
The limit form retained exact confirmation, same original Goal, mobile layout,
lost-reply observation without another POST and stable result reload. This is an
isolated authenticated fake workflow, not a production human-session test.

Candidate local runtime: `mana-ai-operation:inference-20261013-local`, image
`f30ebf1f8c20c4ad86cc15247446f2d3b221a8bba1a3cf9e175d2b51e764674b`,
using the unchanged dependencies from actual v10 local runtime
`e841955dd7f33cac50f4f6b13a41436000209c95d422c5fc57f098f5aa36c663`.
Actual `2ea7b9a` / candidate networkless compatibility checks passed before/after
explicit synthetic pause, preserving private v10, grants, unknown holds, consumed
reads and exact history. No production data/configuration was mounted or restored.

## One new live diagnostic, not a lost-call replay

`scripts/operation_inference_diagnostic.py` is offline by default. Its opt-in
execution requires a fresh directory, an independent synthetic request, one-call
local SQL ledger, 128 output tokens, low reasoning and a $0.05 ceiling. It never
starts the application or loads a production/source database connection. It records
only the declared plan, outcome/model, safe failure class/status and cost totals,
not model text, credentials or customer data. Existing attempts cannot be restarted.

One new streamed `gpt-6.1-sol` request succeeded with a verified receipt:
**one call, estimated $0.000494, unknown hold zero**, source attempts zero,
production changes zero. This demonstrates the present local streaming/receipt
boundary only, not full planning/investigation/review accuracy or production key
equivalence. The SDK request did not recreate the prior Goal or eight-case party.

The existing production Goal's **$0.157238** hold and the earlier local party's
**$0.09612** hold were not refunded, revised, resumed or retried. Their original
causes remain unknown because no diagnostic provider receipt was retained. A later
successful tiny call cannot prove either lost request succeeded, failed for a
particular reason, or was free. The broad Goal remains open, including strong-model
analytical quality, fresh GA4 publication, deployed authenticated-browser acceptance,
extended-context acceptance and owning-domain action delivery.

Ignored evidence: `output/inference-receipts-20261013/`.

## Scoped production release

Explicit owner approval authorized the operational API/Goals worker only. The
candidate was built from `git archive b81f458`, using the unchanged actual
`mana-ai-operation:0d27000` dependency/runtime image and replacing application
code only. New unfinished local cohort-evaluation files were excluded.

- Runtime: `mana-ai-operation:b81f458`, image
  `sha256:a684007679dbc4daf25c08e9ac9903990805458acc99e5fa646a4446846758a8`;
  operational sidecar healthy, `APP_ENV=production`. Existing workspace, Goals,
  worker and explicit-limit flags restored exactly; sidecar scheduler still off.
- Protected backup: `/var/backups/mana-ai/inference-docs-b81f458`, custom PostgreSQL
  dump 1,769,288 bytes, SHA-256
  `11a543e12438aa303127dadcf466b435e405f1122f7a14c5730c21b8ea04670f`;
  `pg_restore --list` verified. No migration or database restore was performed.
- Fresh preflight found no queued/running Goal, active chat/source run or lease.
  Admission was disabled before staging, then existing flags restored.
- Actual production images `0d27000`, `2ea7b9a` and the candidate passed isolated,
  networkless synthetic compatibility checks before/after explicit pause. The
  first harness order assertion failed locally because the legacy synthetic
  control had not yet run; a new isolated fixture with the documented ordering
  passed. Neither audit mounted customer data or changed production Goals.
- Main/audio, UI `0d27000`, scheduler `2ea7b9a`, PostgreSQL containers retained
  exact IDs, starts, configurations and mounts. Existing sidecar environment,
  mounts and host configuration are unchanged. All 25 protected original files
  are unchanged except the separately authorized public Swagger ingress include.
- Seven source configurations, six schedule configurations, two source gates,
  controls and schema `a36d9f7b802c` retained their SQL fingerprints. Schedule
  configuration comparison excludes only normal `next_run_at`/`last_run_at`
  progression by the pre-existing scheduler; it includes enabled flags, cron,
  scope and circuit configuration. No source activation or new schedule occurred.
- All three pre-existing unknown reservation rows retained their exact fingerprint.
  The original review Goal `cd91c5e9-07fd-4959-ba4b-15ed51498e66` retained its
  exact full-state fingerprint: waiting, revision 16, four steps, accounted
  $0.215847 including unknown hold $0.157238. It was not resumed or retried.
- Authenticated read-only API availability and main health checks passed. Release
  verification dispatched no model inference, source read, action or Goal command.

The compatible application-only rollback is the immediately previous `0d27000`
image with the same environment/mounts and private v10 state. Drain admission and
inspect active work before switching; retain unknown holds and never restore an
older database dump over newer work. The separate `2ea7b9a` legacy fallback still
requires native execution disabled and the established pause procedure.

Ignored production evidence: `output/docs-release-20261013/`. Public MANA AI
[Swagger publishing](mana-ai-production-swagger.md) was independently authorized
and does not update the main/audio image or expose operational schemas.

The error mapping follows the SDK classes in
[official OpenAI guidance](https://developers.openai.com/api/docs/guides/error-codes#python-library-error-types).
Its general retry examples do not override this project's explicit no-replay policy.
