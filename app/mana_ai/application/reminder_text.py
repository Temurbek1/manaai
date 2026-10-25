"""Exact approved reminder facts, not model-generated execution claims."""

import re
from zoneinfo import ZoneInfo

from app.mana_ai.application.parent_languages import parent_language
from app.mana_ai.domain.chat import ResponseLanguage
from app.mana_ai.domain.parent_reminders import ReminderCandidate


def reminder_language(text: str, fallback: ResponseLanguage = "en") -> ResponseLanguage:
    detected = parent_language(text)
    if detected:
        return detected
    words = re.findall(r"[^\W\d_]+", text.casefold())
    prefixes: dict[ResponseLanguage, tuple[str, ...]] = {
        "ru": ("напомн", "напомин", "отмени", "тетрад"),
        "uz-Latn": ("eslat", "daftar", "bekor"),
        "uz-Cyrl": ("эслат", "дафтар", "бекор"),
        "en": ("remind", "notebook", "cancel"),
    }
    matches = [
        language
        for language, values in prefixes.items()
        if any(w.startswith(p) for w in words for p in values)
    ]
    return matches[0] if len(matches) == 1 else fallback


def reminder_preview(candidate: ReminderCandidate, language: ResponseLanguage) -> str:
    if candidate.due_at is None:
        if language == "ru":
            return f"Когда напомнить: «{candidate.content}»? Укажите дату и время."
        if language == "uz-Latn":
            return f"«{candidate.content}» haqida qachon eslatay? Sana va vaqtni yozing."
        if language == "uz-Cyrl":
            return f"«{candidate.content}» ҳақида қачон эслатай? Сана ва вақтни ёзинг."
        return f"When should I remind you: “{candidate.content}”? Include the date and time."
    stamp = candidate.due_at.astimezone(ZoneInfo(candidate.timezone)).strftime("%d.%m.%Y %H:%M")
    if language == "ru":
        return f"Напомнить {stamp} ({candidate.timezone}): «{candidate.content}»?"
    if language == "uz-Latn":
        return f"{stamp} ({candidate.timezone}) da «{candidate.content}» haqida eslataymi?"
    if language == "uz-Cyrl":
        return f"{stamp} ({candidate.timezone}) да «{candidate.content}» ҳақида эслатайми?"
    return f"Remind you on {stamp} ({candidate.timezone}): “{candidate.content}”?"


def reminder_ack(kind: str, language: ResponseLanguage) -> str:
    text = {
        "scheduled": (
            "Напоминание запланировано.",
            "Eslatma rejalashtirildi.",
            "Эслатма режалаштирилди.",
            "Reminder scheduled.",
        ),
        "cancelled": (
            "Напоминание отменено.",
            "Eslatma bekor qilindi.",
            "Эслатма бекор қилинди.",
            "Reminder cancelled.",
        ),
        "none": (
            "Нет активных напоминаний.",
            "Faol eslatmalar yo‘q.",
            "Фаол эслатмалар йўқ.",
            "There are no active reminders.",
        ),
        "expired": (
            "Срок подтверждения или выбранное время истекли.",
            "Tasdiqlash muddati yoki tanlangan vaqt o‘tib ketdi.",
            "Тасдиқлаш муддати ёки танланган вақт ўтиб кетди.",
            "The confirmation or selected time has expired.",
        ),
        "queued": (
            "Напоминание подготовлено; сначала завершим текущий вопрос.",
            "Eslatma tayyor; avval joriy savolni yakunlaymiz.",
            "Эслатма тайёр; аввал жорий саволни якунлаймиз.",
            "Reminder prepared; we will finish the current question first.",
        ),
    }
    return text[kind][{"ru": 0, "uz-Latn": 1, "uz-Cyrl": 2, "en": 3}[language]]


def reminder_message(candidate: ReminderCandidate, language: ResponseLanguage) -> str:
    prefix = {"ru": "Напоминание", "uz-Latn": "Eslatma", "uz-Cyrl": "Эслатма", "en": "Reminder"}[
        language
    ]
    return f"{prefix}: «{candidate.content}»."
