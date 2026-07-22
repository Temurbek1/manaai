# Action safety

## Defaults

- Operation dry-run is enabled.
- Live Meta writes are forbidden; the adapter exposes no write path.
- Budget increases, decreases, pause, resume, and audience changes require approval.
- Self-approval is disabled.
- Missing/invalid configuration cannot authorize an action.
- Global and per-agent kill switches are checked at run acceptance and immediately before action.
- Global and per-agent daily execution limits are conservative and include dry runs.
- Budget factor, percentage decrease, absolute change, confidence, and cooldown are configured.
- Every provider write is serialized by a database-backed lock scoped to provider, object type, and
  provider object ID. The lock covers the final policy check, fresh state read, write, and
  verification, preventing different concurrent proposals from changing the same object at once.

## Authorization

Internal roles are ordered `viewer < operator < approver < admin`. Viewer reads; operator runs
agents; approver decides/executes approved actions; admin changes configuration, schedules, status,
kill switches, and users. A browser actor is the stable durable user UUID joined from an opaque
server session; role and status are re-read on every authenticated request. Caller-selected role or
actor headers cannot establish browser identity. Self-approval compares the approval initiator with
that UUID. Constant-time-compared technical role keys remain available only for service-to-service
automation and use synthetic identities unless the trusted service supplies an actor with its valid
key.

Bulk approval is restricted to homogeneous budget-decrease actions. Bulk rejection also requires a
homogeneous action type. Approval requests expire and are persisted with a system decision.

## Failure behavior

- A stale provider state creates a failed execution and proposal before returning HTTP 409.
- A current safety block returns 423 and keeps an approved action retryable through the explicit
  execute endpoint after the control is resolved.
- An occupied provider-object lock returns 423 before a provider write; the approved proposal stays
  retryable and an expired worker lock is recoverable after the configured job timeout.
- Provider failures are recorded as failed; stack traces and credentials are not returned.
- Verification mismatch is `partially_applied`, not success.
- Interrupted `executing` actions are re-read by hourly reconciliation.
- Reports expose pending and failed actions rather than hiding them.

## Secrets

Settings use `SecretStr`; API/UI contracts contain configuration status, never secret values. Meta
tokens are added only to outbound request parameters. Structured application logging replaces known
secret values and named access, bot, HMAC, session, CSRF, and OTP assignments. The UI contains no
human key/password flow and writes no identity secret to browser storage. OTP/session/CSRF plaintext
values are absent from persistence and audit; refresh uses the HttpOnly cookie and sign-out revokes
the database session. Disable revokes every user session. See `telegram-otp-auth.md`.

## Live Meta boundary

There is no supported procedure for enabling live Meta writes. `META_REAL_WRITES_ENABLED=true` and a
live provider with `OPERATION_DRY_RUN=false` are rejected at startup. The Meta client rejects POST
before token lookup/transport, the provider adapter rejects execution, the lifecycle persists
advisory-only proposals, the API returns `write_operation_forbidden`, and the UI has no live execute
control. Fake Meta remains available for executable lifecycle tests and demonstrations.
