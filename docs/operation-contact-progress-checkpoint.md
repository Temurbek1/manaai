# In-flight contact continuation — local UI checkpoint

This increment continues the original nine-item [agent workspace objective](operation-agent-workspace.md),
especially truthful progress and stop/reload behavior. It does not complete that objective,
deploy contacts or change the separate application parent chat. Production, sources,
refresh schedules, keys, SSH and main/audio are untouched.

## Behavior and boundaries

After explicit **Continue with agent**, the UI starts observing the same private SQL
transcript while the existing continuation POST is pending. The admitted child becomes
visible with its real status and existing **Stop answer** control, before inference
returns. Requests are tracked separately by owner/topic/originating turn; completing an
old request cannot clear another topic's pending state. New ordinary messages remain
blocked while this request is pending. Stop targets the actual admitted child's ID,
not its already executed contact action or the browser fetch.
If a Goal is also running, this control stops the visible chat answer first; Goal
pause remains available in its own workspace. Ordinary admitted chat answers are
also stoppable while their send POST is pending: the old `disabled={sending}`
condition incorrectly blocked that control. Existing SQL stop remains idempotent.

The existing paginated hook had `revalidateFirstPage=false`: SWR 2.4.2's interval
reused the cached head instead of reading it. The fix revalidates the first SQL page.
The established two-second polling runs only during a pending submission or while
the transcript contains active work. Paging earlier history can also refresh the
head; this is bounded local SQL observation, not GA4/Firestore auto-refresh.

Explicit continuation scrolls to the new work, as ordinary send already does.
Passive updates still preserve a user's position when they scroll up. The small
RU/Uzbek Latin pending label describes observation, not private reasoning or a
claim that a cancelled model is still generating. The manual status button refreshes
the transcript when SQL reports an existing continuation, without another POST.

No server contract, stored metadata, feature flag, migration or event protocol changes.
This intentionally reuses authenticated REST observation rather than adding a second
journal or treating contact continuations as streamed model tokens. Existing SSE
remains unchanged. Old v1/v2/v3 turns are not upgraded. Closing/reloading/navigating
does not stop work or redispatch inference/contact writes. A lost acknowledgement
permits SQL observation only, never an automatic retry.

The existing SQL one-consumer and stop fences remain authoritative. A late verified
receipt still settles cost, but cannot replace cancelled state with an answer or
another native request. Unknown submitted usage retains its hold. A confirmed fake
contact result remains verified after stopping its explanation; stop is not rollback,
unsend, delivery confirmation or measured retention improvement.

OpenAI Docs was used to compare the observable turn/progress/interrupt lifecycle in
[Codex App Server](https://learn.chatgpt.com/docs/app-server#lifecycle-overview).
This implements that interaction distinction using the existing application runtime,
not Codex's proprietary implementation or complete Claude/Codex parity.

## Engineering evidence

- The valid pre-fix regression failed in both legacy and paginated history because
  no Stop control appeared before the continuation POST completed. A preliminary
  fixture-only failure used an invalid null contact message and is not product evidence.
- After the pending-state change, the paginated case still failed, exposing the cached
  first-page defect. With revalidation fixed, both cases pass, including cross-topic
  navigation while the old POST is still pending and no extra generation/action POST.
- The expanded actual SDK/mock HTTP/SQL test passes: a deferred inference is observable
  before its receipt; another owner cannot read it; two stops and result replay do not
  infer again; the late verified cost settles; the existing action stays verified;
  no second preparation or send is created. Its local fixture explicitly enables
  development actors and fictional self-review; it is not personal-session acceptance.
  The first assertion incorrectly expected anonymous 401 despite that development
  fixture; the corrected check confirms private-topic 404 instead, without auth changes.
- Final clean UI suite: **213 tests / 30 suites passed**, including simultaneous
  Goal/chat stop priority and the ordinary pending-send stop regression. The latter
  failed before removing the incorrect disabled state. RU/UZ literal coverage caught
  a missing status-button translation before the corrected pass. Ruff/format, root
  mypy **407 files**, ESLint and TypeScript passed at the recorded stage.
- The first full private browser passed two distinct personal reviewer logins and
  separately confirmed fake actions, then observed/stopped a deliberately delayed
  final continuation and reloaded without replay. Visual review found that the
  active mobile transcript still showed the older card. After explicit-continuation
  scrolling, a fresh assertion still failed when the harness resized an already
  active desktop conversation; the mobile case now starts on mobile before Continue,
  without forcing the result into view. A following harness run queried the old RU
  stop label after switching to Uzbek and timed out. Both failed logs remain.
- The full fresh private browser **passed**, original session `7696` exited **0**
  (`output/contact-progress-browser-reload-20261017.log`). Its 320px Uzbek screenshot
  shows both the actual active child status and Stop control and was visually inspected.
  Two personal reviewer logins, separate exact confirmations, delayed fake inference,
  stop/reload, no third action, Goal/history/catalog/stream/CSRF/accessibility
  regressions pass. The preceding run passed the contact scenario but raced the
  existing reload-scroll assertion; the final harness waits for that existing layout
  effect without forcing scroll. The ordinary-send disabled-state removal followed
  this browser run and is covered separately by the final 213-case clean UI suite.
  The fixture uses no paid inference or real source/contact data. All local server
  ports closed after exit.
- Clean OpenAPI regeneration/synchronization passed and its JSON hash matches HEAD;
  no API changes ship. The first clean audit accidentally imported the editable root
  package because PYTHONPATH was omitted; explicit clean PYTHONPATH regenerates the
  original operational schema. The subsequent secret scan could not list files in a
  non-Git export. Root `make audit-security` then passed (673 tracked/unignored files),
  including secret/quality-marker scans and Compose validation, without external writes.
- The original clean operational-only **`make verify` completed every logged stage**:
  **1394 backend passed**, **213 UI tests / 30 suites passed**, Ruff/format, ESLint,
  mypy **396 clean Python files**, TypeScript, production UI build and npm audit
  (**zero vulnerabilities**). Backend runtime was **31m34s**. The **30 PostgreSQL
  skips** are not passes or a new PostgreSQL run; the previous unchanged backend's
  separate checks are recorded in the v3 checkpoint. **Two opt-in live cases were
  excluded**, not passed. Log: `output/contact-progress-clean-verify-20261017.log`.
  Source: `/mnt/ssd2/mana-contact-progress-clean.cXpOTy`.
  Original session `68103` was no longer available after an intentional conversation
  interruption, and pytest PID `331090` no longer existed. The complete saved log
  ends after the successful final npm audit, with every subcommand's success output;
  the tool's final numeric exit receipt was not recovered. Do not wait for or restart
  that terminal handle, or claim a separately observed exit code.
  UI amendments were applied before UI tests/build, with separate fresh format,
  lint/typecheck and 213-case UI gates; backend source was unchanged after the full
  gate began. The nine source/test/harness files match the staged export byte-for-byte.
- The final clean standalone production UI build passed, with liveness, protected
  root/runs/analytics session placeholders and CSP; its **28** text client assets
  passed the credential/server-setting scan, and no-Vite checks passed
  (`output/contact-progress-clean-build-20261017.log`,
  `output/contact-progress-clean-production-smoke-20261017.log`). This is not an
  authenticated production-browser test or a full backend-proxy exercise.
- Clean UI image `manaai-admin-nextjs:contact-progress-clean-20261017` built as
  `sha256:d2a6c8fc73ed67901ed3e17f334ed08f80a705fefc439da4131fab909929e2be`.
  The actual image passed liveness/protected placeholders/CSP as non-root, with
  `--network=none`, read-only root and a small private `/tmp` tmpfs
  (`output/contact-progress-clean-ui-image-20261017.log`,
  `output/contact-progress-ui-image-smoke-20261017.log`). No credentials, source data
  or persistent volumes were mounted. Its proxy build target is the local `api`
  service; this is not production-ingress/rollback acceptance or a release.
- Two independent public read-only GET checks returned `{"status":"ok"}` from
  `https://ai-frontend.360rec.uz/healthz` and `/api/v1/health/live` during verification.
  No SSH/deploy/source call was made. This checks existing liveness only, not the
  new UI being deployed, authenticated production behavior or domain readiness.

Logs are under `output/contact-progress-*-20261017.log`; they contain no real source
reads or paid inference. Keep the earlier negative receipts. A clean scoped release,
production-human acceptance and wider model/action/business-outcome quality remain
separate open obligations. No source/contact production activation is authorized.
