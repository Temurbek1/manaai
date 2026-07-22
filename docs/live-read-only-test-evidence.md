# Live read-only test evidence

Evidence is intentionally split so deterministic tests never require Meta and live access never
becomes an accidental default.

## Live evidence (2026-07-22)

- Graph/Marketing API: `v25.0`
- Account: alias `2b6c4ddcc5`; exactly one accessible account
- Credential/account health: passed
- Period: 2026-07-15 through 2026-07-21, completed days only
- Inventory/Insights: all zero rows; 13 compatibility checks explicitly empty
- Transport: 15 GET requests, 15 pages, 0 retries, 0 provider errors
- Analytics: one `insufficient_data` finding
- Advisory output: one `observe`, one `propose_test`, zero proposals, zero executions
- Calibration: latest bounded rerun version 13, all 15 account overrides unavailable/inherited;
  the initial documented validation was version 7
- Nightly report: structured and human-readable records persisted
- Portable report: schema, source interaction, 1440px and 390px rendering, overflow, and external
  request checks passed
- Ads Manager UI comparison: pending manual values in `docs/meta-data-reconciliation.md`

No POST or DELETE was sent. No real Meta mutation test exists or is permitted.

## Fixture and fake-provider evidence

Hermetic tests cover pagination/deduplication, account selection, mixed currency/attribution,
delayed conversions, missing metrics, compatible and invalid breakdowns, transient/permanent/rate
errors, request reservation before transport, token-health sanitization, analytics/reporting,
advisory lifecycle, API authorization, and frontend live-read-only language. Fake Meta remains the
executable provider used to test the governed action lifecycle without external effects.

The explicit provider boundary test attempts live execution and asserts the exact typed 403 response,
zero provider calls, and a redacted `write_forbidden` audit event.

## Test separation

- Default `make test` excludes the `live_meta` marker.
- Live tests require `META_LIVE_READONLY_VERIFY=1` and are invoked separately by the live Make target.
- Tests never use a real OpenAI request.
- The live verification script rejects non-read-only configuration before constructing the workflow.

## Final repository-wide verification

`META_LIVE_READONLY_VERIFY=1 make meta-live-readonly-verify` passed end to end:

- Ruff format/lint and strict mypy: passed for 111 Python source files;
- backend: 95 passed, one documented PostgreSQL skip, and one live deselection in the hermetic run;
- frontend: 16 Jest tests, Prettier, strict TypeScript, Next-aware ESLint, optimized/standalone
  builds, bundle scan, and npm audit passed;
- focused safety suite: 28 passed; mutation audit caught 15/15 safety mutations;
- SQLite clean round-trip/drift/existing-copy and PostgreSQL upgrade/downgrade/drift audits passed;
- PostgreSQL integration: 1 passed;
- Python and npm dependency audits: no known vulnerabilities (local package is not on PyPI);
- secret/quality-marker/OpenAPI/Compose checks: passed;
- browser E2E: fake collect through approved execution, verification, audit, and report passed;
- marked live Meta health: 1 passed;
- live Next.js Marketing page: enforced read-only state, safe alias, no execute control, and
  desktop/mobile no-overflow checks passed without action mutations;
- canonical portable report: validation, packaging, source interaction, desktop/mobile, overflow, and
  external-request checks passed through the repository-owned generator.
