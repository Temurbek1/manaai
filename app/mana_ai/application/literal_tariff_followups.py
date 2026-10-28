"""Full-match numeric tariff commands; all other wording remains model-directed."""

import re
from decimal import Decimal

from app.mana_ai.domain.chat import ResponseLanguage
from app.mana_ai.domain.client_upsell import UpsellChoice
from app.mana_ai.domain.literal_tariff_followups import LiteralTariffChange

_DAYS: tuple[tuple[ResponseLanguage, str], ...] = (
    ("ru", r"(?:а\s+)?на\s*([1-9][0-9]{0,2})\s*д(?:ень|ня|ней)"),
    ("uz-Latn", r"yana\s*([1-9][0-9]{0,2})\s*kun"),
    ("uz-Cyrl", r"яна\s*([1-9][0-9]{0,2})\s*кун"),
    ("en", r"(?:what\s+about|for)\s*([1-9][0-9]{0,2})\s*days?"),
)
_AMOUNT = r"([0-9]{1,12}(?:[.,][0-9]{1,2})?)"
_BUDGETS: tuple[tuple[ResponseLanguage, str], ...] = (
    ("ru", r"(?:бюджет\s+)?до\s*" + _AMOUNT + r"\s*(UZS|USD)?"),
    ("uz-Latn", r"byudjet\s+" + _AMOUNT + r"\s*(UZS|USD)?\s*gacha"),
    ("uz-Cyrl", r"бюджет\s+" + _AMOUNT + r"\s*(UZS|USD)?\s*гача"),
    ("en", r"(?:budget\s+)?up\s+to\s*" + _AMOUNT + r"\s*(UZS|USD)?"),
)
_CURRENCIES: tuple[tuple[ResponseLanguage | None, str], ...] = (
    (None, r"(UZS|USD)"),
    ("ru", r"(?:а\s+)?в\s*(UZS|USD)"),
    ("uz-Latn", r"(UZS|USD)\s*da"),
    ("uz-Cyrl", r"(UZS|USD)\s*да"),
    ("en", r"in\s+(UZS|USD)"),
)


def literal_tariff_change(message: str) -> LiteralTariffChange | None:
    text = message.strip()
    if text[-1:] in {"?", ".", "!"}:
        text = text[:-1].rstrip()
    for language, pattern in _DAYS:
        match = re.fullmatch(pattern, text, flags=re.IGNORECASE)
        if match and int(match[1]) <= 366:
            return LiteralTariffChange(
                kind="duration_days",
                exact_message=message,
                language=language,
                duration_days=int(match[1]),
            )
    for language, pattern in _BUDGETS:
        match = re.fullmatch(pattern, text, flags=re.IGNORECASE)
        if match:
            minor = int(Decimal(match[1].replace(",", ".")) * 100)
            if 1 <= minor <= 10**14:
                return LiteralTariffChange(
                    kind="maximum_total",
                    exact_message=message,
                    language=language,
                    maximum_price_minor=minor,
                    currency=match[2].upper() if match[2] else None,
                )
    for currency_language, pattern in _CURRENCIES:
        match = re.fullmatch(pattern, text, flags=re.IGNORECASE)
        if match:
            return LiteralTariffChange(
                kind="currency",
                exact_message=message,
                language=currency_language,
                currency=match[1].upper(),
            )
    return None


def apply_literal_tariff_change(prior: UpsellChoice, change: LiteralTariffChange) -> UpsellChoice:
    prior = UpsellChoice.model_validate(prior.model_dump())
    change = LiteralTariffChange.model_validate(change.model_dump())
    if (
        change.kind == "currency"
        and change.currency != prior.currency
        and prior.maximum_price_minor is not None
    ):
        raise ValueError("Changing a budget's currency needs an explicit replacement amount")
    values = prior.model_dump() | {"parent_quote": change.exact_message}
    if change.kind == "duration_days":
        values.update(minimum_days=change.duration_days, maximum_days=change.duration_days)
    elif change.kind == "maximum_total":
        values["maximum_price_minor"] = change.maximum_price_minor
        if change.currency is not None:
            values["currency"] = change.currency
    else:
        values["currency"] = change.currency
    return UpsellChoice.model_validate(values)
