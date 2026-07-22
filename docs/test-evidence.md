# Test evidence

## Verification entry points

`make verify` runs formatting, Ruff, ESLint, mypy, TypeScript, backend/frontend tests, the frontend
production build, and the npm high-severity audit.

`make audit-verify` additionally runs:

- focused architecture, concurrency/recovery, repository, redaction, and Meta fixture tests;
- the safety mutation audit;
- tracked/unignored secret and approved TODO/skip scans;
- generated OpenAPI/TypeScript synchronization;
- clean/reversible SQLite migration and schema drift checks;
- isolated PostgreSQL 17 migration and concurrency verification;
- Python and npm dependency audits;
- a fresh-database browser lifecycle using the real API and fake provider.

The PostgreSQL test has one explicit collection-time skip in the ordinary SQLite suite and is
executed with `TEST_POSTGRES_URL` by `scripts/postgres_audit.sh`. The marker scanner allowlists only
that exact opt-in skip.

## Verified 2026-07-22 result

- Python: 89 passed, 1 documented PostgreSQL opt-in skip; the isolated PostgreSQL run then passed.
- Frontend: 6 files and 11 tests passed; lint, typecheck, and production build passed.
- Focused architecture/safety/provider suite: 25 passed.
- Mutation audit: all 15 deliberate invariant violations were caught.
- SQLite and PostgreSQL: upgrade/downgrade/upgrade and autogenerate drift checks passed.
- Dependencies: no known auditable Python vulnerabilities and zero npm vulnerabilities.
- Browser: fake data through run, finding, separate-actor approval, execution, verification,
  audit, and report passed against the real API.

The historical baseline collected 32 Python cases (31 passed and one environment-isolation failure),
so the audited slice has a net 58 additional Python cases. The new admin UI contributes 11
frontend tests, plus the 15 isolated mutation probes and one browser lifecycle gate.

## Adversarial matrix

| Area | Scenarios proved |
| --- | --- |
| architecture | direct and transitive MANA AI boundary, domain/application dependency direction, no request/service locator in business layers, provider payload confinement |
| analytics | exact Decimal ratios, zero/missing/negative values, duplicate/base/breakdown rows, non-additive reach, mixed currency/attribution, conversion lag, DST |
| Meta | cursor pagination, cutoff failure, rate limits, transient/permanent classification, token-safe diagnostics, account currency/minimum, typed normalization, no write retry, multi-step uncertainty |
| finance | stale/expired/deleted object, policy changed/removed, config removed, kill switch timing, provider minimum/currency, absolute/factor delta, cooldown/daily limits, wrong/partial/eventually consistent provider value |
| identity/RBAC | no implicit admin, viewer denial, self-approval denial, role-key resolution, failed-auth throttling, bulk homogeneity |
| concurrency | 12-way SQLite and 16-way PostgreSQL lock/claim/run creation, concurrent HTTP decision, per-object write lease, transaction rollback/recovery |
| scheduler | two schedulers, dead worker, due occurrence retention, DST, job timeout, retry/idempotency |
| API | malformed values/UUID-shaped identifiers, enum validation, pagination limits, duplicate requests, extra/mass-assignment fields, invalid timezone, controlled upstream errors |
| frontend | login/session, viewer-disabled controls, approval/rejection/expiry, failed/partial/executing states, global/agent kill switches, configuration/schedule, manual run, loading/error/empty, mutation failure, pagination/filter, report/timeline, redaction/XSS, responsive/keyboard navigation |
| security | ignored `.env`, no browser storage, no dangerous HTML, structured log redaction, security headers/CSP, production CORS, bundle/OpenAPI inspection, secret scan, dependency audit |

## Mutation evidence

`scripts/mutation_audit.py` applies each mutation in an isolated temporary repository copy and
requires the named regression test to fail. All 15 are caught:

| Mutation | Catching evidence |
| --- | --- |
| allow self approval | operation API self-approval test |
| bypass global kill switch | operation API kill-switch test |
| use float for financial math | operation domain Decimal test |
| dispatch provider write twice | recovery one-dispatch test |
| ignore proposal expiry | expired proposal API test |
| ignore stale expected state | stale-state API test |
| remove provider-object lock | concurrent object-lock API test |
| ignore maximum budget delta | action policy absolute-delta test |
| execute without active policy/config | missing-policy/config API test |
| include access token in diagnostic | Meta redaction test |
| omit verification commit | operation E2E persisted-verification test |
| permit invalid state transition | domain transition test |
| duplicate scheduler occurrence | scheduler concurrency test |
| allow viewer approval | RBAC API test |
| import operation repository from MANA AI | architecture boundary test |

## Browser lifecycle

`scripts/browser_e2e.sh` starts a fresh temporary database, API, and Vite client. The fake adapter
creates its own provider snapshot during startup; the script does not insert finished database
rows. It performs:

```text
login operator -> run agent -> inspect finding/proposal -> sign out
-> login different approver -> approve scale action -> provider write -> verification
-> reject remaining action -> inspect succeeded execution/report
-> open completed run -> inspect approval/execution/verification/report audit events
-> verify responsive menu and Escape behavior
```

The audit also manually confirmed that trying to approve as the same browser actor returns `403`.
No OpenAI or live Meta endpoint is called by automated tests.

Final command counts and the exact successful `make audit-verify` run are recorded in the final
audit handoff; command exit status, not this document, is the source of truth.
