# Local single-chat lab checkpoint — 2026-10-24

This is an isolated test interface and API-documentation increment, not a
production release or completion of the externally blocked conversion goal.
The source checkout is `/mnt/ssd2/mana-conversion-agent-20261021`; the dirty IDE
checkout and shared production services were not changed by this implementation.

## API surface

The recommended `mana-chat` group has exactly three operations: review-first
message admission, observation of the original message UUID, and single history.
Backend specialist ingestion, conversion events, contact context and coordination
are grouped separately. Independent stateless analyses do not automatically
participate in chat. Existing synchronous operations are deprecated in schema
metadata only: no handler, request/response, security or persistence change.

The generated OpenAPI comparison against feature baseline `4e6084c` retained all
104 main paths /111 operations and all component schemas, with only tag and
deprecation changes. The product export retains 42 paths /46 operations. The lab
is not mounted on either production factory or included in their schemas.
This does not establish that every legacy operation is unused in production;
removal still requires an owning-client migration and actual usage evidence.

## Isolated browser flow

`make chat-lab` starts the loopback-only standalone app. It uses actual
Parent-Touch, Child-Safety, conversion policy, event worker and private SQLite,
but a deterministic simulated model and one fictional family. Separate explicit
`chat-lab-live` permits configured paid models, not live family data or writes.
That paid mode was not exercised in this increment. Both modes preserve 2000
raw chat tokens/day plus 2000 global Child-Safety tokens/day, durable unknown
holds and separate mode-marked directories. Exact real context may exceed those
limits; a refusal does not authorize a reset, replay or budget increase.

There is no Firebase/GA4/Manakids family-data adapter, grant adapter or push
gateway. No real customer ID is accepted, including test parent `4`. Templates
and paid terms are explicitly fictional; no payment, transaction, free tariff
or contact is created. The lab has host/loopback checks, a private HttpOnly
SameSite session cookie, CSRF plus exact Origin validation, body limits and CSP.
The browser never receives backend or model credentials.

Observation polls local SQL only. Lost acknowledgements retain the original
UUID; reload/navigation/status reads never resend work. A definitive refused
admission plus absent SQL state unlocks only the UI. An unclassified failure
retains its unresolved identity rather than creating a new nonce.

## Actual acceptance

- Focused fake-only backend checks cover one chat, proactive first question,
  question/answer binding, child alert, offer/paid events, idempotent replay,
  restart, Uzbek Latin response, quota/source isolation and negative access.
- Five browser-controller tests cover normal completion, lost acknowledgement,
  definitive refusal, unclassified failure and GET-only reload observation.
- Actual isolated Chromium at desktop and 390-pixel mobile sizes verified offer
  publication before parent text, sleep question, bound reply, dated urgent
  child notice and persisted history on reload, with no browser errors.
- The browser lost-acknowledgement diagnostic made exactly one simulated POST;
  original-ID observation completed, cleared its draft and pending/error UI,
  and settled 600 simulated tokens in each separate ledger. No paid model ran.
- Screenshots remain under local `output/chat-lab-20261024/`, outside the commit.

Full `make verify` session **34669**, terminal exit **0**: **1014 backend tests**
passed, one skipped, two opt-in live tests excluded; **26 admin tests** and
**5 lab controller tests** passed. Ruff format/lint, ESLint with 34 compatibility
checks, mypy **289 files**, TypeScript and Next production build passed.
Dependency audit reports **zero vulnerabilities** after compatible transitive
lock updates `undici 7.30.0 → 7.30.1` and `zod 4.4.3 → 4.6.7`; primary dependency
versions and guarded overrides remain unchanged. A clean `npm ci --ignore-scripts`
was used before this final gate; no audit suppression or forced upgrade.

Earlier full session **14036** failed the old exact Swagger-tag assertion;
the expected group set was corrected without weakening schema checks. Session
**79894** passed tests/build but failed the newly surfaced dependency audit.
These remain failed runs, not earlier green acceptance. Focused session **4327**
passed 22 tests before the final full gate. Final secret/diff checks are recorded
in the owning handoff; no secrets, SQL stores or test-output artifacts are staged.

No production process/configuration, source refresh, customer contact, grant,
SSH setting, shared key or schedule was changed. This lab is not an old-image
rollback, candidate-image acceptance, real-model quality or business-outcome
measurement. Do not publish it as production, replay old paid parties, or use
the simulated offer as authorization to contact real parents.
