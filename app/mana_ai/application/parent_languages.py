"""Conservative RU/UZ/EN presentation hints, never identity or source authority.

This is not a general language detector. Unknown prose stays model-directed; only
neutral acknowledgments/numbers may inherit the last frozen parent reference.
"""

import re

from app.mana_ai.domain.chat import ResponseLanguage


def parent_language(text: str) -> ResponseLanguage | None:
    words = re.findall(r"[^\W\d_]+", text.casefold())
    prefixes: dict[ResponseLanguage, tuple[str, ...]] = {
        "ru": (
            "привет",
            "помог",
            "ребен",
            "ребён",
            "спасиб",
            "пожалуй",
            "как",
            "почему",
            "обычн",
            "ложит",
            "засып",
            "спат",
            "школ",
            "вста",
            "понял",
            "понят",
            "нужн",
        ),
        "uz-Latn": (
            "salom",
            "farzand",
            "bolam",
            "maktab",
            "uyqu",
            "uxla",
            "yotadi",
            "uyg",
            "nech",
            "qachon",
            "qanday",
            "rahmat",
            "iltimos",
            "yordam",
            "odatda",
            "soat",
            "tushunar",
            "uchun",
            "turadi",
            "nima",
            "yubor",
            "xavfsiz",
        ),
        "uz-Cyrl": ("салом", "фарзанд", "болам", "мактаб", "уйқу", "неча", "раҳмат", "ёрдам"),
        "en": (
            "hello",
            "please",
            "child",
            "sleep",
            "school",
            "what",
            "when",
            "how",
            "thanks",
            "help",
            "wake",
            "understood",
            "usually",
            "your",
            "does",
        ),
    }
    scores = {
        language: sum(any(w.startswith(p) for p in starts) for w in words)
        for language, starts in prefixes.items()
    }
    best = max(scores, key=lambda language: scores[language])
    if scores[best] == 0 or list(scores.values()).count(scores[best]) != 1:
        return None
    if scores[best] == 1 and not set(words) & {
        "salom",
        "rahmat",
        "tushunarli",
        "привет",
        "спасибо",
        "понятно",
        "hello",
        "thanks",
    }:
        return None
    return best


def neutral_parent_reply(text: str) -> bool:
    return not any(c.isalpha() for c in text) or text.strip().casefold().rstrip(".!?") in {
        "ok",
        "okay",
        "ha",
        "yes",
        "no",
        "да",
        "нет",
    }


def language_name(language: ResponseLanguage) -> str:
    return {
        "ru": "Russian",
        "uz-Latn": "Uzbek (Latin script)",
        "uz-Cyrl": "Uzbek (Cyrillic script)",
        "en": "English",
    }[language]
