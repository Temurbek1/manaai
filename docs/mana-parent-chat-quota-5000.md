# Parent-Touch daily allowance — 29 October 2026

The owner explicitly increased Parent-Touch to **5000 raw input plus output tokens
per parent per day**. This changes the existing chat allowance, not the model,
reply ceiling, number of chats, ownership checks or source permissions.
Child-Safety retains its independent **2000-token server-wide daily budget**.

`MANA_PARENT_CHAT_DAILY_TOKENS=5000` is the application default and example
configuration. The fictional web lab uses the same parent allowance. An explicit
deployment environment value overrides the default.

Changing the configured allowance preserves all used tokens, attempts, messages
and unknown-receipt holds. It does not renew a day or replay an old request. Exact
replay retains its originally saved response, including its historical quota
snapshot; use the history GET for the current quota. A lost submitted receipt
continues to block generation even after the allowance increases or midnight
passes. There is no database migration or reset.

Earlier diagnostic receipts and their 2000-token failures remain historical
evidence. They are not rerun or retroactively described as successful 5000-token
tests. Historical checkpoint sections retain their original limits; current
integration limits are in section 8 of
[the English integration guide](mana-single-chat-integration.en.md).

The production change uses the already released application 4018971/family 41 image.
It does not release the local owner-first routing or semantic reminder changes.
Only the isolated parent-chat container needs recreation for its new environment.
Main/audio, OPERATION services, UI, SSH, keys, Firebase/GA4, source ceilings, bulk
collection, push dispatch and trial-grant flags retain their existing settings.

The scoped release helper takes a private consistent SQL backup, validates that
resolved Compose configuration differs in exactly this one environment value,
and compares every original database table/cell and other container identities
after activation. Internal and public authenticated history must report 5000.
Compatible closure uses the same family 41 image and retains all history and holds;
never restore an old database over newer messages.

## Verified result

The scoped production configuration update completed successfully. Internal and
public HTTPS authenticated history return `quota.daily_limit=5000`. The parent
sidecar is healthy with zero restarts after its planned recreation. Its released
application image and family 41 schema are unchanged; every cell in all 86 tables
is preserved. The other five containers retain their original identities,
configurations and start times. No diagnostic message, model request, source read,
push or trial grant was submitted for this change.

Protected server evidence and the private consistent backup are in
`/opt/manaai-releases/parent-quota-5000-20261029/`. The resolved existing Compose
override retains exactly one changed value. The separate
`close_same_image_5000.py close` helper preserves the old same-image closure and
updates only its expected quota guard; it was not executed on production. The
original release helper remains unchanged and expects the historical 2000 value.

Final `make verify` passes 2576 backend, 26 admin and 23 lab cases, mypy 536 files,
format/lint/types/build and the configured high-severity dependency gate. One
backend skip, two opt-in live exclusions and five existing low-severity
development findings remain. The initial run exposed two test fixtures that still
seeded the old exhausted allowance; those thresholds were corrected without
weakening refusal assertions. A clean staged quota-only export, excluding the
unfinished routing work, separately passes 45 relevant cases. Regression checks
prove exact replay retains its original result, spent usage is not reset, new
requests see the increased remainder, and a 612-token unknown hold still blocks
generation across restart and midnight. Logs are retained under
`output/parent-quota-5000-*.log` and the protected local release directory.
