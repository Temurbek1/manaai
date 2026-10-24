# Shared family source runtime — local increment, 2026-10-24

The subsequent [native workflow](mana-native-source-workflow.md) adds captured
model-selected reads and family schema 11. Its flag remains default disabled;
this document preserves the earlier runtime/source-only evidence below.

The server runtime can now construct the existing bounded own-child Firestore
battery reader, shared private cache and optional source-to-Child-Safety consumer.
This is implementation progress on the full autonomous single-chat objective,
not production activation or completion of model-selected source tools, the
09:00/15:00 collector, GA4 aggregate sharing or all document scenarios.

## Configuration and execution

`MANA_FAMILY_SOURCES_ENABLED` defaults to false. Enabling it requires the existing
Parent-Touch runtime, explicit `FIREBASE_PROJECT_ID`, `FIREBASE_DATABASE_ID`, a
readable `FIREBASE_SERVICE_ACCOUNT_FILE`, and
`MANA_FAMILY_FIREBASE_MANA_CONFIRMED=true`. This last switch records the owner's
confirmed MANA data binding; it never changes Google IAM. The key's project,
principal domain and universe must match that configured binding. There is no
public-read fallback, automatic project discovery or model-controlled endpoint.

`MANA_FAMILY_SOURCE_DATABASE_PATH` must be separate from chat, marketing,
operation and credential storage. Existing schema-2 policy, budget, snapshot,
unknown-hold and consumer-admission rules remain unchanged. Neither startup
nor normal SQL worker polling fetches Google data. The server exposes
`ParentTouchService.sources.read_child_battery(FamilySourceTarget(...))` to
typed internal orchestration. It is not a mobile endpoint or an unrestricted
query interface. A future native model-selected tool must durably bind its
original invocation and meter its model calls before dispatching this service;
that tool loop is not implemented by exposing this server method.

`MANA_FAMILY_SOURCE_SAFETY_ENABLED` independently enables the existing source
consumer on a Child-Safety worker. Its policy is frozen at source-change capture;
enabling it later cannot upgrade earlier disabled events. A dated, eligible
new observation may produce a specialist job, with the existing separate token
budget and Parent-Touch communication lifecycle. It is not authority to invent
recipient preferences, send push, grant a tariff or bypass the sole speaker.

Defaults remain 100 new source admissions and 200 conservatively reserved
document units per rolling 24 hours, a six-hour child-wide provider cooldown,
30-second total OAuth/query wall bound, and six-hour maximum dated observation
age. OAuth shares that wall bound rather than adding another retry window.
These limits do not expand the 2000-token parent chat or 2000-token global
Child-Safety daily ceilings. No new public route or family history migration is
introduced. Sources retain their separate private schema 2.

## Credentials and receipts

`FamilyFirestoreToken` uses google-auth's public service-account signer, a fixed
datastore scope and an explicitly bounded OAuth request to Google's fixed token
endpoint. It never calls SDK refresh/authorized transports, follows redirects,
uses domain-wide delegation, trusts a credential-supplied token URL, or retries
transport requests. A lock coalesces simultaneous token requests. Tokens remain
in server memory; expiry is measured from dispatch, not receipt. Invalid
credentials/token receipts or rejected authorization close the source through
its durable ledger. Transient/lost calls keep their original conservative hold;
new request IDs, restart or a new day do not release it.

The existing Manakids membership adapter now reports login/profile `401/403` as
the controlled `child_source_auth_denied` code. The shared source service maps
that gate refusal to its durable authorization circuit before any Google call.
Invalid OAuth receipts also close that circuit immediately, rather than waiting
for another child to encounter the in-memory blocked token provider. Restart
does not reopen either refusal. Existing chat HTTP error status stays controlled;
there is no login/GET/source retry in the failed invocation.

Datastore OAuth scope alone is not a read-only grant. Read-only enforcement is
the fixed equality query adapter and deployed IAM policy. Credentials and OAuth
assertions are never given to agents, chat, browsers, history or audit payloads.
Service-account JSON is size-bounded and errors omit its contents. Production
packaging now includes pinned google-auth and its resolved signing dependencies.
The Python 3.12 resolver initially preserved all old pins; the subsequent security
audit required the separate certifi correction described below.

Primary references checked for this increment:
[Google service accounts](https://developers.google.com/identity/protocols/oauth2/service-account),
[public signer/credential API](https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.service_account.html),
[Firestore query billing](https://firebase.google.com/docs/firestore/pricing).

## Bounded real source evidence

The owner-authorized local diagnostic used designated test parent `4` and its
fresh connected-child membership. Its first configuration preflight refused a
missing local backend key before any HTTP request; that original admission and
failure remain in `output/family-source-live-20261024/`. The corrected isolated
diagnostic used a temporary in-memory backend key and no listening API. It did
not change any existing key or `.env` file.

`output/family-source-live-20261024-configured/result.json` records exactly:

- one successful Manakids login and two bounded successful exact-parent reads
  (discovery, then the source service's fresh ownership check);
- one successful Google OAuth exchange;
- one successful `documents:runQuery` limited to two battery documents;
- one completed source receipt, one private snapshot and one change event;
- two conservative document units reserved, not a Google billing receipt;
- zero additional HTTP calls on exact-request replay;
- zero model calls, contacts, push attempts, tariff grants or source mutations;
- disabled consumer admission and zero specialist dispatch rows.

The result is available, but its measurement time is unknown. It must not become
a current battery alert or be relabeled with collection/server-write time.
The result validates real credentials, membership, query compatibility, parsing,
SQL persistence and exact replay for one test family only. It does not validate
all families, the model tool loop, an independent quality review, real delivery,
a paid conversion or production capacity. Do not repeat this diagnostic to
reproduce its evidence; inspect its original SQL/receipt instead.

For costs, this targeted lane reserves at most 200 document units per rolling
day under its default ledger. If the deployed database price is `R` USD per
100,000 reads, that unit component is at most `200 * R / 100000` per full day,
`6000 * R / 100000` per 30 days, and `73000 * R / 100000` per 365 days, excluding
free allowance. Actual region/edition, index billing and bandwidth must be
confirmed before turning this into a total dollar forecast. This is neither
the eventual bulk collector's allowance nor an account-wide Firebase bill cap.

## Packaging and security

The minimal product lock adds google-auth/signing dependencies resolved in a
clean Python 3.12.15 container, keeping the OpenAI 2.53.0 pin and existing models.
A real pip-audit found the previous certifi 2026.7.22 bundle affected by
PYSEC-2026-4320; the product lock now uses 2026.10.19. The original failing audit
is retained. See the
[maintainer advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2).
Private `output/` is excluded from Docker build context. No production image,
service, source switch, refresh schedule, SSH setting or credential was changed.

## Acceptance

Focused runtime/source tests use real signing and actual application/SQL with
fictional MockTransport responses, never paid providers. They cover lazy startup,
fresh ownership before Google, shared cache, exact replay/restart, durable auth
circuit, unknown receipt holds, concurrent token coalescing, strict token expiry,
fixed endpoint/scope, invalid receipts, rejected redirects and separate storage.
The final full `make verify` process **62822** exited **0**:
**1092 backend tests passed**, one skipped, two opt-in live tests excluded;
**26 admin tests /11 suites** and **seven lab controller tests** passed.
Formatting, Ruff, ESLint and its 34 compatibility cases, strict mypy **303 files**,
TypeScript, Next production build and npm audit (zero vulnerabilities) passed.
The retained log is `output/family-source-runtime-verify-admission-final.log`.
The focused auth/source/adapter run **10681** separately passed **87 cases**.
Counts overlap and must not be added together.

The first full run failed collection because the isolated checkout had no
dummy `OPENAI_API_KEY`; subsequent runs explicitly used a fake key. Earlier
test/mypy mistakes and a secret-scan refusal of unmarked fictional token strings
were corrected; no real key was exposed. The earlier green full runs **46792**
and **9873** predate the final authentication-gate cases, and remain qualified.
The final source-security scan passed **526 tracked/unignored files** and
`git diff --check` passed before this evidence note.

The product-lock pip-audit passed with **no known vulnerabilities** after the
certifi fix (`output/family-source-runtime-dependency-audit-final.log`). This
checks the pinned product packages, not all development/private packages or OS
libraries. The original finding is preserved in the earlier audit log.

The final local Python 3.12 image is
`mana-ai-family:source-runtime-auth-20261024-local`,
`sha256:09c041a0599183b923ac3f14391da96bbd273b6fe6a45003032b5d53aebdfd09`.
Its actual networkless smoke process **91420** exited **0**, using
`scripts/mana_family_source_smoke.py` mounted read-only without application
source, credentials, environment or customer data. The real packaged signer,
typed query adapter and SQL runtime passed cache/reconstruction/exact replay
and retained unknown-read refusal. One simulated OAuth exchange and two
simulated queries were recorded, with zero real network/model/contact calls.
The log is `output/family-source-runtime-image-auth-smoke.log`. The initial
Docker command refused an unsupported `--progress` flag before building; the
supported local legacy builder completed. No daemon/SSH configuration changed.

The packaged smoke is current-image synthetic acceptance, not an old-image
rollback, real-family model quality, collector throughput or production release.
No browser was needed for this backend-only increment; existing lab/UI tests
passed without changing their fictional-source contract. The whole goal remains
active with native source tools, collectors, remaining specialists and broader
source/model/channel/administrative acceptance outstanding.
