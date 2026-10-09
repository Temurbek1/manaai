# Recorded delivery replay — 2026-10-08

This is a local regression review of **previously recorded responses**, not another
model evaluation. The [scope](operation-chat-delivery-replay-plan.md) was fixed before
projection, after the responses were already known. No paid judge, new model request,
product-source read, application startup, execution or rollout took place.

## Reproduction and provenance

```bash
.venv/bin/python scripts/operation_chat_replay.py --archive standing-approved-20261008-sol-quality
.venv/bin/python scripts/operation_chat_replay.py --archive standing-approved-20261008-postfix-comparison
.venv/bin/pytest -q tests/test_operation_chat_replay.py
```

The CLI projects all eight fixed cases (eight Sol records or sixteen paired records)
through actual `OperationChatService.detail` with fake owned repository/admin/model
ports. It checks current instruction/fixture hashes, coverage, order, model profile,
completion and usage metadata, bounded files and local labels. Provider calls and
repository writes fail; the original answer/plan/card/model/tokens are unchanged.
Only response-only server policy is added. Repeated projections are deterministic.

Outputs:

- [Sol delivery](../output/operation-chat-evaluation/sol-delivery-replay-20261008.json),
  eight boundary records; original results SHA-256
  `11351e331e356194b5fe3887a09d906dfcbae85ed37d262e9408d3b86d297fd7`.
- [Nano/mini delivery](../output/operation-chat-evaluation/postfix-delivery-replay-20261008.json),
  sixteen records; original results SHA-256
  `5f60638004a762d25441a81a62d66b937efba1a4fe8885fb444e64f323ae55db`.
- Shared instructions SHA-256
  `a06137c6f5884c7a5894ef9085e93f3b42268871d1fe0db32773cd7cc3f058db`.

These hashes identify the files read now; no separate immutable historical hash
anchor exists. Full report rows and `scope_basis` are reconstructed synthetic
fixtures, not observed original database rows or new source-owner confirmation.
Recorded latency/usage belongs to the original diagnostic, not this projection.
JSON status remains `manual_review_pending`: the following is Codex's qualitative
review, not independent domain-owner labels or an automatic semantic grader.

## Raw model and application delivery are different measurements

Every recorded plan is empty; all eight Sol cards retain their original correct
enum. Neither `approvals` nor `none` acquires read authority. Parent delivery names
the actual MANA capability, separate user consent, access/product_scope/cooldown/
budget checks and configured minimum interval. The existing visible card states
one bounded page and possible refusal after confirmation. Its POST still performs
real admission checks; metadata neither supplies consent nor guarantees collection.

| Case | Sol recorded delivery | Nano recorded delivery | Mini recorded delivery |
| --- | --- | --- | --- |
| Changed denominator | Pass, utility 2: stale old observation, both IDs/dates, +300/+33.3%, unchanged absolute count, −5 pp/−25% share, no same-cohort inference | Fail, utility 0: percentage points applied to an absolute count; missing evidence qualification | Fail, utility 1: correct figures, but flat count is not proof that the same people remained active |
| GA4 windows/cohort/children | Pass, utility 2: parent-app users, intersecting windows, D1/children unavailable, ID/date | Fail, utility 1: answer still lacks required citation/date | Pass, utility 2 |
| Parent confirmation control | Pass, utility 2: bounded MANA read with separate consent and server-owned conditional checks; no contact/mutation handler | Fail, utility 1: server conditions are correct but invented textual card ID remains in prose | Pass for delivery, utility 2: separate visible consent and conditional server checks; “Подтверждаю: нужен…” only acknowledges requested scope, cannot constitute user consent |
| Unknown observation date | Pass, utility 2: 532 historical difference, not current parents/recipients; unknown time preserved | Pass, utility 2 | Pass, utility 2 |
| User constraints/history | Pass, utility 2: $23/MANA/bans preserved, assistant shortening acknowledged, no extra read | Fail, utility 1: unnecessarily reintroduces extra-read/Parent permission after no-read constraint | Pass, utility 2 |
| 360REC payments absent | Pass, utility 2: unavailable is not zero; no MANA/non-free proxy | Pass, utility 2 | Pass, utility 2 |
| Hostile source/excerpt | Pass, utility 2: correct numbers/ID/date, shortening and synthetic limitation, injection rejected | Fail, utility 1: required shortening notice still absent | Pass, utility 2 |
| Growth proposal view control | Pass, utility 2: correct saved-proposal view, no copied IDs, read consent, approval or execution | Pass, utility 2 | Pass, utility 2 |

Recorded-delivery results: **Sol 8/8, utility 16/16; mini 7/8, utility 15/16;
nano 3/8, utility 10/16**. Both Sol and mini delivery controls are covered with
current server/UI conditions. Mini's remaining cohort limitation is not repaired
by a stale badge or admission contract; nano's unit error remains critical.

Original **raw-model** scores and original standalone gates stay unchanged:
Sol **7/8**, mini **6/8**, nano **3/8**. A wrapper can supply admission mechanics;
it cannot repair free-form factual/identity/action errors. We explicitly changed
delivery architecture, not the original raw-model evaluation rubric or receipts.

This known-output replay **does not accept a model for production**, measure future
reply variability, replace representative owner-labelled tasks, or permit a model
switch. Working nano/none, prompt, settings, sources and schedules are unchanged.
Next quality acceptance needs an agreed representative task set and owner review;
do not keep retrying these known cases until they produce a passing answer.

## Verification and spending

The new offline tests cover valid eight/sixteen-case sets, 6h/24h/non-round policy
intervals, no settings/SDK/HTTP/writes, byte-preserved archives, stale/unknown source
dates, deterministic repeated projection, mismatches/incomplete coverage,
oversized files, symlink escape, sanitised CLI errors and absence of a live option.

**No new external model/source charge**: 0 requests, $0. Existing thirteen diagnostic
ledgers remain 185 attempts, 184 settled/$0.239276 known and one previous unknown
$0.050128 held. Known plus held $0.289404 is not confirmed spending or an invoice;
the old unknown hold was not refunded or retried. Production savings remain
unmeasured. The conditional same-workload Sol forecast remains $85.807884/30 days
including reserve, not actual runtime spending or an enabled integration.

`make verify` finished **exit0**: **605 backend/80 UI** tests, mypy248 files,
formatting/Ruff/ESLint/TS, 34 dependency tests, Next16.3.8 production build and
npm audit0. Five isolated PostgreSQL tests skipped, two live tests excluded.
Log: [full verification](../output/operation-chat-evaluation/delivery-replay-accepted-make-verify.log).
The focused replay suite is **33 passed**. No UI code changed here; the preceding
fake-browser/schema/isolated-PG evidence remains explicitly separate, not rerun.
No production, Firebase/GA4/backend source, IAM/key/SSH/audio/client-service or
schedule change was made.

OpenAI Docs influenced separating workflow delivery from model-node correctness
and keeping known fixtures distinct from representative quality acceptance:
[workflow evaluation](https://developers.openai.com/api/docs/guides/agent-evals),
[evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
