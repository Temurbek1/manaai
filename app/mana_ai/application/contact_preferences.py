"""Exact parent refusals, never positive consent or model-inferred permission."""

from app.mana_ai.domain.chat import ResponseLanguage

_STOP_OFFERS: dict[str, ResponseLanguage] = {
    "не присылай предложения": "ru",
    "не присылайте предложения": "ru",
    "не хочу рекламу": "ru",
    "не присылай рекламу": "ru",
    "отпиши от предложений": "ru",
    "отписаться от предложений": "ru",
    "stop offers": "en",
    "no more offers": "en",
    "unsubscribe": "en",
    "stop promotions": "en",
    "taklif yubormang": "uz-Latn",
    "takliflarni yubormang": "uz-Latn",
    "reklama yubormang": "uz-Latn",
    "таклиф юборманг": "uz-Cyrl",
    "реклама юборманг": "uz-Cyrl",
}


def commercial_refusal_language(text: str) -> ResponseLanguage | None:
    normalized = text.strip().strip(".!? ").casefold().replace("’", "'")
    return _STOP_OFFERS.get(normalized)


def commercial_refusal_reply(language: ResponseLanguage) -> str:
    return {
        "ru": "Больше не буду присылать предложения тарифов и акций. "
        "По вашему запросу по-прежнему помогу с тарифами.",
        "uz-Latn": "Endi tarif va aksiya takliflarini yubormayman. "
        "O‘zingiz so‘rasangiz, tariflar bo‘yicha yordam beraman.",
        "uz-Cyrl": "Энди тариф ва акция таклифларини юбормайман. "
        "Ўзингиз сўрасангиз, тарифлар бўйича ёрдам бераман.",
        "en": "I will stop sending tariff and promotional offers. "
        "I can still help with tariffs when you ask.",
    }[language]
