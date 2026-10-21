# Conversion candidate-image checkpoint

Application source: `efc9645`, branch `feat/mana-conversion-agent-20261021`.
This checkpoint adds a reusable hermetic diagnostic and integration documentation,
not a production deployment or a claim that real-user tracking is complete.

## Actual image and source verification

Built locally with the existing `Dockerfile.mana-ai` and locked dependencies:

```text
mana-ai-family:conversion-efc9645-local
sha256:88193f53d363dd12cee994806ffdb14e40e616a8747ebee8fd7764a0450c3995
```

All **184 packaged application Python files** match source SHA-256 values. The
combined sorted path/hash manifest is
`83e1c41887377e3f8ca4505ca060b11355490165acb1a8efb3a1a3ab06e121ff`.
No `/app/.env` exists in the image. Docker runs as the image's non-root `app` user.

Both diagnostics used the actual packaged `/app/app`, not a mounted source tree.
Only the diagnostic scripts were mounted read-only. Runs used `--network none`,
`--read-only`, `--cap-drop ALL`, `no-new-privileges`, `APP_ENV=production`, and
temporary in-container SQLite storage. No host customer database/credential file,
port, production container, SSH or external data source was used or modified.

## New conversion lifecycle

Harness: `scripts/mana_conversion_smoke.py`; actual container session **51438**,
terminal exit **0**.

The actual product ASGI routes, application lifespan/worker, pinned OpenAI SDK,
strict usage parsing, SQLite adapters, Manakids grant adapter and push adapter
ran with MockTransport. These are fake provider decisions, not real model quality.

Verified:

- Authenticated account/contact admissions for three fictional parents.
- First offer in the single chat before parent text, with no profile/model call
  for the deterministic offer itself.
- A real worker publishes that saved message and queues the generic push through
  the documented HTTP adapter. A positive device queue is not phone delivery.
- Review-first parent reply passes through Child-Safety then Parent-Touch, with
  the frozen commercial terms in the speaker input, not model write permissions.
- Explicit backend acceptance dispatches one non-paid three-day Maxsus grant.
  A confirmed receipt and an unknown write each yield their own same-chat result.
  Identical acceptance replay never repeats the grant.
- A separately confirmed expired free-access snapshot selects the valid paid
  synthetic offer, never the higher-priority free grant.
- Current closed-v9 retains message-state replay and refuses new conversion
  admission. GET/replay does not call a model/source or dispatch a notification.
- Actual v1 -> v6 seed -> v9 migration preserves exact legacy chat/quota row
  fingerprints. The unknown submitted legacy call retains its **2000-token hold**
  after activation, closed-mode restart and observation.

Observed totals: **4 fake generations /4 fake input counts /4 fake profile reads**,
**2 mocked grant writes /3 mocked push writes**, five fresh mocked logins.
**Zero** real inference, sources, grants, contacts or production mutations.
The diagnostic's larger explicit synthetic server pool is not the production
Child-Safety allowance; production remains 2000 global tokens/day.

The first local harness attempt incorrectly asserted that cumulative model/profile
counts were zero when beginning a later fictional family. It failed. The corrected
assertion compares counts immediately before and after that family's new offer;
no application behavior or policy was weakened. Typed diagnostic annotations were
also corrected before full verification. The failed attempt is not relabelled.

## Existing family workflow

The same image ran `scripts/mana_family_agents_smoke.py`, container session
**95171**, terminal exit **0**. Existing child safety/urgent notice, review-first,
idempotent replay and closed v5/v6 behavior passed: **8 fake generations /10 fake
input counts /10 fake profile reads**, zero real source/provider calls.
This is a separate diagnostic, not extra backend test-count credit.

## Full local gate

`make verify`, original session **10748**, terminal exit **0**:

- **781 backend tests passed**, one skipped, two excluded; 53.18 seconds.
- **26 UI tests /11 suites** passed; Next production build passed.
- mypy **274 files**, TypeScript, Ruff, UI lint/format and 34 compatibility checks passed.
- Dependency audit: zero vulnerabilities.

The new hermetic diagnostic is included once in the backend count. English backend
event documentation was separately validated against `ConversionSnapshot`.
Final secret/diff checks are recorded in the WIP after documentation is complete.

## What this does not establish

- No production image was deployed, no real device notification was sent, and no
  live model quality was evaluated by these deterministic responses.
- Candidate deactivation is supported with this image and private v9, not an old
  v8/`f8d095e` image rollback or database restore over new history.
- An authoritative all-parent subscription/activity producer is not installed.
  Current Parent List omits the necessary paid/free/trial/consent/activity facts.
- Synthetic approved prices are not a real checkout-approved discount. Interest,
  a free grant and a provider queue are not paid conversion or measured uplift.
- The original full objective remains open. The source owner must supply the
  missing [backend contract](mana-conversion-backend-events.en.md), actual billing
  offer terms and channel integration before a separately scoped contact release.
