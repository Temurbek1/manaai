# Meta permissions and credential handling

## Observed credential state

The 2026-07-22 token debug and read test succeeded for account discovery, structure, and Insights.
Relevant observed scopes included `ads_read` and `business_management`. The token also exposed
write-capable or otherwise broader scopes, including `ads_management`; this application still
forbids every Meta write independently of token capability.

The debugger returned `expires_at=0` and `data_access_expires_at=0`. The service reports these raw
semantics as “no finite timestamp returned,” not “never expires.” Health should be checked before
each controlled live validation and monitored for token/authentication error classes.

## Least privilege target

- Prefer a dedicated Meta system user for this service.
- Request `ads_read` for advertising reads.
- Retain `business_management` only when business-owned/client account discovery requires it.
- Remove `ads_management` and unrelated product scopes from the replacement credential where Meta
  asset and app-review rules permit the required reads.
- Give the system user access only to the intended ad account and business assets.
- Keep the app in the appropriate Meta access/review state for assets it does not own.

Meta's official collection documents user and system-user tokens, permission selection, account IDs,
and pagination: [Marketing API requirements](https://www.postman.com/meta/facebook-marketing-api/collection/0zr4mes/facebook-marketing-api-mapi).
The official SDK also recommends App Secret Proof for server calls: [Meta Python Business SDK](https://github.com/facebook/facebook-python-business-sdk).

## Storage and rotation

Store `META_ACCESS_TOKEN` only in the deployment secret manager or an ignored local `.env`. Never put
it in Git, images, frontend bundles, report artifacts, URLs, or support tickets. Logs record only a
hashed account alias and a sanitized operation name.

Rotation procedure:

1. Create and asset-scope the replacement system-user token.
2. Install it in the secret manager without revoking the current token.
3. Restart the API/worker and run the bounded health and live read-only verification.
4. Confirm the exact account alias, relevant scopes, currency/time zone, and GET-only request log.
5. Revoke the old token and record the rotation in the private operations log.

On suspected exposure, revoke first, disable live scheduling, rotate application/role credentials,
inspect provider and application audit logs, then re-enable only after a clean bounded validation.
