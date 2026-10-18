# Chat controls — UI-only candidate, 2026-10-18

This is local preparation toward the unchanged [nine-item workspace objective](operation-agent-workspace.md),
not a production release or a claim of full agent parity. The owner has not yet
answered the request to release only the interface after compatibility checks.
No production write, source refresh, contact, paid inference or schedule change is authorized here.

## Clean boundary

- Worktree: `/mnt/ssd2/mana-ui-controls.KbB3wt`.
- Local branch: `release/ui-chat-controls-20261018`, based on actual released UI `faf0a78`.
- Verified local candidate commit: `c198132d4d00a1d3ed742ca704269683fd68e905`.
  It has not been pushed or deployed; this root document records its receipt separately.
- That baseline's application/backend files match operational production `38cdac4`.
- Runtime changes only `ChatPage.tsx` and `useChatTranscript.ts`, with two UI test
  files and two isolated fake-browser fixture/harness files.
  Backend, migrations, API schemas, dependencies and the professional analytics
  screens remain byte-identical to the released baseline.
- It contains no private Retention contact pages, preparation/admission, peer reviews,
  native v1/v2/v3 contact contracts or local action-control UI. The broader `8eb86be`
  branch/image must not be substituted for this isolated UI candidate.
- The independent parent-chat branch, its private key/history/volume and all unrelated
  dirty root files are outside the candidate. No `.env` is copied into this worktree.

## Included behavior

An admitted answer is stoppable while the original message POST is pending. If a
Goal is also active, the composer control targets the visible chat turn rather
than silently pausing the Goal; Goal pause remains in its own controls. The paginated
SQL head actually revalidates during active submissions instead of reusing a stale
cache. A fast first reply in a newly created topic refreshes its exact owner-scoped
SQL key, not the pre-creation/null hook closure. No control retries inference or
renews a source/action grant. Stop does not undo a completed action or waive usage.
An authenticated, sequential `thinking` text event also updates display status;
otherwise a cached `reading` turn incorrectly said it was still reading reports
while answer text was already arriving. This UI correction changes no server state
or tool authority. It was first isolated in this candidate; the subsequent
[peer-loop checkpoint](operation-contact-peer-loop-rollback-checkpoint.md) also
ports this one-line display correction to the private contact-bearing root workspace.

The fresh-topic cache fix is carried over from the already tested operational
source because `faf0a78` predates it. It changes only existing authenticated SQL
GET/cache handling; no new route, capability or response field is introduced.

## Current evidence and outstanding work

- Final **186 UI tests / 26 suites passed**, including legacy/paginated pending-message
  stop, simultaneous Goal/chat stop priority and a fast first native reply.
  A new status regression failed before the `reading` → `thinking` display fix.
- Candidate static gates passed, including mypy **350** baseline Python files and
  TypeScript. No backend source changed.
- The original full **`make verify` passed**, and session `12368` returned **0**:
  **1241 backend tests**, **186 UI tests / 26 suites**, Ruff/format/ESLint, mypy
  **350** Python files, TypeScript, production build and npm audit with **zero
  vulnerabilities**. Backend runtime: **24m29s**. **23 PostgreSQL cases were skipped**
  and **two opt-in live cases excluded**, not passed or rerun separately here.
  Log: `output/ui-chat-controls-verify-20261018.log` ends with durable
  `MAKE_VERIFY_EXIT_CODE=0`. Original pytest PID `566724` is terminal; do not restart
  that handle. UI/fixture amendments preceded the final UI/build phases and received
  separate fresh lint/typecheck/UI checks; application/backend source never changed.
- The original full private browser passed, session `32056` exited **0**:
  `output/ui-chat-controls-browser-20261018.log`. It covers existing native/professional
  UI fixtures, Goal limits/catalog/history, RU/UZ/mobile/accessibility and no real
  sources or paid inference. It ran before the subsequent text-status-only fix.
- Two new focused actual browser → old API → SQL → fake stream Stop probes passed
  (sessions `64814` / `28324` exited **0**), the second after the status correction.
  Exactly one message and one explicit Stop, a cancelled SQL row, no new Goal,
  reload with no redispatch, correct writing status, RU/UZ and 320px accessibility
  were verified. Final pending/cancelled screenshots were visually inspected.
  Logs/screenshots: `output/ui-chat-controls-stop-browser*-20261018*`.
  These probes do not prove a real provider's final usage receipt or fee-free Stop;
  the 12-second generator and all data are fake. All local server ports closed.
- The candidate production UI build passed. Existing authenticated-session placeholders
  for root/runs/analytics, liveness and CSP passed in standalone mode. **27 client
  text assets** passed the key/server-setting scan; no private contact route/control
  identifiers were found in static assets, and no-Vite checks passed.
- OpenAPI/TypeScript regeneration with explicit candidate `PYTHONPATH` byte-matched
  the released schema. Backend/migrations, dependency manifests, Compose and root
  Dockerfile still byte-match `faf0a78`; only the stated UI/tests/harnesses differ.
- Image `manaai-admin-nextjs:chat-controls-candidate-20261018` built as
  `sha256:af9fe9fdb0a3ca4a155602bdb464ba747b1f70ed99f153e77193e6a453506f70`.
  The actual local image passed health/protected placeholders/CSP as non-root,
  networkless and read-only with only a private temporary tmpfs; no credentials,
  data volumes or host ports were supplied. This is not authenticated production
  or proxy/backend acceptance; its build proxy points at the generic local `api` service.
- Secret/quality-marker scans passed (**590** Git-listed/unignored paths, with the
  private venv symlink skipped). The optional full Compose audit first refused missing
  interpolation variables, then the absent `.env`; those failures are retained.
  Syntax validation with explicit dummy DB values and `--no-env-resolution` passed,
  without creating/copying `.env` or touching real keys. That narrower check is not
  fully resolved production-configuration acceptance.

Build/schema/smoke/security logs: `output/ui-chat-controls-*-20261018.log`.
The six-file runtime/test/fixture patch against `faf0a78` retained exact SHA-256
`c9b1d14d01f8f4ac9e5b46b0847a74e1e96793a519ce0bdc2cba4626e6a3483b`
before and after the completed full gate. A browser-generated `next-env.d.ts`
dev-path change was restored rather than included. The private `.venv` symlink
is not part of the candidate, image or commit.

One read-only server-connectivity probe used existing key-based noninteractive SSH
with strict host checking and failed with `Permission denied (publickey,password)`.
Password login was not attempted; this is not proof that every authorized access
method is unavailable. No login mechanism, SSH file or server setting was changed.

The local code/UI/build/image checks above are complete at their stated scopes;
they do not complete the full agent objective or authorize rollout. Keep all failed
attempts. Production rollout requires the owner's separate approval, fresh service/config/
Goal/unknown-hold fences, a retained UI image/config backup, exact compatible proxy
targets, a bounded canary, UI-only switching and verification. No database restore,
schema downgrade, backend/worker/container restart or automatic Goal retry is implied.

While rollout awaits approval, the broader objective still has a concrete local
release-acceptance gap: the existing v3 compatibility fixture constructs synthetic
chat results but does not populate a complete two-person grant/decision/action chain.
The next rollback increment should exercise that real owning-service fake lifecycle
through old-reader/current-image/pause/reconstruction without real sends, new source
access, schema downgrade or replay. It must not relabel the older narrow probe as
complete grant-history acceptance or complete the overall goal from this UI candidate.

The subsequent [local peer-loop matrix](operation-contact-peer-loop-rollback-checkpoint.md)
addresses that fixture gap through actual owning-service fake actions and personal
HTTP admission. Its checks and limitations are separate; they neither change this
UI candidate nor approve its release.
