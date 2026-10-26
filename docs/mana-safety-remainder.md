# Reuse the verified Safety allowance — local, 2026-10-26

Native parent-message reviews already have a bounded remainder-admission path.
Ordinary child-data and background source-review jobs required the entire
configured job allowance before starting. With 2000 global tokens and a 2000-token
job ceiling, a verified 150-token analysis therefore left 1850 tokens unusable by
the next observation job. This is an admission problem, not evidence of 1850
tokens being billed or lost.

New default-disabled `MANA_CHILD_SAFETY_REMAINDER_ENABLED` extends the existing
remaining-budget path to **new captured observation jobs**. It requires the full
current manager/source-review profile. Production is unchanged; no new source
refresh, model, public endpoint, payment, tariff or contact authority is added.

## Contract and accounting

Private family **v27** adds one indexed `safety_remainder_admissions` table. A
new child-data or coalesced source-review job captures its exact parent/job and
original job ceiling in the same insert transaction. Existing typed
`ChildSafetyLimits` still own queue, daily-token and daily-attempt limits.
There is one capture per existing admitted job, not an extra lifetime counter,
full-table capture scan or new per-event polling task.

Old jobs, disabled admissions, content deduplication and exact/new-nonce replay
never recapture. Parent-message protocols retain their original native/legacy
rules. Disabling this flag stops new remainder claims; the existing full-job path
and already submitted work retain their original lifecycle.

SQL atomically reserves at most the minimum of the global remainder, parent's
remainder, current job ceiling and captured original ceiling. Eligibility and
attempt limits are applied before the bounded candidate page. The existing
64-token admission floor, same-parent pending exclusion, ownership, observation
dates and actual model token preflight still apply. A smaller reserve never trims
the objective, source facts or prompt, adds retries or changes a model. If the
complete input and required output do not fit, stop before inference.

Verified raw receipts settle actual usage. Submitted/unknown holds keep consuming
the shared allowance across midnight and restart. Another family may use only
what remains after those holds; the affected parent remains blocked. Parent-Touch
stays 2000 raw tokens per parent/day, independently of **2000 global Safety/day**.
This improves use of the allowance; real-model token requirements still determine
how many analyses can fit. It does not establish fleet capacity or model quality.

## Migration and verification scope

The new capture hook is a no-op in earlier store profiles. The shared native
selector keeps its previous eligibility, adding only the private captured branch
in v27. There is no new stored prompt/context/tool protocol or public schema.
New v27 databases must use the current closed v27 reader for observation/closure;
older v26 refusal is not functional execution rollback. Never downgrade populated
history or restore an old database over new events.

Focused fake/SQLite checks cover two sequential observations, coalesced review ->
Parent-Touch, atomic concurrent claims, unknown/cross-day reserves, the 64-token
floor, disabled/old migration no-backfill, exact replay, atomic capture rollback,
closed preservation and actual idle runtime wiring. The initial ledger fixture
omitted required child authorization and correctly failed. A stronger delivery
assertion then found the earlier queued battery notice; the corrected fixture
delivers it first and still requires the subsequent exact source-review notice.
No owning policy was relaxed.

The first implementation passed its full gate with an unnecessary lifetime
capture counter. Before freeze that counter was removed: existing job/attempt/
queue limits already bound admission, and one metadata row follows its job.
Do not treat that pre-freeze gate or its temporary SQLite fixtures as the final
one-table v27 artifact. Final gates/browser/image evidence follow below.

Run `make chat-lab-remainder CHAT_LAB_PORT=8102` for the declared fictional
single-family profile. First collect battery context, then submit the separate
test threat: both can be reviewed under the unchanged shared allowance. Parent-
Touch alone writes the results into the same chat. The lab has no real Firebase,
GA4, push, tariff grant or payment adapter. Other lab profiles remain unchanged.

Final **`make verify` exited 0** for the one-table ledger: **1568 backend tests**,
**26 admin tests /11 suites**, **15 lab tests**, mypy **439 files**, formatting,
lint/typecheck, production UI build and zero npm vulnerabilities. One skip and
two excluded live tests are not passes. Sequential schema synchronization passed
without changing the public mobile contract. The earlier pre-freeze 1569-test
gate included the removed lifetime-counter case and is not this final artifact.

Chromium -> API -> SQLite -> display passed two distinct events: coalesced battery
context, then a direct synthetic threat. Both Safety jobs completed and produced
one assistant message each in the same chat, **300 simulated Safety and 300 parent
tokens**, zero holds. Reload and actual server restart preserved every cell in
**65 family and 15 source tables**, including two captures/two completed jobs.
The 390px screenshot was inspected without overflow/script errors. This uses
fictional data/models; no actual Firebase, GA4, OpenAI, push or grant request.
Evidence: `output/safety-remainder-browser-20261026/` and final verify/schema logs.
Packaged/migration checks are recorded separately when completed.

The full original goal remains open: supported referral/commercial mechanisms,
broader source/model/channel/capacity acceptance and administrative owning-domain
workflows are still required. Technical remains last.
