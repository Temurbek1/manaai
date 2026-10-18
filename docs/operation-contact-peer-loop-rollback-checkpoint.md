# Peer-reviewed contact loop — local rollback checkpoint, 2026-10-18

This continues the unchanged [nine-item agent workspace objective](operation-agent-workspace.md),
particularly durable tool results, separate human approval and rollback acceptance.
It does not complete that objective, release contacts or activate a source. The
[UI-only candidate](operation-chat-controls-ui-candidate.md) remains separate and
undeployed; its release request has not been answered. The application parent chat,
production services, keys, SSH, source data and schedules are unchanged.

## Gap addressed

The earlier v3 rollback fixture assembled private loop metadata but did not populate
a complete two-person grant/decision/action chain. The new optional
`WORKSPACE_CONTACT_PEER_LOOP_AUDIT=true` fixture uses the actual owning services and
HTTP admission to populate that history. It does not replace or retrospectively
broaden the earlier fixture's evidence.

The new peer history uses its own temporary `peer-history.db`. The original audit's
`synthetic.db` retains its unknown preparation, target guards and Goal history.
Combining those fixtures by clearing an unknown hold or bypassing a recipient
cooldown would invalidate the test; neither is done. No populated schema is
downgraded, and no old database is restored over later history.

## Actual fixture lifecycle

1. Two independently issued personal OTP/cookie sessions authenticate through the
   real ASGI endpoints. OTP delivery is captured locally: no Telegram request,
   development actor header or shared technical authentication is used. CSRF and
   origin checks remain enabled. These are fictional staff accounts, not proof
   that two credentials belong to different physical people.
2. A native Retention chat request enters the existing v3 protocol. The pinned
   OpenAI 2.53.0 SDK processes scripted Responses HTTP bodies through
   `httpx.MockTransport`, with a dummy key and SDK retries disabled. The host pairs
   each native call with its actual saved result before the next decision.
3. The owner explicitly prepares `sample_uz`, is denied self-approval, and shares
   its exact action fingerprint with the other registered staff identity. That
   reviewer cannot read the owner's transcript, Goal topic or private contact
   list. The reviewer separately confirms the exact action and receives a fake
   verified result. Repeating the same decision only observes SQL.
4. A separately confirmed continuation selects `sample_ru`. Its preparation,
   denied self-approval, exact disclosure and peer decision are independent. The
   following continuation is final-only. A new continuation nonce observes the
   already admitted child instead of inferring again.
5. A fourth, separate message loses its terminal model receipt through a synthetic
   `ReadTimeout`. It remains failed with a positive unknown cost reservation.
   Exact message replay retains that turn and hold, without another HTTP attempt.
6. Setup records only fixture IDs, typed requests, hashes and the fictional policy
   clock. It refuses an existing database or manifest, including an interrupted
   fixture. It never resumes or reseeds an old model attempt.

The resulting history contains **two verified fake actions, two reviewer grants,
their review/action/preparation audits, three settled mock usage receipts and one
unknown model hold**. Setup performs four fictional target reads and two fake
dispatches. The three terminal mock receipts each contain 100 input and 50 output
tokens. These scripted numbers and calculated rate-card amounts are accounting
assertions, not real OpenAI usage, invoices or model-quality measurements.

Only opaque fake continuation content is supplied; raw reasoning, credentials,
cookies and OTPs are not written to the manifest. The mock call/output/result shape
follows the host-owned [OpenAI function-calling flow](https://developers.openai.com/api/docs/guides/function-calling#the-tool-calling-flow).
OpenAI Docs informed the SDK fixture boundary, not a framework, SDK or model upgrade.
There are **zero paid inference calls, external source reads and real contacts**.

## Old/current image and reconstruction checks

The combined matrix ran with existing local images, no pull and `--network none`:

- Closed legacy `mana-ai-operation:2ea7b9a`, image
  `sha256:c2d322aec69f58ff1c9bad83017de70ce37db62c7eae12d96951ef82d6fa0dae`.
- Current clean v3 image `mana-ai-operation:contact-tool-loop-clean-20261017`, image
  `sha256:0dceda239e595ce1f7045c74a98558e67f2667f02fc427b5aa149bc69886a2ee`.

The new audit helper is mounted read-only into those images; application/runtime
code comes from each actual image. The old repository sees four closed public
turns with no action grant: three completed and one failed. Current host and image
reconstruct a fresh application, then replay preparation, peer decision, both
consumed continuations and the unknown message through the owning services.
Each reconstruction requires **zero model attempts, target reads and dispatches**.

Fingerprints before and after cover private chat/topic metadata, actions, guards,
preparation admission, review grants/audits, all cost reservations and cost-period
usage, plus the owner/reviewer's current role and status. Lifecycle assertions also
check that each decision actor is the selected different reviewer and each grant
matches the saved action. Negative tests detect deleted review audit, cleared
unknown usage, changed period accounting and reviewer disablement.

The original audit's three Goals are explicitly paused, then both databases are
checked again through old reader/current reconstruction. Those Goals and the new
peer history are in separate databases: this is not one integrated peer-contact
Goal capture or a live rollback of a running peer action. Restart verification
uses service-level replay, not a fresh browser/cookie login after image replacement.
No native execution is enabled in the legacy reader.

## Additional fresh-login HTTP observation

A separate new fixture at `/mnt/ssd2/mph.LpnZ6h/peer-history.db` passed setup,
actual closed `2ea7b9a` repository observation and then an additional current-image
HTTP diagnostic. Both Docker processes were networkless, with only the synthetic
database and read-only fixture helper mounted. The current application code came
from the actual clean v3 image listed above, not a host backend bind mount.

Two new OTP/cookie sessions logged in as the same saved owner/reviewer, without
relaxing OTP cooldown/rate policy. Real HTTP route parsing, personal authentication,
origin and CSRF checks then admitted exact preparation/peer-decision/continuation
replays and the failed message replay. The owner could read their transcript;
the reviewer still received 404 for that transcript, Goal topic and private contact
list. Both exact review pages remained available to the selected reviewer.

The process exited **0** (session `50783`) and its minimized receipt confirms two
verified action observations, two consumed continuations, retained unknown hold,
unchanged protected fingerprint and **zero model attempts, target reads or fake
dispatches**. Logs: `output/contact-peer-loop-http-setup-20261018.log`,
`output/contact-peer-loop-http-old-reader-20261018.log` and
`output/contact-peer-loop-http-restored-20261018.log`.

This closes the fresh personal-session HTTP replay gap for this one fictional
history. It is a one-off diagnostic using ASGI transport, not a newly registered
automated regression, real socket/TLS/ingress, browser, PostgreSQL, running-action
rollback or production acceptance. The original matrix's service-level checks and
its separate-Goal-database qualification above remain unchanged. No old paid
diagnostic, production history or unknown submitted call was resumed.

## Engineering receipts and qualifications

- Focused fixture/regression suite: **8 passed**, including repeat reconstruction,
  existing-database refusal and fingerprint mutations:
  `output/contact-peer-loop-tests-final-20261018.log`.
- Root UI suite: **214 passed /30 suites**. The root now also includes the isolated
  candidate's display-only `reading` → `thinking` status correction for an authenticated
  sequential text event. No backend, protocol or permission changes accompany it.
  Log: `output/contact-peer-loop-ui-20261018.log`.
- Root Ruff/format, ESLint, TypeScript and mypy **409 files** passed at this stage:
  `output/contact-peer-loop-static-final-20261018.log`.
- Clean operational OpenAPI/TypeScript regeneration byte-matched the existing
  schema, with explicit clean-export `PYTHONPATH`. Root secret/quality-marker
  scans and Compose validation passed. Logs:
  `output/contact-peer-loop-clean-schema-20261018.log` and
  `output/contact-peer-loop-security-20261018.log`. No parent-chat source or schema
  is included in the clean export; unrelated dirty files remain untouched.
- Actual legacy/host/current-image matrix passed before and after explicit Goal
  pause: `output/contact-peer-loop-image-final-20261018.log`. A preceding matrix
  also returned an observed process exit **0** in session `41059`; the final
  matrix's saved log reaches the complete success marker, but its numeric tool
  exit receipt was not recovered. Do not invent a separate observed exit code.
- Full clean operational **`make verify` passed**, with original session `88692`
  returning **0** and durable `MAKE_VERIFY_EXIT_CODE=0`: **1402 backend tests**,
  **214 UI tests /30 suites**, Ruff/format/ESLint, mypy **398 clean Python files**,
  TypeScript, production UI build and npm audit (**zero vulnerabilities**).
  Backend runtime was **36m09s**. **30 PostgreSQL cases were skipped** and **two
  opt-in live cases excluded**, not passed or rerun here; this patch changes no
  application SQL/concurrency contract. Export:
  `/mnt/ssd2/mana-peer-rollback-clean.FVAFSb`; log:
  `output/contact-peer-loop-clean-verify-20261018.log`. The original wrapper PID
  `615606` and pytest PID `616061` are terminal; do not wait for or restart them.

The seven-file source/test patch against `b58dade`, excluding the subsequently
written checkpoint documents, has SHA-256
`d13b186135c182d6ccc0885ae1971ca6d75f06c95750a5528a13586149d83e9c`.
Every one of those files byte-matches the clean export used for the completed gate.
No application backend, schema, dependency or production flag changes in this patch.

The first combined image run exposed a nondeterministic older admission fixture:
real UTC quiet hours refused its fictional proposal. That fixture now freezes a
yesterday-noon policy clock in its own manifest; production policy/quiet hours and
real receipt clocks are unchanged. Regressions at UTC 02:00 and 23:00 pass. Older
manifests without the new fixture date retain their previous observation behavior.
The failure log is preserved separately, not relabeled a pass.

Preliminary helper failures concerned HTTP status expectations, mock input shape
and explicit fake rate-card configuration; all used new fake databases. An invalid
mock response left its fake unknown hold intact. None was a paid diagnostic or
permission to resume a lost attempt. Existing negative real-model receipts remain
untouched, including their original manual-review qualifications.

This matrix is SQLite/synthetic engineering evidence, not a new PostgreSQL race
run, authenticated production-browser acceptance, real delivery, broad semantic
model quality, retention improvement or deployment authorization. Existing v15
Goal context is independently assembled/checked by the original core fixture;
do not claim an actual full peer-history Goal capture from this new peer database.
The local contact flags remain default disabled. Wider owning-domain/source/model
acceptance and separately approved rollout remain open under the original goal.

An independent subsequent UI-fix branch surfaced an ordering assumption in an
existing concurrent contact-loop test. Its failed run and read-only SQL observation
are retained under `output/explicit-native-goal-*-20261018.log`; that separate
branch's diagnostic is not a pass. This checkpoint's original complete gate remains
a pass, not proof that every race ordering was covered. A deterministic reproduction
and correction belong to the separate follow-up; no production behavior was changed.
