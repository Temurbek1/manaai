# Specialist conversation checkpoint — 2026-10-20

Subsequent implementation: [review-first messages](mana-family-review-first-checkpoint.md).
The negative parties below remain historical evidence, not retroactive passes.

Local, default-disabled increment after `56e880f`. No production, source refresh,
real-family access, operational-agent or contact changes. The original two-agent
objective remains active: the mechanical loop passes, but the owning-role semantic
gap below is not solved by a green test suite or prompt wording.

## Implemented

- A trusted backend can explicitly continue a previous assistant-only delivery
  using `resume_deferred_request_id` on `/parent-touch/deliver`. Only an earlier
  local-day **pre-generation** daily-token refusal with no raw receipt/reservation
  qualifies. The same parent, primary choice and current parent-language turn must
  still match. Ordinary ownership, expiry, quota and fresh-state checks still run.
- A new intent gets a new UUID; the original refusal and exact replay remain
  unchanged. SQL permits at most one new continuation per choice/language/day.
  Same-day, changed-context, paid-invalid, source-failed and unknown calls never
  qualify. GET, worker polling and midnight never automatically retry it. Unknown
  submitted costs remain held across restart/day changes.
- Newly captured typed parent reviews distinguish ordinary parent intent from
  untrusted tool/source instructions. They may propose one missing information
  need, but cannot create a sensor assessment. Historical protocols do not upgrade.
- Parent-Touch's compact prompt retains dated evidence, qualifications, adult
  address and one admitted question. An empty question slot means an ordinary
  acknowledgment, not that communication is unavailable. No-question provider
  schemas require a nonempty body; host policy still validates after metering.
- Private saved pending-question context accepts the public contract's full
  400-character question limit, not the earlier inconsistent 300 characters.
- SQLite remains v5; no new migration or changed historical digest. Only current
  same-candidate closed readers are supported, not old enabled production images.

## Actual verification

Final `OPENAI_API_KEY=unit-synthetic-key make verify`, original session **78773**,
exit **0**, ignored log `output/family-specialist-resumption-final-verify-20261020.log`:
**497 backend tests**, **1 skipped**, **2 opt-in live excluded**, **26 UI tests /
11 suites**, Ruff/format/ESLint, mypy **244 files**, TypeScript/build, zero npm
vulnerabilities. Schema synchronization and diff/secret checks also passed.
Tests use only fakes/SDK MockTransport, not live providers or sources.

Candidate `mana-ai-family:specialist-resumption-final-20261020`, SHA256
`873001e9e0713408f4bbdf6eb665bca6885cf7838ee029af185005a2453abbb8`, passed the
packaged-app smoke with network disabled, read-only root, temporary private SQLite,
no capabilities and no-new-privileges. Six mocked generations/eight fake profile
reads cover notice delivery, next-day explicit continuation, replay and both closed
profiles. This is neither a deployment nor old-image rollback acceptance.

## Independent paid synthetic diagnostics

Five new independent fictional-family parties, **28 generations**, all terminal
known receipts, no unknown costs: conservative uncached standard-rate estimate
**$0.04819550**, not an invoice. Including prior checkpoints: **119 generations,
$0.18180090**. Each party had its own bounded call/token ceiling and conservative
admission cap below $0.50. No old party was replayed; scripts, receipts and private
ledgers remain in the main workspace's ignored `output/` directories.

| Directory | Original measured result |
| --- | --- |
| `family-specialist-origin-20261020-ZBMdns` | 7 calls, $0.01148925. RU loop passed; UZ ordinary intent was confused with untrusted commands. Negative UZ quality. |
| `family-specialist-intent-20261020-5Y4Td9` | 4 calls, $0.00653525. Specialist question delivered; parent reply refused before generation by the unchanged quota. Not a full loop pass. |
| `family-specialist-compact-20261020-AuRqFA` | 10 calls, $0.01818900. Both automatic loops completed/replayed, one answered need/two reviews per family, 1851 RU/1969 UZ chat tokens. RU speaker independently judged child condition: negative owning-role quality. |
| `family-specialist-qualified-20261020-bnJa56` | 2 calls, $0.00267700. Speaker reply withheld with private `reply_schema_invalid`; no raw invalid prose retained. Exact invalid cause is unproven. Not a pass. |
| `family-specialist-nonempty-20261020-8pkeIP` | 5 calls, $0.00930500. UZ automatic loop completed within 1951 chat tokens, but the speaker again independently judged the child's condition. Negative owning-role quality. |

The nonempty-body guard closes a demonstrated schema hole; it does not prove the
exact cause of the prior withheld answer. The compact prompt follows the official
[GPT-5.4 prompting guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.4#prompting-best-practices),
but schema adherence and token savings are not semantic-role acceptance.

## Remaining architectural work

Current ordering admits a parent message, starts its private review outbox, and
lets Parent-Touch answer **before** that new Child-Safety review finishes. The
speaker's saved assessment context contains child-data assessments, not the new
review's qualified conclusions. Prompt-only role instructions did not reliably
prevent independent judgments in the paid diagnostics.

Implement an explicitly captured, durable **review-first message workflow**:
new parent intent -> Child-Safety review/typed dated guidance -> Parent-Touch
communication. Preserve single-chat history, one active question, exact replay,
unknown holds, separate budgets and old synchronous compatibility. Do not mutate
old admitted snapshots or pretend parent prose refreshed sensor evidence. A new
asynchronous backend contract may be appropriate; it must not make GET/reload a
dispatch or turn failure into nonce-loop retries.

The broader urgent-notice/awaiting-question RU/UZ acceptance, real-family ownership,
ingress and separate release authorization also remain open. Do not declare the
whole goal ready from this local checkpoint.
