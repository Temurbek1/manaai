# One non-paid grant — designated reset-account acceptance, 2026-10-23

**Subsequent owner restriction, clarified:** no grants to ordinary customers
during testing. Explicitly designated test accounts may receive a scoped test
grant after fresh preflight and a durable one-shot claim; known/unknown actions
never retry. This historical consumed grant does not authorize another grant to
parent `4`. Keep `MANA_CONVERSION_TRIAL_GRANTS_ENABLED=false` by default; automated
checks remain fake-only. No old grant is undone, and the test exception does not
authorize shared production configuration changes or service restarts.

The owner requested practical tests, designated parent `4`, and then confirmed
that its paid access had been reset. The completed test created exactly one
non-paid **one-day Maxsus** grant, purchase **74311**. This consumed the parent's
once-per-lifetime agent grant; do not repeat or undo it automatically.

This is an external API test using the existing account/grant adapters, not
deployment, a fabricated Parent-Touch activation message, verified paid conversion
or permission to contact real users. No payment/transaction API was invoked.

## Original preflight and explicit manual test

Session **10294**, terminal exit **0**, made one login and one exact-parent GET.
Both returned **200**. Parent `4` now had `is_paid=null`, `agent_trial_used=false`
and null `created_at`, `payment_date`, `valid_until`. Automatic policy correctly
did not treat null as false; the diagnostic stopped before any grant invocation.

Session **25293**, terminal exit **0**, continued only that known pre-dispatch
test refusal under the owner's explicit reset/test authority. It held an exclusive
local journal lock, verified the exact still-fresh empty-tariff observation and
absence of any previous grant claim, and fsynced a dispatch claim before HTTP.
No unknown action was rearmed. This manual exception is not an agent eligibility
rule or a synthetic parent acceptance; the application policy is unchanged.

Private ignored journal, created exclusively with mode 0600:
`data/diagnostics/trial-grant-test-4-20261023/attempt.jsonl`.
It retains minimized facts/receipt and the original stopped preflight. Never
erase it, start a new nonce to repeat the grant, or relabel the preflight as a
dispatched refusal. The earlier `168440` diagnostic also stopped before a write
because that separately designated account remained paid.

## Verified result

There were **six HTTP requests across both phases**: three fresh logins, two
exact-parent GETs and exactly one grant POST. No retries, redirects, scan, other
parent, direct Firestore/GA4 request, push or model call occurred.

```http
POST https://api.manakids.uz/api/v1/admin-panel-payment/agent-grant-tariff/
Content-Type: application/json

{"parent_id":4,"days":1}
```

The grant returned **201** with a valid receipt:

| Field | Value |
| --- | --- |
| `purchase_id` | `74311` |
| `parent_id` | `4` |
| `tariff` | `Maxsus` |
| `is_paid` | `false` |
| `agent_trial_used` | `true` |
| `created_at` | `2026-10-23T11:13:17.050912Z` |
| `valid_until` | `2026-10-24T11:13:17.029993Z` |

The subsequent GET returned **200**, the same parent and the same absolute
creation/expiry timestamps in +05:00, with non-paid access and consumed trial.
Local expiry is **2026-10-24 16:13:17 Asia/Samarkand**. Creation is within the
verified grant window, not the Account registration date previously observed
in December 2025. These observations bind one new grant to its current record;
they do not classify all historical tariff records or prove uninterrupted use.

## Local adapter increment

The observed new metadata is inside `data`. The gateway still accepts the
original documented receipt when all three metadata keys are absent. Once any
are present, it requires the complete strict group: `is_paid=false`,
`agent_trial_used=true`, and an explicitly timezone-aware ISO creation string
within 300 seconds of `valid_until - requested_days`. Contradictory, partial,
coerced, null or malformed metadata becomes an unknown outcome after the one
claimed write, never an automatic retry. Duplicate JSON keys are refused;
ambiguous login JSON stops before the business POST.

Metadata is validation-only. `TrialGrantResult` and stored SQL still contain
only purchase ID, parent ID, tariff and expiry. No public schema, private schema,
captured historical receipt, source grant, consent, quota, model or default flag
changes. Old absent-metadata receipts and exact replay remain readable; this
does not claim an old image implements the new validation policy.

The hermetic conversion harness now includes the new metadata in its fictional
success response. Live acceptance above used the prior adapter; regression and
candidate checks of the stricter code must be reported separately, never by
repeating this real grant or a paid model party.

The unchanged full goal still needs authoritative parent activity/permissions,
coverage/event production, real supported paid offer terms and separately scoped
contact/release acceptance. The owner does not yet know the real paid offer
catalog; no discount or payment terms were invented.

## Candidate and initial local gate

Local image `mana-ai-family:grant-metadata-20261023-local` has ID
`sha256:730e23d65196ab6987f91892b6fe93d02350c72a493aeb6028f39265c1ebcc9d`.
All **188** packaged application Python files match the worktree; the canonical
manifest SHA-256 is `704a34b1e2a1a69140de417d2246b9a700543496262c02c273c05fcaee63bfa3`.
The image runs non-root and has no `/app/.env`.

Actual container sessions **81741** (v10) and **56396** (v9) exited **0** under
network-none/read-only/dropped-capabilities/no-new-privileges with only diagnostic
scripts mounted read-only. The fictional new-metadata receipt passed the SDK/
HTTP/worker lifecycle. Legacy fingerprints, the 2000-token unknown hold and v10
source unknown/refusal receipts survived same-image closure/reconstruction.
No application source, customer data, keys or production volume were mounted.
These are current-image fake checks, not old-image rollback, real paid models,
live Parent-Touch contact, business improvement or production acceptance.

Initial **`make verify` session 55300** passed **915 backend tests** (one skipped,
two live excluded, 38.51s), **26 UI tests /11 suites**, Ruff, ESLint/34 compatibility
checks, mypy **282 files**, TypeScript and build. It then failed npm audit on the
installed Next 16.3.8 advisory group. It is not a passing full gate.

Upstream confirms fixed versions from 16.4.1 for
[image optimization](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw),
[Server Actions DoS](https://github.com/vercel/next.js/security/advisories/GHSA-p3m5-59mp-jv5r)
and [typed-array cache RCE](https://github.com/vercel/next.js/security/advisories/GHSA-673q-mjm6-r5xr).
The local dependency correction pins Next and its ESLint config/plugin to 16.4.2,
retains React 19.2.8 and all existing guarded overrides, and regenerates the lock.
No advisory is suppressed and no `--force` or `--legacy-peer-deps` is used.
Initial install attempts returned ERESOLVE/ETARGET; subsequent fresh metadata and
online lock resolution succeeded. Actual clean installation and the final full
gate are separate evidence, not inferred from lock generation or this paragraph.

## Final local gate

Clean lockfile installation **session 71560** exited **0** with
`npm ci --ignore-scripts --prefer-online`; no dependency scripts were executed.
Final **`make verify` session 3470** then exited **0**:

- **915 backend tests passed**, one skipped and two opt-in live excluded, 43.79s.
- **26 UI tests /11 suites**, Next **16.4.2** production build, formatting/Ruff,
  ESLint/34 guarded-chain cases, mypy **282 files** and TypeScript passed.
- npm audit: **zero vulnerabilities**. Secret scan: **463 tracked/unignored
  files**, passed; `git diff --check` passed.
- The 23 additional strict-metadata/duplicate-key regressions are part of the
  backend total, not extra tests. All use fake providers and fictional families.

There are no new public routes, response schema fields or private migrations.
The backend image/manifest above remain exact: the later dependency update affects
the separate local UI, not packaged Python application bytes. No corrected backend
or UI was deployed, no Git push was performed and no old receipt was rewritten.
Existing production services, source refresh, model budgets, SSH and keys remain
unchanged. The sole external mutation was the explicitly authorized test grant.
