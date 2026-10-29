# Commercial preferences in the single parent chat

Released as **ebcfa88** in the isolated parent-chat service. Production test parent
4 confirms completed zero-token refusal and exact replay with Conversion disabled.
Read [the scoped release record](mana-family-production-20261029.md).

Parent-Touch now handles an explicit offer refusal before model, source, currency
and specialist admission. It works even when Conversion/Retention services are
disabled, the parent has exhausted their 5000-token allowance, or a previous
submitted model receipt remains unknown. The refusal and its acknowledgement
commit together using the existing host-message and conversion preference tables.
There is no new mobile endpoint, schema version, model call or consent grant.

Send an ordinary `POST /api/v1/mana-ai/parent-touch/messages` with the existing
backend credential, canonical `parent_id`, new `request_id` and one exact command:

- RU: `Не присылай предложения`
- Uzbek Latin: `Taklif yubormang`
- Uzbek Cyrillic: `Таклиф юборманг`
- EN: `Stop offers`

The completed response acknowledges the choice in that language with zero raw
model usage. Existing exact negative synonyms remain supported. Quoted commands,
negated explanations, positive consent and arbitrary prose are not interpreted
as a preference grant. Legacy readers without the host-command contract retain
their previous behavior; use the recommended message/status/history API.

The choice cancels queued Conversion proposals and stops unsubmitted marketing
pushes. Tariff-expiry and known free-period invitations/pushes honor the same
preference. Saved messages remain visible. A submitting/unknown push is never
rewritten or retried. Safety notices, confirmed assistant reminders and ordinary
support check-ins have separate permissions and are not unsubscribed by this
commercial-only command. An unrelated pending question remains unanswered.

The parent can still explicitly ask for prices afterward. This is a requested
service, not unsolicited marketing, payment, grant or automatic resubscription.
No command here re-enables campaigns or creates verified contact permission.
History and unknown holds survive restart/midnight; exact replay observes the
original result and a conflicting UUID cannot apply the preference.

## Evidence and boundaries

Four pre-fix regressions against the clean 5000-token baseline fail at the old
quota gate; the new four-language control works without any model/source work.
The focused integration matrix passes 83 cases. The trial-card regression now
requires an immediately completed zero-usage reply while preserving cancellation
of only the unclaimed card and zero grants. No real tariff is issued by tests.

The clean quota/preference-only source, excluding unfinished owner-first routing,
passes `make verify`: 2434 backend, 26 admin and 23 lab cases, mypy 508 files,
format/lint/types/build and the configured high-severity audit gate. One backend
skip, two live exclusions and five existing low development findings remain.
The earlier mixed-worktree run passed 2589 cases and exposed the trial-card
test's obsolete pending-phase expectation; it is not relabelled a full pass.

One actual GPT-5.4/GPT-5.4-mini party completes an assistant-first dated expiry
notice, a bound currency question, 90-day quote, refusal, explicitly requested
180-day quote and useful child/backpack guidance. It uses 4069/5000 parent tokens
and 1223/2000 global Safety tokens, with zero unknown holds. Sources/family are
fictional; only OpenAI was called, five generations and five counts. This is not
a real customer conversion, live catalogue or fleet-capacity measurement.

The original diagnostic's final fingerprint helper called the wrong source-cache
method and exited after saving the completed conversation. That failure is kept.
A separate SQL-only correction copies the stable files, reconstructs all five
parent requests, verifies 11 messages and every family/source table fingerprint,
and checks the same-schema closed reader with zero HTTP/profile/catalogue calls.
Original files and paid receipts are unchanged; the model party is not rerun.
The final answer offers a practical evening checklist and gradual independence,
without invented telemetry, danger, payments or an unbound follow-up question.

Local evidence: `output/commercial-preferences-*.log`,
`output/proactive-commercial-full-chat-20261029/`, and the separately named
`output/proactive-commercial-sql-recovery-20261029/`. Clean image/factory evidence
is under `/mnt/ssd2/mana-commercial-preferences-20261029/`. No source refresh,
push dispatch, grant campaign or OPERATION deployment follows from this feature.

The owned 390px browser completes assistant-first expiry contact, refusal and an
explicit catalogue enquiry, preserving all five messages and 150 simulated parent
tokens after reload. No page overflow/errors occur. Two initial observation
expressions used invalid browser-evaluation syntax; corrected GET observations
repeat no scenario POST. The browser and its owned loopback server are closed.
