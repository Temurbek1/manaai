# Conversion account candidate — hermetic checkpoint

The full goal is still unfinished. This increment verifies the existing v10
application in a local container; it activates no production provider, source
refresh, contact, grant, push or deployment. Application source remains `8532a9f`.

## Actual packaged application

Local image `mana-ai-family:conversion-account-8532a9f-local`:

```text
sha256:09abd632f76bdbd6a0d0411f37c3b346a466f952ba413db57418afcd2953892c
```

All **188** packaged application Python files match the checkout. The sorted
relative-path/content-hash manifest has SHA-256
`38708fc8026ade03d1095d7d65ca6330528959061eaf2d2959f95969903604f5`.
The image runs as `app`, not root, and `/app/.env` is absent. Only application
code and locked production requirements are copied by the existing Dockerfile.
No application code changed during the harness increment.

The actual image runs had networking disabled, a read-only root filesystem,
all capabilities dropped, `no-new-privileges`, and a private `/tmp` tmpfs. Only
the diagnostic scripts were mounted read-only; there was no application-source,
credential, customer-data, Docker-socket or production-volume mount.

## Actual new and previous profiles

`scripts/mana_conversion_smoke.py --verify-accounts` adds an opt-in synthetic
v10 diagnostic while preserving the prior v9 mode by default. Both ran against
the actual packaged app, runtime/lifespan/worker, pinned OpenAI SDK and actual
Manakids adapters with `MockTransport` responses, not the real services.

- **V10 container session 46588**, terminal exit **0**: three source-verified
  first offers, four mocked account GETs, ten mocked JWT logins in total, two
  mocked free grants, three mocked pushes, four SDK-mocked generations/counts
  and four synthetic child-profile reads. Source `created_at` is a year old but
  the backend-confirmed free period remains seven days; it is not remapped.
- The third source-verified parent has a current non-paid record and lifetime
  trial already used, so the approved paid offer is selected. The fixture does
  not invent expired-record coverage for the documented current Parent List.
- A fourth parent's account GET loses its response; a fifth receives login
  `403` without any subsequent account GET. Their unknown/refused receipts and
  read constraints survive closed mode and active-runtime reconstruction.
  Another event nonce/revision returns respectively `409`/`429`, not a relogin,
  source scan, reset or automatic retry. Exact event replay reuses saved SQL.
- **Prior v9 mode container session 7452**, terminal exit **0**: the existing
  conversion lifecycle still passes with zero account-source GETs, five mocked
  logins, two mocked grants, three mocked pushes and four SDK-mocked generations.
  Its separately supplied confirmed-expiry scenario remains synthetic, not a
  newly proven expired Parent List source.
- In both profiles, exact completed message replay/GET/closed history does not
  call the model, profiles or provider again. The actual v1 -> v6 seed preserves
  its completed legacy chat and **2000-token unknown hold** through migration
  and same-code closed mode. V10 source-ledger row fingerprints also survive
  closure and reactivation unchanged. No populated schema is downgraded.

This is same-candidate closed-v10 acceptance, **not** an old-image rollback.
The previous v9/production image is not a v10 reader and must not replace it over
new history. Mock queueing is not real device delivery, a free grant is not paid
conversion, and mocked generation is not real-model sales quality.

The harness retains its explicit synthetic **20,000-token Child-Safety ceiling**
for two reviewed conversations. This does not change or prove throughput under
production's shared **2000-token/day** Child-Safety budget. Parent-Touch remains
2000 tokens per parent/day; neither quota nor source permissions are renewed.

## Full verification

**`make verify` session 63416** terminated with exit **0**:

- **884 backend tests passed**, one skipped, two opt-in live excluded, 40.51s.
- **26 UI tests /11 suites**, production build passed.
- Ruff/format, ESLint and its 34 compatibility checks, mypy **280 files**,
  TypeScript and npm audit (**zero vulnerabilities**) passed.
- The two hermetic harness tests are included in the totals, not additional tests.
  The initial harness-only mypy variable-name collision was corrected before this
  full gate. No application or policy change was needed.
- Final secret scan: **457 tracked/unignored files**; `git diff --check` passed.

No real OpenAI, Manakids, Firebase/GA4, Meta, grant, push, SSH/key or production
request occurred in this increment. The last separately bounded real Parent List
check still lacked all three newly announced fields; it was not repeated here.

## Remaining full-objective acceptance

Continue finite RU/Uzbek real-model commercial-dialogue quality checks under the
unchanged actual parent allowance, preserving every unknown/negative receipt and
never replaying a lost paid call. The fake container pass is not that evidence.
The external source still needs deployed fields, confirmed date/lifetime/paid
precedence semantics and a population event producer with gap accounting,
verified parent activity/permissions and a real approved checkout/offer catalog.
Source refresh and customer-contact deployment require their own scoped release;
this checkpoint grants neither. Keep the original goal unfinished.
