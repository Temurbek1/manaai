# Review-first family messages — 2026-10-20

Local, default-disabled implementation after `920cc3f`; no production release.
This implements the coordinated workflow missing from the
[specialist checkpoint](mana-family-specialist-checkpoint.md). Old negative
receipts remain negative: this is a new protocol, not a replay or retrospective
quality pass for synchronous messages.

## Implemented contract

`POST /api/v1/mana-ai/parent-touch/messages` saves a parent's text and returns
`202` with its durable `turn_id`, `request_id` and `phase=awaiting_review`.
`GET /parent-touch/messages/{request_id}?parent_id=123` observes that same turn;
it cannot dispatch, retry or read an external source. A completed state contains
the normal Parent-Touch `response`, including its invisible question/reply binding.
The same single chat is visible through `GET /parent-touch/chat` and legacy `/chat`.

1. SQL atomically saves the parent message, exact request digest, optional answer
   binding, language reference, quota reservation and bounded review snapshot.
   This new private protocol delays communication-choice capture; historical
   synchronous turns retain their original capture/order/digests.
2. The existing event worker claims and runs one separately budgeted Child-Safety
   review. Fresh own-child profiles and dated saved evidence remain required.
   Parent text is self-reported context, never a fresh sensor reading or tool grant.
3. Only a successful terminal review can release a communication claim. SQL freezes
   its complete bounded guidance, parent-message/review dates and authorized child
   set, then selects at most one question and existing qualified notice/context.
4. Parent-Touch rechecks fresh ownership before its one inference and communicates
   the specialist's guidance. It is the only chat speaker; the specialist never
   inserts an assistant message. Revoked guidance cannot be heuristically redacted
   and reused: it fails closed if its reviewed child set is no longer authorized.
5. Replay returns the saved state/result without source/count/model work. Two
   concurrent workers cannot claim the same communication. A lost claimed worker
   is not reclaimed for generation; a lost submitted receipt retains its hold.

The existing **five-minute preparation deadline** bounds review waiting/input
preparation, not a promise of instant delivery or cancellation of a submitted model
call. Exhausted specialist budgets may leave a message waiting until that deadline.
Expired queued reviews cannot start a paid call. A late known review still records
its cost but cannot publish a question/result after its original parent turn has
expired. A failed speaker choice cannot automatically resurface as a new delivery
at midnight. Unknown calls are never refunded, retried or discarded.

Use this endpoint for new app integrations. The earlier `POST /parent-touch/chat`
and legacy `/chat` intentionally remain synchronous compatibility paths; they do
**not** acquire review-first semantics or silently upgrade old request IDs.
New sensor observations use the ten typed Child-Safety routes, not the message
request. No Firebase/GA4 refresh, listener, schedule, push or device-control action
is installed by this workflow.

## Configuration / private storage

New `MANA_PARENT_TOUCH_REVIEW_FIRST_ENABLED=false` requires all three existing chat,
Parent-Touch and Child-Safety flags plus explicit safety server/parent/job limits.
The active adapter adds only `family_reviewed_messages`, upgrading private SQLite
to **v6**. The captured safety review bit is serialized only when true; old false/
absent contexts and persisted legacy bytes/digests are preserved, never recaptured.

Same-candidate deactivation supports a **v6 closed broker** with no safety model/
worker: saved reviewed-message GET/exact POST replay still work, new admissions
refuse. Disabling Parent-Touch provides the existing history/exact legacy replay
reader at v6. Keeping safety enabled on v6 while disabling the captured review-first
runtime refuses startup rather than downgrading storage or silently executing an
incompatible protocol. Old v5/production images cannot read v6. Never restore an
old database over newer messages; old-image rollback is not accepted.

## Verification

Final `OPENAI_API_KEY=unit-synthetic-key make verify`, original session **67339**,
terminal exit **0**, ignored log `output/family-review-first-fenced-verify-20261020.log`:
**509 backend tests**, **1 skipped**, **2 opt-in live excluded**, **26 UI tests /
11 suites**, Ruff/format/ESLint, mypy **247 files**, TypeScript/build, zero npm
vulnerabilities. Schema synchronization, diff checks and secret scan **412 files**
passed. Earlier 507-test gates remain historical, not substitutes for the final
late-publication/failed-choice regressions. No test used a live provider or source.

Candidate `mana-ai-family:review-first-fenced-20261020`, SHA256
`d4e3af2582278abad12458626f69a1677e30abebc3ede4662998d30618a29e87`, passed the
actual packaged-app smoke, original session **76745**, terminal exit **0**:
network disabled, read-only root, temporary private SQLite, no capabilities and
no-new-privileges. **Eight** SDK MockTransport generations/**ten** fake profile
reads verified the v5 legacy lifecycle and the new v6 review-first/closed-broker
HTTP lifecycle. Zero real provider/source calls or production mutations. This is
same-candidate acceptance, not old-image rollback, real ingress or real-family QA.

Tests cover concurrent admission/claim, review-before-speaking, bound answers,
separate budgets, no-dispatch GET/replay, HTTP auth/privacy/conflicts, restart/day
unknown holds, abandoned claims, queue expiry, revoked children, late metered
reviews, no automatic quota retry, v5 preservation and v6 closed readers.

## Independent paid synthetic diagnostics

Both parties used fresh fictional families/ledgers, GPT-5.4 Parent-Touch and
GPT-5.4 mini Child-Safety, unchanged 2000-token chat ceilings and separate explicit
safety limits. Each party had an independent conservative admission cap below
$0.50; neither was replayed. Tests themselves use only fakes/SDK MockTransport.

| Main-workspace ignored output directory | Result |
| --- | --- |
| `family-review-first-20261020-0DIjUQ` | 8 known generations, $0.01685300 estimated. Both RU/UZ question -> bound answer -> review -> speaker loops completed/replayed. Chat totals 1599/1827. UZ advice followed specialist guidance; RU follow-up was unhelpfully thin. |
| `family-reviewed-guidance-20261020-YWpkGn` | 8 known generations, $0.01717575 estimated after the useful-next-step prompt. Both loops completed/replayed; chat totals 1691/1741. Speaker's sleep-duration calculation/advice followed the actual specialist guidance, not independent condition judgment. |

This increment: **16 generations /$0.03402875** conservative uncached estimate,
not an invoice. Combined retained family diagnostics: **135 /$0.21582965**. No
unknown receipts/holds, real families, Firebase/GA4 or production calls. The final
host-only late-publication fences were added after these parties and have separate
fake/candidate checks; they do not rewrite either model receipt.

Manual quality remains qualified, not comprehensive: the second party's specialist
internally assumed a father without evidence (not displayed by Parent-Touch), and
one question asked weekday/weekend variants of the same bedtime information need.
The small matrix does not prove broad language/safety quality, current real-family
coverage, emergency delivery, business outcomes or unlimited conversation. Do not
erase these qualifications or call token savings a causal quality result.

## Handoff boundary

The two-agent API workflow is available for local/backend integration. Production
activation still needs a separately authorized scoped release, volume backup,
isolated ingress/credential checks and app-owned channel/ownership acceptance.
The urgent notice is quota-limited chat, not an emergency service or push guarantee.
Existing parent-chat `f2c023f`, main/audio, OPERATION agents/UI, keys, SSH and source
schedules remain unchanged. The practical backend contract is in the
[integration guide](mana-family-agents-integration.md).
