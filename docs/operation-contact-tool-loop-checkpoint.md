# Sequential contact tool decisions — local v3 checkpoint

Local engineering checkpoint on 2026-10-17 toward the unchanged nine-item
[Codex/Claude-style workspace objective](operation-agent-workspace.md).
This does not complete the goal or release contact features. Production, the
application parent chat, main/audio, keys, SSH, sources and schedules are unchanged.

## Behavioral increment

The old native v2 result continuation is deliberately final-only. New, explicitly
captured `native_contact_preparation_v3` turns can instead produce another native
preparation request after an actual saved result. They use a separate, default-off
`OPERATION_WORKSPACE_CONTACT_TOOL_LOOPS_ENABLED` switch and require all existing
workspace/contact/proposal/continuation prerequisites. V1/v2 conversations never
upgrade; disabling v3 permits observation of a previously consumed invocation,
not new inference or a fallback protocol.

The first bound is two distinct fictional adult recipients in one root chain,
not two real parents, a campaign, unrestricted multi-action authority or infinite
reasoning. This advances the agent's actual result/next-decision loop; broad
cross-capability planning and outcome execution remain unfinished.

The model can select the next fictional request or finish; the host does not run
a second preparation automatically. Every selected request remains a separate
human-confirmed preparation, a separate exact approval/reviewer grant and the
owning Retention fake lifecycle. The original author cannot approve themselves
under the normal default. There is no arbitrary body, account, reviewer, consent,
source grant or live-provider parameter.

Only fake `verified` acceptance allows requesting the remaining recipient. A
still-proposed action must finish its separate review first. Refusal, rejection,
dispatching or uncertainty permits final explanation only, never another request.
The second result always forces final-only inference. Existing recipient cooldowns,
durable preparation ceilings, exact request replay and unknown model/source holds
remain authoritative; neither a new nonce nor a UI reload renews authority.

This follows the documented
[tool output → next model decision](https://developers.openai.com/api/docs/guides/function-calling#the-tool-calling-flow)
pattern. OpenAI Docs was used to verify call-ID/output pairing and retention of
opaque reasoning items, without changing the selected models or runtime framework.
These are observable interaction semantics, not proprietary Codex/Claude parity.

## Private context and durable pairing

`ContactLoopState` freezes the exact root, two-invocation ceiling and original
choice/dated SQL receipt for each consumed step. A child and its originating
invocation's one-consumer pointer commit atomically under the existing SQL chat
fence before inference. Concurrent or new-nonce calls only observe that child,
including a failed/cancelled/unknown result. There is no automatic model retry.

The new bound window protocol `contact-model-continuation-v2` retains the exact
root instructions/context, original function calls, opaque encrypted reasoning,
host-owned outputs and frozen session conditions. New windows must append the
exact prior prefix and new SQL result, not summarize, replace, or regenerate them.
All calls/results are revalidated against owner/topic/turn, selection fingerprint,
call hash, fixed parameters and original language. A repeated call identifier,
recipient or missing pairing fails after accounting verified provider usage.
Raw/summary reasoning and provider-supplied execution receipts remain forbidden.

The chain and result live only in additive private workspace metadata, not old
strict chat/Goal JSON or public responses/SSE. Public history and recent conversation
are separate projections. New saved loop/result snapshots cannot be replaced by a
later application update. There is no migration and no new Goal tool/checkpoint;
Goals remain read-only. Unknown expenses keep their original reservations.

Current owning status/kill controls gate new continuation admission and any newly
selected request after inference. A stop/cancel during inference discards the late
decision, not verified usage. Original model/reasoning/response language persist;
fixed recipient language, UI locale and personal-review authority remain independent.

## Verified engineering evidence

- Initial two-language HTTP → actual pinned SDK/mock HTTP → SQL → owning fake
  sequence passed **2 cases**. After extending the matrix and correcting a misplaced
  test-factory return, the matrix passed **17 cases**. The failed factory run is
  retained; it failed before application work, not a passing product evaluation.
- Expanded focused v3/v2/native/preparation suite: **72 passed**
  (`output/contact-tool-loop-focused-final-20261017.log`). This covers two independent
  confirmations, exact history/language, restart, concurrent single consumer, third
  call/recipient reuse denial, provider receipt/raw reasoning rejection, lost prefix,
  unknown receipt/pending/timeout, stop/cancel cost reconciliation and disabled/self-
  approval boundaries. Some fixtures explicitly allow fictional self-approval;
  the browser separately exercises two personal reviewer identities.
- Existing v1/v2/bridge regression: **46 passed**
  (`output/contact-tool-loop-v2-regression-20261017.log`), not additive coverage.
- Local PostgreSQL: **30 passed**, including v2 and v3 cross-connection one-consumer
  cases, migration round-trip and no schema drift
  (`output/contact-tool-loop-postgres-20261017.log`). This tests SQL pairing,
  not full multi-action HTTP concurrency, real providers or production load.
- Actual networkless closed `2ea7b9a` read/pause/reconstruct passed with v3 root,
  retained two-call history and a failed final child, existing v15/v14 Goals,
  consumed v2 continuation and populated preparation ledger
  (`output/contact-tool-loop-compat-20261017.log`). Exact new private-row fingerprints
  survive old observation. The v3 fixture uses synthetic result snapshots, not a
  complete contact/grant lifecycle or a production rollback drill.
- Ruff/mypy passed at the recorded stage for **407 files**. OpenAPI/TypeScript
  synchronization, secret/quality-marker scans and Compose validation passed
  (`output/contact-tool-loop-schema-security-20261017.log`). A separate staged
  operational-only export excludes parent-chat source and regenerates only the
  operational API changes; its mypy gate passed for **396 files**.
- The full new private browser flow passed
  (`output/contact-tool-loop-browser-fixed-20261017.log`): two separately confirmed
  preparations, two exact reviewer grants/decisions across personal logins, two fake
  acceptances, native result/next-request/final continuation and reload without a
  third action. Existing stream, Goal limit/discovery/context, CSRF and accessibility
  regressions passed too. It uses a fake model, not a paid semantic evaluation.
  The first browser
  attempt reached the second prepared action, then refused a reviewer-selector
  interaction covered by the composer. The harness now explicitly scrolls that
  control into the transcript and asserts its visibility; no forced click or
  weakened confirmation is used. The failed log/screenshot remain evidence.
  The first mobile final screenshot showed an earlier part of the conversation,
  not the final answer. A subsequent screenshot-only harness correction scrolls
  the last turn into view and checks visibility. That full fresh run also passed
  (`output/contact-tool-loop-browser-final-20261017.log`); its Uzbek 320px final
  result was visually inspected. Both local server ports closed after exit 0.
- A clean Python 3.12 image built successfully:
  `mana-ai-operation:contact-tool-loop-clean-20261017`, ID
  `sha256:0dceda239e595ce1f7045c74a98558e67f2667f02fc427b5aa149bc69886a2ee`.
  That actual image passed the v3/populated-admission/old-reader/Goal-pause probe
  before and after pause (`output/contact-tool-loop-clean-image-compat-20261017.log`).
  It was networkless, with no source/configuration/customer mounts. This is narrow
  candidate-image compatibility, not complete peer-grant rollback or release acceptance.
- The same image passed a networkless **production-mode ASGI lifecycle smoke**:
  `APP_ENV=production`, a synthetic backend key, fresh synthetic SQLite, no mounted
  credentials/data, sources fake, scheduler/Goals worker disabled, v3 availability
  enabled, liveness 200 and unauthenticated protected-route 401
  (`output/contact-tool-loop-container-smoke-fixed-20261017.log`). The first fixture
  omitted the required backend key and correctly failed startup; authentication was
  not weakened. This is not real nginx/entrypoint/PostgreSQL deployment acceptance.
- The clean full **`make verify` passed**, and its original tool session `5968`
  exited **0**: **1393 backend tests**, **209 UI tests / 30 suites**, Ruff/format,
  ESLint, mypy **396 Python files**, TypeScript, production UI build and npm audit
  (**zero vulnerabilities**). **30 PostgreSQL skips** are covered by the separate
  run above; **two opt-in live cases were excluded**, not passed. The backend portion
  took **30m36s** and was never restarted while being observed. Log:
  `output/contact-tool-loop-clean-verify-20261017.log`. Clean source:
  `/mnt/ssd2/mana-contact-loop-clean.pcusQi`, excluding unrelated parent-chat work.
  No operational source changed after this gate began. The independent browser used
  the root tree's separate `.next` and its own private DB/browser session, avoiding
  shared build or authentication state.
- The clean built UI passed standalone liveness, protected root/runs/analytics
  placeholders, CSP, client-bundle credential/settings scan and no-Vite checks
  (`output/contact-tool-loop-clean-production-smoke-20261017.log`). These are local
  production-build checks, not testing or updating the public website.

The engineering suites above use no paid inference or real source/contact operation.
The subsequent separately recorded real-model diagnostic below is not a fake-suite
pass or general readiness proof.

## Independent real-model diagnostic, 2026-10-17

One fresh synthetic party used **three `gpt-6.1-sol` / low calls**, standard service
tier, at most 2048 output tokens per call and one isolated SQL ledger capped at
**$0.50 / three calls**, with SDK retries disabled. The exact model and $2 input,
$0.10 cached input, $2.50 cache-write and $10 output per million short-context
standard tokens were rechecked in the
[official model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
and [API pricing](https://developers.openai.com/api/docs/pricing). No configured
production model was changed. These are usage estimates, not invoice amounts,
subscription credits, long-context or regional/fast-tier pricing.

The ignored, one-party harness is `output/contact_tool_loop_quality_20261017.py`,
SHA-256 `5e8d4629c59d5abbb58bfd9964c9131f6cd7a22d307370aeae9a8d6b2f70afa4`.
An initial offline import error was corrected before the mock-HTTP offline pass;
it made no paid request. The real attempt is retained at
`/mnt/ssd2/mlq.4UhBeV/attempt/result.json`, SHA-256
`07d68d0fd191f888bbe61d8b31ca8c7e690377498d6b2b79a5956fc3990c4f72`.
It completed at **2026-10-17 13:21:51 UTC** with **25670 microusd ($0.025670)**
settled usage and **zero unknown hold**. The attempt directory is 0700 and result
0600; no provider credentials or opaque reasoning are printed. Do not rerun/resume
this party or alter its original `manual_review_pending` receipt.

The real model chose `sample_uz` then `sample_ru`, both `onboarding_help`, and
produced the final answer after exact native call/output continuation. The harness
uses the actual owning preparation, SQL state, bound window, session-context reader,
per-action reviewer grants and fake receiver. Two generated staff identities receive
separate exact approvals; author self-approval stays disabled. These are synthetic
repository identities, **not actual personal-session logins or HTTP/browser admission**.
The initial context is assembled with the real workspace instructions, not admitted
through the chat HTTP endpoint. No result grants a source, customer or production action.

There were **four fictional target reads and two fake acceptances**, zero external
sources and zero real contacts. A later user condition was preserved before model
continuation. Each request/new-nonce replay observed the same saved child without
another inference. The original two fixed RU/UZ messages were unchanged.
An independent read-only SQLite inspection confirmed two recorded preparations,
two verified actions, two review grants/audit events with different author/reviewer
identities, both actual decision actors matching their exact grant/fingerprint,
three settled model receipts, summed cost 25670 microusd and zero unknown receipt.

Manual semantic review passes **this single case**: the Russian final answer preserves
the requested order and no-discount constraint, distinguishes preparation from approval,
correctly reports fake `verified` acceptance, forbids repeat, and states that real
delivery and retention improvement were not measured. Its two cited times are the
actual SQL-result observation times, not claimed source/eligibility/receipt-write dates.
The first continuation's confirmation text is host-owned, not generated prose.
This does not prove broad task/model quality, production-human acceptance, causal
business benefit, complete multi-action planning or full Codex/Claude functionality.

## Remaining acceptance

The local browser/static/backend/UI/build, narrow clean-image compatibility and
production-mode lifecycle checks above are complete at their stated scopes.
The operational commit excludes parent-chat work. Preserve all old negative and
unknown receipts; no live diagnostic is implicitly resumed or repeated.
A separately approved scoped release and broad independent real-model/source/action
quality, live individual consent/billing/channel authority and measurable outcomes
remain open. Do not deploy or close the overall objective from this checkpoint.

One next UX gap is visible in the current code, not a failed semantic claim: the
contact continuation POST waits for inference, and the card calls `onContinued` only
in its `finally` block. Its SQL child exists earlier, but the browser does not yet
discover that child live through a journal notification. The existing chat stop API
can cancel it by ID; this is not proof that a user can see/stop the in-flight child
from this card without explicitly observing status or waiting. An ensuing increment
should expose truthful admission/status through the authenticated SQL observation
stream, preserving one-consumer, no-redispatch and cost reconciliation invariants.
