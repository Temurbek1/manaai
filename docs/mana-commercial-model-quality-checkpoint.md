# Commercial dialogue — bounded real-model checkpoint

The original conversion goal is unfinished. One local, explicit real-model party
used only fictional families and local account/profile fixtures. No production
service, source refresh, Manakids/Firebase/GA4 read, grant, push or payment ran.

## Original party, not post-fix acceptance

`data/diagnostics/commercial-quality-20261021-party1/` is ignored private output.
The original four case JSON/SQLite files, `summary.json` and append-only
`usage.jsonl` remain unchanged. Their ten-file manifest SHA-256 is
`7189c0b62b80592dac80d7eaffcce58da0745b8f74968d31f2f040c79a0cc092`.
The separate `manual-review.md` records interpretation, never rewrites receipts.

Application source was **8532a9f**. Actual models returned snapshots
**gpt-5.4-2026-03-05** (Parent-Touch) and **gpt-5.4-mini-2026-03-17**
(Child-Safety), with the unchanged source-default `none` reasoning profile.
Session **80061** terminated normally: four completed review-first conversations,
eight generations, eight input counts, no unknown generation receipt and no retry.
All prior conversations retain their original history/idempotency.

The diagnostic requires both `MANA_COMMERCIAL_LIVE_EVAL=1` and `--confirm-paid`,
an explicit ignored key-file path, and a new output directory. It stops before
more than eight generations, admits only an exactly counted input plus output
within 2000 tokens, and reserves $0.05 before each call: **$0.40 maximum** for
this finite cohort. An unknown generation halts the party and keeps its reserve;
definitive request rejection halts without an inference receipt. No fallback,
lost-call retry, real source, grant or push adapter is configured. Unit tests use
only fakes, never this paid opt-in.

Raw verified usage totals **8523 input + 767 output tokens**. The standard uncached
estimate is **$0.02035250**, unknown reserve **$0.00**, using the fetched
[official pricing](https://developers.openai.com/api/docs/pricing): GPT-5.4
$2.50/$15.00 per million input/output tokens, mini $0.75/$4.50. This is not an
invoice reconciliation; cache discounts are deliberately not assumed. Reasoning
tokens are not added to output a second time. The requested models and standard
service tier were preserved; no model migration or live configuration change ran.

## Manual review, not just completed statuses

| Case | Parent-Touch raw tokens | Child-Safety raw tokens | Narrow manual verdict |
| --- | ---: | ---: | --- |
| Paid RU | 1129 | 1126 | Correct $8.50/30 days and explicit no-renewal terms |
| Paid Uzbek Latin | 1144 | 1148 | Same terms correctly explained in Uzbek Latin |
| Free days RU | 1135 | 1177 | Activation honestly unconfirmed; billing-scope wording qualified |
| Free days Uzbek Latin | 1222 | 1209 | Activation honestly unconfirmed; future billing uncertainty qualified |

No answer falsely claimed an actual activation, payment or transaction. Paid
answers match the exact fictional approved price/renewal terms. Free answers
distinguish the grant from a paid subscription, but expose ambiguity in the host
template's blanket no-automatic-charge wording. The Uzbek answer's caution about
future subscription terms is not proof of a fabricated charge or activation.
This party is **not an all-four semantic pass**, a measured conversion result or
evidence that real checkout/discounts exist.

Each case has its own isolated 2000-token Parent-Touch allowance and 2000-token
Child-Safety server/day ledger. This does not demonstrate four conversations
within one shared production safety budget. At these measured input sizes one
reply already uses about 1100–1200 raw tokens. Sustained multi-turn/population
capacity under the unchanged production limits remains unproven; do not silently
raise budgets or discard evidence to make a diagnostic pass.

## Scoped correction after review

The supplied `agent-tariff-api.md` confirms that granting 1–30 free Maxsus days
creates no payment/transaction. It does not document future renewal terms for a
separate subscription. The four-language offer template now scopes its statement
to the grant operation instead of promising blanket no automatic charges.
Parent-Touch's existing commercial instructions clarify the same distinction:
do not invent future renewal terms and do not suggest this free grant itself
creates a charge. This follows the explicit factual/context boundaries in the
fetched [GPT-5.4 prompting guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.4).

No stored message, captured offer, receipt, input objective or legacy JSON was
rewritten. No schema/migration, role model, quota, source/action authority or SDK
transport changed. Only new rendering and the shared explanation guidance changed.
The source boundary is narrower, not an invented no-renewal flag.

**The correction has not received a new paid-model acceptance party.** Do not
reuse the original $0.02035250 party as post-fix evidence or replay its requests.
The previous `09abd632f76b…` image likewise contains the pre-fix wording.

## Engineering verification

The harness's initial fixture/type preflight found an old phase spelling and
untyped helper values; those were corrected offline before any paid call.
The first full local gate (16828) passed **891 backend /26 UI tests** before the
template correction. The subsequent full **`make verify` session 23636** reached
terminal exit **0** with the correction:

- **892 backend tests passed**, one skipped, two opt-in live excluded, 45.24s.
- **26 UI tests /11 suites**, production build passed.
- Ruff/format, ESLint and 34 compatibility checks, mypy **282 files**, TypeScript
  and npm audit (**zero vulnerabilities**) passed.
- Eight new diagnostic/template tests are included, not additional to the totals.
- Final secret scan: **460 tracked/unignored files**; diff check passed. Private
  synthetic SQLite/JSON receipts and the environment file are not staged.

The full objective still requires real source fields/semantics, an authoritative
all-parent subscription/activity/consent producer with coverage accounting, actual
approved billing offers and separately scoped production/channel acceptance.
Neither this small synthetic party nor the offline correction establishes those.
