# Native contact loop: real-model lifecycle diagnostic

Local evidence on 2026-10-15. Production remains the separately documented RU/UZ
release. Contact features remain default disabled and undeployed. No Firebase/GA4,
application API source, customer, production database, SSH, schedule, deployment or
contact approval/send was used. Goals remain read-only; the overall workspace
objective is not complete.

## Actual scope and safe execution

`scripts/operation_contact_loop_evaluate.py` defaults to an offline plan. Paid use
requires `--confirm-paid --output <fresh-directory>`; an existing directory is
refused, never resumed. It takes only the configured inference key from settings
and uses the official OpenAI endpoint. A new local SQL database/ledger caps a party
at two calls and $0.50. SDK retry is disabled. Unknown receipt reservations remain
held; a new nonce observes the saved child, never reissues a call. Unit tests use
only mock HTTP and a test key.

The initial synthetic context is assembled by the diagnostic with the actual
workspace/session instructions; it does not exercise HTTP or the initial chat-service
admission. The real model selects the native fictional recipient/template. The
diagnostic then uses the actual owning Retention preparation service, private SQL
pairing, updated session-context reader and result-continuation application/model
path. The operator explicitly prepares only `sample_uz` / `onboarding_help` and
adds a no-discount/no-other-message condition. Author self-approval remains denied.
No approval, reviewer assignment or fake dispatch is performed. The dated fictional
fixture clock is separate from the real SQL/budget/observation clocks.

The API protocol follows [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling).
The diagnostic uses `gpt-6.1-sol`, low reasoning, at most 2048 output tokens per call,
standard service tier. Its local rate card was rechecked against
[official API pricing](https://developers.openai.com/api/docs/pricing): $2 input,
$0.10 cached input, $2.50 cache write and $10 output per million tokens for this
short-context standard profile. These are usage-based estimates, not an invoice,
regional/fast-tier quote or prediction of whole-platform operating costs.

## First attempt: semantic failure, not a pass

Evidence: `output/contact-loop-live-20261015.fR17Gd/attempt/result.json`, SHA-256
`7af51e1c5f2ba57220a6cb7551d58f4c151f981ec87f7da482cf04e2e8943285`.
The party finished at 07:00:56 UTC. Two terminal model receipts settled to 14084
microusd ($0.014084); no unknown hold remained. There was one fictional target read
and zero fake sends.

Native selection, exact call/output pairing, Russian answer, Uzbek fixed template
and SQL replay worked. Manual review nevertheless failed the answer: it said the
next step was human confirmation of preparation even though that confirmation had
already produced the saved `proposed` action. The diagnostic JSON's `completed`
status means transport/application completion, not semantic acceptance. Its original
`manual_review_pending` artifact is preserved unchanged; this report records the
negative review instead of rewriting it as a pass.

The full gate in `output/contact-loop-diagnostic-verify.log` was intentionally stopped
with SIGTERM/exit 143 after this discovery so the correction could be verified in a
new run. It is not a successful full verification or a source/provider failure.

## Correction and independent new attempt

The host now supplies typed lifecycle meaning beside the original frozen SQL facts
in the function output. `preparation_recorded=true` explicitly means preparation has
already occurred, not approval or delivery. `proposed` identifies separate human
approval as the next step under the existing default author-self-approval denial;
`dispatching`/`uncertain` permit observation without redispatch; `refused`, `rejected`
and fake `verified` authorize no next action. These labels do not grant reviewer
access, refresh eligibility, alter policy or perform a write. The model instruction
explicitly distinguishes preparation from approval.

Only the transient model input changes. Persisted result/window contracts, hashes,
source permissions and Goal checkpoints do not change. A consumed old invocation
continues to return its original saved answer, not regenerate it with new wording.

New evidence: `output/contact-loop-fixed-live-20261015.h9CB2J/attempt/result.json`,
SHA-256 `bac7de4dcbc7dafbb69253793fb7ec2bb47e6f74f6bcaabf37a1c0e7334f7e97`.
It finished at 07:04:13 UTC; two terminal receipts settled to 10966 microusd
($0.010966), with zero unknown hold, one fictional target read and zero sends.
This was a new explicit party, not a retry/resume of the old invocation.

Manual review of this answer passed this particular case: it correctly states that
preparation is complete, no approval/send happened, separate authorized review is
next, and another preparation is unnecessary. It preserves the Russian response and
exact Uzbek template, offers no discounts/other messages and does not claim real
delivery or measured retention. Replay returns the same saved child without another
model call. Both parties together used four calls, $0.025050 by the recorded usage
and rate cards, zero unknown holds and zero real-source/customer activity.

This single before/after example is not statistical quality coverage, a causal proof
of optimal prompting, real customer authority, authenticated browser/HTTP acceptance
with a real model, production readiness or complete Codex/Claude parity.

## Engineering verification

- Focused pinned-SDK/application/diagnostic tests passed: 22 tests, mock HTTP only
  (`output/contact-loop-lifecycle-focused.log`). They cover all six lifecycle labels,
  exact SQL pairing, preserved conditions, refusal/unknown accounting and no replay.
- Actual networkless closed `2ea7b9a` read/pause/reconstruction passed again with v2
  consumed pairing and v15/v14 Goal state (`output/contact-loop-lifecycle-compat.log`).
  This remains local compatibility, not a candidate-image or production rollback.
- Schema/client synchronization, secret/quality-marker scans and Compose passed
  (`output/contact-loop-lifecycle-schema-security.log`). No schema/client change or
  new migration was needed; mypy passed for 383 files.
- Final full `make verify` passed and its original process exited successfully:
  1344 backend tests passed, 28 PostgreSQL cases skipped and two opt-in live cases
  deselected; 188 UI tests passed. Formatting, lint, mypy (383 files), TypeScript,
  production UI build and npm audit (zero vulnerabilities) passed
  (`output/contact-loop-lifecycle-verify.log`). Skips are not provider acceptance;
  the earlier 28-case PostgreSQL run remains separate evidence for unchanged SQL.
  Observation across conversation turns did not restart this final gate.

The prior local fake browser/PostgreSQL evidence is in the
[result-continuation checkpoint](operation-contact-tool-continuation-checkpoint.md).
It does not become real-model browser or new SQL-concurrency acceptance by reference.
Owning capability/admin-control registration, broader real-model/source/action coverage
and separately authorized candidate/release/rollback remain open.

The next control gap is confirmed in the current code, not inferred from the model:
`RetentionContactService._execution_allowed` checks
`capability_kill_switch:retention-agent:retention.contact.sandbox`, but
`OperationAdminService.set_kill_switch` accepts only the owning agent's loaded
capability definitions. `RetentionAgent` currently obtains those from the analysis
handler registry, which has no contact entry. Global and agent-level checks still
exist; the contact-specific key is not yet governable through that standard admin
API. A safe next increment needs explicit owning action/control registration and
bounded proposal admission, not a pretend scheduled analysis handler or a fifth agent.
