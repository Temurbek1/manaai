# Server-owned read conditions — local checkpoint 2026-10-08

The preceding [Sol diagnostic](../output/operation-chat-evaluation/standing-approved-20261008-sol-quality/review.md)
had 7/8 functional passes. Its Parent answer named generic access/limits rather
than all preregistered admission qualifications. The raw score, original prompt,
model, manifests, receipts and unknown hold are unchanged. No paid rerun occurred
in this checkpoint; this is application-contract hardening, not a retrospective
model-quality pass or default-model activation.

## Implemented contract

`ChatTurn.read_confirmation` is optional server-generated presentation metadata:

```json
{
  "kind": "mana_parents",
  "product": "mana",
  "capability_key": "retention.parents.analyze",
  "confirmation_required": true,
  "admission_checks": ["access", "product_scope", "cooldown", "budget"],
  "minimum_interval_seconds": 21600
}
```

The Parent interval comes from the same `manakids_parent_min_interval_seconds`
setting as the existing handler, not a model guess or hardcoded promise that a
read will succeed in six hours. The permitted range remains six to twenty-four
hours. Default analysis uses its actual registry capability and no unverified
numeric interval; saved Growth proposals/discussion/planned or unsupported cards
have no read conditions. Product names the selected topic, **not verified source
ownership**: that check can still refuse admission.

The model still supplies only the existing `ChatReply` fields. It cannot issue
this contract or confirm a read. `OperationChatService` derives conditions only
for supported proposed read cards on completed non-analysis turns, using current
topic/configuration/availability when replying or displaying saved history.
Failure/cancellation, unavailable source or absent handler supplies no read grant.
The existing user-confirmed analysis endpoint and its authorization, scope,
cooldown, budget, idempotency and audit protections remain authoritative.

These conditions are **not persisted as consent** in `ChatTurnRow.payload`.
Serialization excludes the new response field so this addition does not place
unknown JSON keys in records consumed by an older strict chat schema. Reload and
restart reconstruct current conditions from the saved intent without a model or
provider call. This does not certify compatibility/rollback of every other
uncommitted change; existing migrations and rollout review remain separate.
Existing history/cost rows were not rewritten or deleted.

The UI uses a well-formed Parent contract for the displayed interval, preserves
the six-hour lower-bound/refusal warning for missing/corrupt legacy metadata, and
names all four admission controls. It does not poll sources on render, send policy
metadata back as authority, infer access from the contract or automatically
launch a job. The POST still contains only request ID, explicit confirmation and
the existing kind. Extra `read_confirmation` request data is rejected by the
existing strict request schema. No new button or second confirmation was added.

## Evidence

- Real ASGI chat + SQLite/restart tests use fake models: four valid card kinds,
  disallowed MANA/360REC/agent combinations, configured 24-hour interval, private
  history/replay, no new model call on replay, zero runs, and no persisted response
  field. Disabling the Parent source removes current read conditions and refuses
  the explicit analysis request before its background handler.
- Schema rejects missing/reordered admission conditions, false confirmation and
  intervals outside the existing bounds; old payloads default to no conditions.
  The model output schema and exact instruction hash are unchanged.
- UI tests cover eleven valid/malformed policy cases, source/app/capability/kind
  mismatches, missing budget check, exact/non-round intervals, 21-hour Russian
  formatting, legacy fallback, ChatPage-to-card propagation and no authority in POST.
- OpenAPI/TypeScript client regenerated; `make audit-schema` passed.
- Browser audit uses an isolated local fake app/database/OTP/browser session,
  with Parent interval **86400 seconds**, no auto-connect to the user's Chrome.
  It checks response metadata before confirmation, all visible controls, no
  duplicate confirmation, historical warning outside collapsed details, 320px
  reachability, accessibility, fake execution/approval/audit/reload/logout.
  [Final terminal browser log](../output/operation-chat-evaluation/read-confirmation-compatibility-browser.log)
  passed; desktop/mobile screenshots in `output/operation-chat-evaluation/
  read-confirmation-compatibility-ui-20261008` were visually inspected. One warning
  and one confirmation remain visible/reachable with details closed, no overflow.
- Final [make verify](../output/operation-chat-evaluation/read-confirmation-compatibility-accepted-make-verify.log)
  **exit 0**, **572 backend/80 UI**, mypy246 files, formatting/lint/TS, 34 dependency
  checks, Next16.3.8 build, npm audit zero findings. Five isolated PostgreSQL tests
  skipped/two live excluded. Focused ASGI/Parent/chat/fallback: **61 passed**.
  Secret scan and `git diff --check` pass. An intermediate TypeScript optional
  property error and a fixture-role assertion were corrected, not waived; earlier
  failed logs retained, final terminal run is the accepted gate.

No Firebase/GA4/backend or OpenAI paid requests, production, source binding,
schedule, IAM/key/SSH/audio/client-service changes. Known diagnostic spending is
still $0.239276 with a separate previous $0.050128 unknown hold; neither is a
production bill. Owner source mappings and representative/model acceptance remain
unresolved; the goal is not closed or narrowed to this contract.

OpenAI Docs influenced separating typed workflow controls and human confirmation
from untrusted model prose. We apply those principles in the existing application,
not migrate to Agent Builder or introduce tools/new agents:
[official agent safety guidance](https://developers.openai.com/api/docs/guides/agent-builder-safety).
