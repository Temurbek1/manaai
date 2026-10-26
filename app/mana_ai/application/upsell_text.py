"""Quotes display exact catalog prices; no invented benefit, discount or payment link."""

import re
from decimal import Decimal

from app.mana_ai.application.parent_languages import parent_language
from app.mana_ai.domain.chat import ResponseLanguage
from app.mana_ai.domain.client_upsell import UpsellQuote

TARIFF_HANDOFF_PLACEHOLDER = "Typed tariff enquiry awaiting host validation."

CURRENCY_ENQUIRY_INSTRUCTIONS = (
    "For this captured price/duration enquiry use only the latest parent request. "
    "parent_quote is its exact relevant substring. currency=null unless the parent explicitly "
    "specified UZS or USD; never infer it from language, location, history or the catalogue. "
    "The host asks one currency question and preserves these terms. Month=30, three months=90, "
    "six months=180, year=365 days; unspecified duration=1..366. objective=list for options, "
    "lowest_total for lowest total, lowest_daily only for explicit daily-price comparison. "
    "Both currencies have 100 minor units per unit. maximum_price_minor=null unless an explicit "
    "total budget; an unlabelled explicit number still preserves that budget times 100. "
    "With an enquiry keep body='', question=null, reminder=null, notice_communicated=false. "
    "No invented prices, benefits, discounts, renewal, checkout or eligibility."
)


def upsell_language(text: str, fallback: ResponseLanguage) -> ResponseLanguage:
    known = parent_language(text)
    if known:
        return known
    words = re.findall(r"[^\W\d_]+", text.casefold())
    if any(w.startswith(("oylik", "kunlik", "tanlang", "arzon", "obuna")) for w in words):
        return "uz-Latn"
    if any(w.startswith(("ойлик", "кунлик", "танланг", "арзон", "обуна")) for w in words):
        return "uz-Cyrl"
    if any(w.startswith(("тариф", "подписк", "месяц", "подбери")) for w in words):
        return "ru"
    if any(w.startswith(("tariff", "subscription", "cheapest", "monthly")) for w in words):
        return "en"
    return fallback


def upsell_ack(language: ResponseLanguage) -> str:
    return {
        "ru": "Проверю актуальные варианты в каталоге.",
        "uz-Latn": "Katalogdagi amaldagi variantlarni tekshiraman.",
        "uz-Cyrl": "Каталогдаги амалдаги вариантларни текшираман.",
        "en": "I will check the current catalog options.",
    }[language]


def upsell_result(quote: UpsellQuote | None, language: ResponseLanguage) -> str:
    if quote is None:
        return {
            "ru": "Сейчас не удалось подтвердить актуальные тарифы.",
            "uz-Latn": "Hozir amaldagi tariflarni tasdiqlab bo‘lmadi.",
            "uz-Cyrl": "Ҳозир амалдаги тарифларни тасдиқлаб бўлмади.",
            "en": "Current tariffs could not be verified.",
        }[language]
    if not quote.options:
        return {
            "ru": "В проверенной части каталога нет варианта с указанными сроком, "
            "валютой и бюджетом.",
            "uz-Latn": "Katalogning tekshirilgan qismida so‘ralgan muddat, valyuta va "
            "byudjetga mos variant yo‘q.",
            "uz-Cyrl": "Каталогнинг текширилган қисмида сўралган муддат, валюта ва "
            "бюджетга мос вариант йўқ.",
            "en": "The checked catalog page has no option matching the requested "
            "duration, currency and budget.",
        }[language]
    date = quote.catalog_collected_at.date().isoformat()
    intro = {
        "ru": f"По каталогу от {date}:",
        "uz-Latn": f"{date} sanasidagi katalog bo‘yicha:",
        "uz-Cyrl": f"{date} санасидаги каталог бўйича:",
        "en": f"Catalog checked on {date}:",
    }[language]
    lines = [intro]
    for item in quote.options:
        price = format(Decimal(item.price_minor) / 100, ",.2f").replace(",", " ")
        label = {"ru": "Тариф", "uz-Latn": "Tarif", "uz-Cyrl": "Тариф", "en": "Tariff"}[language]
        unit = {"ru": "дней", "uz-Latn": "kun", "uz-Cyrl": "кун", "en": "days"}[language]
        lines.append(
            f"{label} {item.tariff_id}: {item.duration_days} {unit} — {price} {item.currency}."
        )
    lines.append(
        {
            "ru": "Это цена за весь срок. Доступность для вашего аккаунта и условия "
            "оплаты проверяются в приложении.",
            "uz-Latn": "Bu butun muddat uchun narx. Akkauntingizga mavjudligi va to‘lov "
            "shartlari ilovada tekshiriladi.",
            "uz-Cyrl": "Бу бутун муддат учун нарх. Аккаунтингизга мавжудлиги ва тўлов "
            "шартлари иловада текширилади.",
            "en": "This is the total price for the term. Account eligibility and "
            "payment terms are checked in the app.",
        }[language]
    )
    return "\n".join(lines)
