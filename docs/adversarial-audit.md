# Adversarial production-readiness audit

Audit date: 2026-07-22

## Scope and method

This audit treated prior reports as unverified claims. The implementation was reconstructed from
imports, composition, routes, persistence models, migrations, provider calls, scheduler code, and
the React client. The review then used negative API tests, independent reference calculations,
concurrent repository/API tests, deliberate safety mutations, clean SQLite and PostgreSQL
migrations, dependency and secret scans, and a browser lifecycle against the real API and fake
provider. No live Meta request and no real provider write was made.

The effective boundaries are:

```text
app/mana_ai                       product capability contracts; no operation dependency
app/mana_operation_ai/domain      provider-neutral state and typed action contracts
app/mana_operation_ai/application use cases, policy, analytics, recovery, ports
app/mana_operation_ai/infrastructure SQLAlchemy and fake/Meta HTTP adapters
app/mana_operation_ai/api         internal RBAC API and controlled HTTP errors
app/mana_operation_ai/background  persisted scheduler and standalone worker
admin-ui                          OpenAPI-typed React operator client
app/main.py                       composition root
```

The operational slice does not use the Meta Python SDK. It uses an async, bounded `httpx` Graph API
client inside infrastructure. No raw Graph response object crosses into application/domain code.
This is simpler than wrapping generated SDK objects but makes fixture and official-contract tests
mandatory.

## Findings

### Critical

| Evidence | Possible damage | Fix and regression proof | Remaining risk |
| --- | --- | --- | --- |
| Financial POSTs shared the read retry loop, so a timeout or retryable 5xx after an applied write dispatched again. | Duplicate spend/budget changes or a false failed state after a real change. | **Fixed:** writes are single-dispatch and become `executing/write_outcome_uncertain`; recovery only re-reads state. `test_action_recovery.py` and Meta transport tests prove one dispatch and reconciliation. | Actual Meta ambiguity behavior still needs an authorized non-spending canary; no live write was attempted. |
| Proposal/approval creation, approval decisions, run creation, and action finalization used split persistence operations without all required uniqueness. | Orphaned approvals, duplicate decisions/executions, or an applied provider write recorded inconsistently after a crash. | **Fixed:** atomic repository methods, unique constraints, insert-first idempotency, and transactional execution/verification finalization. Concurrent HTTP decisions and 12/16-way SQLite/PostgreSQL contention pass. | A post-write database outage intentionally leaves `executing` for reconciliation; operators must not issue a manual duplicate. |
| A due schedule could advance without a completed occurrence and had no atomic distributed occurrence claim. | Lost jobs after worker death or duplicate runs under multiple schedulers. | **Fixed:** occurrence leases, advance-after-success, lease-expiry recovery, and a dedicated worker. Two-worker, missed-occurrence, and dead-worker tests pass. | PostgreSQL is required for multiprocess production; SQLite is explicitly local/single-process. |

### High

| Evidence | Possible damage | Fix and regression proof | Remaining risk |
| --- | --- | --- | --- |
| The admin client sent an asserted `admin` role and persisted its key in browser storage. | Misleading UI authorization and recoverable credentials after refresh/XSS. | **Fixed:** server-resolved `/session`, memory-only credentials, default viewer, and role-derived controls; API remains authoritative. Component and browser RBAC tests pass. | Shared role keys do not provide individual attribution and block real-write rollout. |
| Reaching `META_MAX_PAGES` returned the rows collected so far even when `paging.next` existed. | Recommendations from silently incomplete account data. | **Fixed:** fail closed with `MetaPaginationLimitError` and a sanitized diagnostic; pagination cutoff fixture test passes. | The configured bound must be capacity-tested against the intended live accounts. |
| Graph failures collapsed into broad transport/API errors without authentication, permission, not-found, or uncertain-write semantics. | Unsafe retry, wrong HTTP response, or an object deletion mistaken for a transient outage. | **Fixed:** typed infrastructure errors and provider-neutral mappings; official-contract-shaped error fixtures and API failure tests pass. | Synthetic fixtures cannot prove every live Graph subcode/version variant. |
| Analytics mixed base/breakdown rows and attribution/currency scopes, summed non-additive reach, and derived ratios from invalid negatives. | Wrong spend efficiency and unsafe scale/pause recommendations. | **Fixed:** query-scope separation and deterministic Decimal calculations. An independent reference calculator covers duplication, zero/missing/negative data, reach, currency, attribution, lag, small samples, outliers, partial baselines, aggregation, shared creatives, and DST. | Provider-side measurement quality and delayed-conversion completeness remain external data risks. |
| Action parameter models admitted direction/status contradictions and were too close to arbitrary JSON intent. | A recommendation could reach the adapter as a different financial/status action. | **Fixed:** discriminated parameter unions validate direction, exact status transitions, currency, and audience shape; allowlist/domain tests and mutation checks pass. | Adding a future action type requires a new typed model, policy, adapter mapping, and tests. |
| Execution did not revalidate every active policy/configuration, expiry, hash, currency/minimum, kill switch, and target lock immediately before dispatch. | An approved but stale action could violate current policy or change the wrong provider state. | **Fixed:** all checks execute under the provider-object lease after a fresh read. Negative API/concurrency tests and safety mutations cover every guard. | Live provider minimum/currency responses still need GET-only validation before write enablement. |
| SQLite omitted relationship constraints/indexes that production semantics relied on; PostgreSQL behavior was not exercised. | Duplicate records, broken references, slow scheduler queries, or deployment-only races. | **Fixed:** enforced FKs, uniqueness, indexes, reversible migrations, drift checks, and isolated PostgreSQL 17 contention tests. | Restore rehearsal and production sizing remain deployment work. |
| Auditing the locked environment found advisories in the old FastAPI/Starlette and pytest versions. | Exposure to known framework/test-runner vulnerabilities and unreliable security claims. | **Fixed:** compatible pins were upgraded; the full suite, `pip-audit`, and high-severity `npm audit` pass. | Dependency audits must remain a recurring CI/release gate. |

### Medium

| Evidence | Possible damage | Fix and regression proof | Remaining risk |
| --- | --- | --- | --- |
| Broad schedule updates admitted timezone and identity fields without the required validation/recalculation boundary. | Invalid next runs or accidental schedule identity changes. | **Fixed:** narrow `ScheduleUpdateRequest`, immutable identity, timezone validation, and next-run recomputation; hostile API tests pass. | Schedule edits during a claimed occurrence preserve that occurrence and apply to the next one by design. |
| Local-time cron calculation mishandled nonexistent and folded DST minutes. | Missed or duplicate scheduled jobs at timezone transitions. | **Fixed:** UTC-minute search with explicit gap/fold behavior and independent DST tests. | Host clock synchronization is an operational prerequisite. |
| Local authentication defaulted to admin and production accepted wildcard CORS; failures had no bounded in-process throttle. | Accidental privilege in development-like deployments and a broader browser attack surface. | **Fixed:** default viewer, required production role keys, wildcard rejection, and failed-auth throttling; security/API tests pass. | Multi-replica throttling belongs at a trusted gateway. Header-key auth has no cookie-CSRF surface. |
| API and static UI responses lacked a consistent browser security-header policy. | Clickjacking, content sniffing, or looser script execution after a separate injection defect. | **Fixed:** API headers plus Nginx CSP/frame/content/referrer/permissions policy; header tests and production build checks pass. | CSP must be retested if external assets or inline scripts are introduced. |
| Legacy narrative analysis embedded provider/raw strings without explicitly marking them as data. | Prompt injection could distort a report or request secret/tool/policy behavior. | **Fixed:** the system prompt declares every JSON value untrusted and rejects embedded role/tool/secret/policy commands; capture test passes. Operational findings/actions remain deterministic and typed. | LLM narrative remains untrusted output for human review and cannot authorize actions. |
| The admin UI had only two happy-path tests and no real-browser lifecycle. | Permission, failure-state, or accessibility regressions could ship unnoticed. | **Fixed:** 11 integration tests cover RBAC, approvals, expiry/failure/partial states, controls, schedule/config, runs, pagination, reports, XSS/redaction, responsive and keyboard behavior; fake-provider browser E2E passes. | Full assistive-technology and cross-browser certification is outside this slice. |
| Meta coverage used inline examples and no explicitly bounded GET-only workflow. | Fixture drift or an unsafe ad hoc credential test before rollout. | **Fixed:** typed fixtures plus a smoke command that requires explicit confirmation, aborts if writes are enabled, and prints only aggregate diagnostics. | Live validation remains open and is explicitly required before real writes. |

### Low

| Evidence | Possible damage | Fix and regression proof | Remaining risk |
| --- | --- | --- | --- |
| Repository protocols exposed unused execution/verification update methods beside atomic finalization. | Future callers could create partial state while assuming a generic supported capability. | **Fixed:** removed; `finalize_action_state` owns the transaction and repository/type checks pass. | Revisit only when a concrete second lifecycle requires a different atomic boundary. |
| Documentation presented the pre-slice baseline and single-process scheduler as current. | Operators could deploy an unsafe topology or misunderstand the security model. | **Fixed:** the baseline is marked historical and architecture/runbook/deployment documents match Compose; drift searches and `docker compose config --quiet` pass. | Documentation still requires release-time review when topology changes. |

### False positives

| Hypothesis | Result |
| --- | --- |
| Meta SDK objects leak into domain code. | false positive: there is no Meta SDK dependency; raw dictionaries remain inside the infrastructure adapter. |
| An LLM calculates operation KPIs or emits arbitrary write payloads. | false positive: operation analytics are deterministic Decimal code and writes use discriminated action models. The separate legacy report endpoint does use OpenAI for narrative interpretation. |
| CORS/cookie CSRF can approve an action without authentication. | false positive for cookie CSRF: the service uses header keys and no authentication cookie. CORS is still restricted in production. |

## Documentation discrepancies found

- `current-state-audit.md` described the historical repository baseline (no UI, ORM, migrations,
  roles, or retry behavior) but read as current state. It is now explicitly historical.
- `runbook.md` said the API container migrated and ran the scheduler. Compose now has a one-shot
  migration service, scheduler-disabled API, and scheduler-enabled worker.
- `admin-panel.md` and README said the key was stored in the current tab/sidebar. Login is now a
  server-verified screen and credentials exist only in memory.
- `testing.md` listed only two frontend tests and no PostgreSQL, mutation, dependency, schema,
  secret, or browser gate. `make audit-verify` now owns that complete matrix.
- `architecture.md` implied one shared SQLite file and a single-process scheduler as the production
  path. Local compatibility remains SQLite; Compose uses PostgreSQL plus a standalone worker.

## Accepted and open risks

- **closed for the supported mode:** bounded live Meta GET validation proved credentials, one account,
  USD currency, account time zone, endpoint access, empty-result handling, and zero provider errors.
  Non-empty pagination/conversion behavior remains fixture-tested and does not authorize writes.
- **open for shared human accountability:** production role keys map to shared internal identities.
  Put individual authentication and identity propagation at a trusted gateway; live Meta remains
  read-only regardless.
- **accepted for current internal deployment:** authentication throttling is in-process. A
  multi-replica public edge needs distributed or gateway rate limiting.
- **accepted for local development only:** SQLite cannot substitute for PostgreSQL multi-process
  semantics. Production topology requires PostgreSQL.
- **accepted operational condition:** an ambiguous provider write intentionally remains
  `executing` until reconciliation. Operators must not issue a second manual provider write.
- **open for production operations:** load/capacity/SLO evidence, backup/restore rehearsal, alert delivery,
  on-call ownership, and Meta sandbox/live canary evidence are external deployment work.
- **open compatibility boundary:** the legacy marketing API still has direct SQLite and a separate
  OpenAI narrative path. It is preserved for compatibility and is not the financial execution
  path.

The vertical slice is production-oriented for fake-provider/internal validation and ready for an
explicit read-only Meta connection exercise. It is not approved for real Meta writes.
