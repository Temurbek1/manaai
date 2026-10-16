# Parent chat — historical local implementation checkpoint, 2026-10-16

This records the pre-release implementation phase. The later authorized production
deployment is documented in [mana-parent-chat-release.md](mana-parent-chat-release.md).

This is a new, independent application API task. The broad operational workspace
goal remains paused; its preparation-admission WIP has not been resumed or shipped.
No production deployment, source activation, credential change, real source read or
paid model invocation was performed for this implementation.

## Delivered scope

- GET/POST `/api/v1/mana-ai/chat`, one canonical profile/Firebase parent ID per chat.
- Backend-only token authentication, including in local mode; the MANA backend
  must derive the parent ID from its own authenticated session, not client input.
- Dedicated private SQLite/WAL history, atomic per-parent daily token reservations,
  bounded context, exact request/body replay, pending/unknown protection and paging.
- A fresh, filtered MANA Parent API profile/relationship read on each new request,
  with byte/time/row bounds and no transport retry or collection enumeration.
- Optional typed backend observations: owned connected child IDs, dates, screen
  time, at most five apps, battery and a short location label. They are not a direct
  Firestore integration or independently verified live behavioral evidence.
- Same-language/script instruction, explicit partial-memory/date qualifications,
  no tools/actions, and a strict raw terminal input/output usage boundary before
  answer validation. Count and generation use identical semantic input.
  A verified oversized count can trigger one additional sizing call without old
  pairs; current question/facts and full saved history remain intact. No failed
  count/source/generation is retried.
- Default disabled. Default allowance: 2000 combined input/output tokens per
  admission day, Asia/Tashkent reset; 512 output cap, two previous completed pairs,
  20 new attempts/day. Unknown submitted requests remain held across resets.
- Standalone and combined API wiring, public OpenAPI/docs export, generated admin
  schema/types and Docker volume paths. No operational schema migration is needed.

Main files: `app/api/routes/mana_ai_chat.py`, `app/mana_ai/domain/chat.py`,
`app/mana_ai/application/{chat_ports,parent_chat}.py`,
`app/services/parent_chat_{store,children,model,runtime}.py`.
Integration contract: [mana-parent-chat.md](mana-parent-chat.md).

## Verification boundaries

Automated checks use synthetic families, dependency overrides and the pinned real
OpenAI SDK with HTTP mocks, not live customer data or provider calls. The tests
exercise replay/restart, independent SQLite connections, quota/reset/unknown holds,
source ownership, observation dates, strict provisional/raw receipts, auth and the
enabled/disabled lifespan. A passing fake test does not establish model language
quality, account access, a production parent binding or multi-host capacity.

The earlier focused runs passed 68, 71 and 84 overlapping cases. The final focused
run passed **85**, including the added history-sizing regression. These counts
are not additive. The whole-project run collected before that final additional
case passed **1428 backend tests**, with 29 skipped and 2 opt-in deselected; its UI
phase passed **209** tests. Final scoped checks cover the subsequent prompt/history
refinement; do not describe the earlier full collection as including the new case.

- `output/mana-parent-chat-verify-20261016.log`: `make verify` stopped at an
  existing paused-WIP Prettier issue in `contactPreparationAttempt.test.ts`.
  This is **not** a green full gate; the unrelated paused file was not reformatted.
  The final rerun in `output/mana-parent-chat-verify-final-20261016.log` confirmed
  the same blocker, with all 402 Python files passing the format check.
- `output/mana-parent-chat-checks-20261016.log`: independent `make lint typecheck test`.
  Completed successfully: 1428 backend /209 UI passes as qualified above.
- `output/mana-parent-chat-focused-final-20261016.log`: final 85 scoped cases passed.
- `output/mana-parent-chat-static-final-20261016.log`: final `make lint typecheck`
  passed, including strict mypy on 402 Python files and TypeScript.
- `output/mana-parent-chat-ui-tests-20261016.log`: 209 UI tests passed independently.
- `output/mana-parent-chat-build-20261016.log`: production UI build passed.
- `output/mana-parent-chat-npm-audit-20261016.log`: zero npm vulnerabilities.
- `output/mana-parent-chat-docker-20261016.log`: standalone Python 3.12 image built.
  A network-disabled container verified enabled startup/private storage/empty
  history without operational services. It did not verify a model response or
  a production release. The local dirty-tree image is not a deployment candidate.
- `output/mana-parent-chat-docker-final-20261016.log` and
  `output/mana-parent-chat-image-smoke-final-20261016.log`: final source image build
  and networkless startup/private-store probe passed. Local image fingerprint:
  `sha256:3f0a3ec07a5e96bbd7a255aa4a4ba83e17dd04b70c992999d01fb7efd5caee3a`.
- Generated OpenAPI sync, secret scan and standalone compose validation passed.

## Before release

1. Obtain explicit deployment scope; do not ship the paused contact WIP. Preserve
   its files and the production versions recorded in the pause/release documents.
2. Confirm APP_API_KEY is restricted to the trusted MANA backend. Do not grant
   personal history to an untrusted/shared client; split deployment/credentials if
   the existing key is shared with other applications. Do not embed it in mobile.
3. Configure the opt-in flag, a writable durable **single-host** chat volume and
   read-only MANA service credentials. Never point this store at another database.
4. Perform a separately controlled smoke with a legitimate authenticated test
   parent's exact ID, actual upstream permissions and bounded model usage. None
   of the synthetic cases is proof that arbitrary Firebase/Auth IDs are mapped.
5. Agree child-data disclosure, encrypted disk/backup, history lifecycle and manual
   handling of unresolved usage. The API has no public quota-unblock/reset/delete
   endpoint and must not erase unknown holds as a recovery shortcut.
6. Retain the existing API/audio, SSH, sources and schedules unless explicitly
   authorized otherwise. There is no new GA4/Firestore listener or auto-refresh.
