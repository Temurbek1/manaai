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
and kill switches. Production uses separate constant-time-compared keys. A client-supplied actor ID
is ignored in production; the role key maps to a stable internal identity so changing a header cannot
bypass self-approval. Put individual identity at an authenticated gateway before sharing keys among
people.

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
secret values and named `access_token`, `api_key`, `authorization`, and `client_secret` assignments.
The UI keeps an internal API key only in module memory, uses a password input, never writes the key
to browser storage, and never reads a key back from the API. Refresh and sign-out clear it.

## Live Meta boundary

There is no supported procedure for enabling live Meta writes. `META_REAL_WRITES_ENABLED=true` and a
live provider with `OPERATION_DRY_RUN=false` are rejected at startup. The Meta client rejects POST
before token lookup/transport, the provider adapter rejects execution, the lifecycle persists
advisory-only proposals, the API returns `write_operation_forbidden`, and the UI has no live execute
control. Fake Meta remains available for executable lifecycle tests and demonstrations.
