# Evidence dates: conversational quality and shared source display

Status: **local checkpoint, not deployed**, 2026-10-14. The full administrative
workspace objective remains open. Production still runs the separately approved
`a7752dc`; this checkpoint does not activate sources or change production settings.

## Problem and implementation

The [original eight-case matrix](operation-workspace-matrix-checkpoint.md) found
collection timestamps described as SQL-save/observation dates. Its immutable
pre-fix outputs retain that defect. Shared chat/Goal instructions subsequently
clarified collection, report creation, observation windows and SQL storage.

The UI had the same ambiguity: chat said “Данные:”, Goals showed an unlabelled
collection date and “Подтверждён”. Goals also missed malformed expiry and future
collection timestamps in their display warning. Both now use a shared pure helper:

- `collected_at` is explicitly “Сбор данных”; missing/malformed values are unknown,
  never replaced with report/Goal creation timestamps.
- Recent collection/expiry metadata says only “Срок кэша не истёк”, not verified
  activity, population coverage or fulfilment of the requested observation window.
- Missing, future or inconsistent timing fails closed for display; expiration
  changes the displayed state, including cached/live evidence.

The helper does not fetch, grant, execute or change server admission. Existing chat
expiry timers and Goal observation/control mechanisms remain. Source details stay
collapsed; no new buttons, providers, schedules, public schemas or checkpoints.
React guidance keeps labels derived from existing props/time, not extra effects.

## New isolated real-model diagnostic

`scripts/operation_workspace_evaluate.py --case-suite evidence_dates` adds **two new
fixed cases**, rather than replaying the eight-case party. Default administration
cases remain unchanged. Plan-only mode does not load settings/credentials. Candidate
native execution still requires tracked limits, exclusive new output and actual
isolated SQL. Neutral titles/opaque IDs prevent expected-label leakage.

The new suite has one shared **10-call/$0.49** ceiling, gpt-6.1-sol/medium, existing
8192-output and context limits, test-only 210/240-second Goal timeouts and no SDK
retry. Expected review checks are not model inputs. No application factory,
production connection, customer source, contact, action or schedule is started.

One new party completed with **nine settled calls**, estimated **$0.114375**, unknown
hold **0**, source attempts **0** and production changes **0**. This is rate-card
accounting, not an invoice or daily production forecast. It includes one verified
priced invalid review JSON and one existing bounded format correction, not a
transport/source retry or a new party.

The first conversational answer correctly distinguishes collection 01:57:47 UTC,
report generation 02:07:47 UTC and cache expiry 07:07:47 UTC. It keeps observation
period/cohort cutoffs/SQL-save time unknown, rejects seven-day coverage inferred
from collection, marks the source synthetic and does not create a Goal/read.

The second preserves the complete current-data seven-day objective. It actually
inspects, loads the full saved source and searches the catalog, then generates
a useful partial analysis. Independent bound review leaves Goal
`413cb341-79ad-4edd-821d-28500a72569b` **waiting in review**, seven steps, one recovery,
no unsettled cost, read/grant or limit stop. Both original target checks are failed:
missing real observation periods, behavior/funnel and payments prevent completion.
It does not substitute an easier objective or claim improved customer retention.

Manual arithmetic: 72/120 = 60% D1, 36/120 = 30% D7, 44/110 = 40% comparison;
30−40 = −10 percentage points and (30−40)/40 = −25%. These are hypothetical
source calculations, not measured current cohort rates or a proven trend. D1/D7
intersection, mature observation cutoffs, causes, behavior and payments remain
unknown; children are not the denominator. Proposed 07–13 October UTC coverage
is explicitly a future measurement choice, not an observation from this report.
The Goal tool evidence does not expose a report-generation timestamp; its draft
honestly leaves that separate fact unknown, unlike the chat's supplied metadata.

Original plan/SQL/results and a separate manual review:
`output/evidence-date-quality-20261014/independent-01/`. Original result SHA-256:
`eae98b85287844d6d498bf2f92077ac56a2f283a85973b2818749f283c9b1e70`.
Budget DB: `ce834d6dc7964565efca36d2fb19f3f4a24638b1f0a6003fd97d36f5ee8a83da`.
The original pending manual-review field and all prior attempts/holds are unchanged.

Method: inspect the full persisted decision/tool/draft/review trace, following
[official OpenAI trace grading](https://developers.openai.com/api/docs/guides/trace-grading).
Validation and data-quality guidance distinguishes a correct missing-data stop
from a completed business objective: **share with caveats**, not overall readiness.

## Deterministic and browser evidence

The 61 focused UI checks cover shared labels, invalid/missing/future/inconsistent
timing, cached expiry, no provider fetch and existing collapsed/expiry behavior.
Nineteen offline harness checks cover both suites through actual SDK fake SSE/SQL,
isolated sources, original objectives and classified/unknown usage stops.

Native browser → API → SQL → fake model/tool → result/reload passed, including
source collection labels matched to API metadata, same-room handoff, progress
reconnection, questions, limits, long retained context, complete catalog text,
sandbox receipts, ownership, CSRF and mobile accessibility. The legacy chat/manual
approval flow also passed, including its stale-source label and visible warning.
Mobile renders were inspected; no logged-in customer session or live source was
used. The first new browser assertion selected a tool-journal row rather than the
source list; its corrected selector passed without changing application behavior.

Final `make verify` passed against the complete changed worktree: **1220 backend
and 165 UI tests**, Ruff/format/ESLint, mypy 348 files, TypeScript, production UI
build and npm audit (0 vulnerabilities). The 23 PostgreSQL cases remain separately
skipped prior persistence evidence; two live suites were deliberately excluded.
No schema change was made. Browser-dev route imports were restored by the final
production build. These gates do not replace authorized production/source or
broader model-quality acceptance.

## Remaining full-scope work

This is post-clarification quality evidence for these two cases, not a blanket pass
for the earlier eight-case matrix, a completed real MANA analysis, statistical
accuracy or Codex/Claude parity. Real source/extended-session acceptance, compatible
production release/authenticated browser checks and Retention-first owning-domain
actions remain. No new release/read permission is inferred, and no protected Goal,
lost model/source request, unknown hold, key, SSH/main/audio/UI production service
or source schedule is changed by this checkpoint.
