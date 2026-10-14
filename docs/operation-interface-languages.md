# Russian and Uzbek operational workspace

Local implementation checkpoint; **not a production release**.

The website supports Russian (`ru`) and Uzbek Latin (`uz`, **O‘zbekcha**).
One compact selector is available on login and in the agent sidebar. Selection persists
in browser local storage, updates the document language, survives reload, and does not
remount the chat, replace drafts, authenticate again or activate an external source.
When storage is blocked, selection remains usable for the current page.

Owned interface text is translated through an explicit React context/catalog: login,
four-agent navigation, chat, Goals controls, evidence timing labels, approvals and the
professional workspace. Dates use the selected locale. There is no DOM-wide text
replacement, automatic machine translation, provider request or listener on Firebase.
User text, saved source/report contents, historical model answers, plan descriptions,
SQL audit records and their fingerprints remain exact original artifacts, not rewritten
translations. Unknown upstream text is displayed as received.

## Conversation and Goals contracts

`MessageCreate.response_language` is an optional closed `ru | uz` presentation field.
The chat runtime freezes it on admission, supplies it to discussion/native/streamed
generation, and requires an identical value on idempotent replay. Changing locale after
a lost response cannot cause another call under the same request ID. It is stored only
in the existing additive `workspace_metadata`, never legacy-readable chat JSON or
`context_metadata`. Existing messages default to the prior language behavior.

For Uzbek conversation-to-Goal handoff, the objective remains **the exact original
message**. The new Goal's original no-write/no-contact constraint also explicitly requests
Uzbek Latin output. Explicit Uzbek Goal creation sends equivalent translated default
criteria and the same language condition; its scope, steps and budget are unchanged.
This condition persists through SQL continuation/review, not a transient browser header.
Changing interface language does not rewrite or change the instructions of an existing Goal.
No new Goal checkpoint version, inherited source approval or budget grant is introduced.

Chat/Goal availability advertises `response_languages`. The compatible UI refuses a new
Uzbek submission to an older server that has not advertised support, retaining the draft;
it must not silently submit a Russian task. Russian remains compatible with prior payloads.
Release the language-capable operational API/Goals worker and UI together. The verified
closed `2ea7b9a` fallback ignores private chat metadata and keeps native execution disabled;
this checkpoint is not a new old-image execution/rollback acceptance.

## Recipient language is separate

The separate, unexposed Retention contact foundation has explicit RU/UZ versioned sandbox
templates. Recipient preference must be proven by the typed target and match the exact
reviewed language. Interface language, city, push permission or an aggregate are not
recipient language, customer-contact consent or send authority. See
[the contact foundation](operation-retention-contact-foundation.md).

## Acceptance

Automated checks use fake models and sources. They verify selection/storage fallback,
owned-string catalog and interpolation completeness, unchanged saved text/drafts,
closed language validation, exact chat replay, private storage and Goal handoff. The local
real-browser audit checks RU/UZ login and agent navigation, reload, 320px layout and
WCAG A/AA checks before returning to existing Russian flows.

These are transport/UI checks, **not independent Uzbek linguistic quality acceptance**
of a real model. No paid model call, Firebase/GA4 read, production update, new schedule,
main/audio change or SSH/key change was performed for this language increment.
