"""Parent-Touch's approved commercial wording, not model-generated financial terms.

Eligibility requires no LLM. These assistant-only messages use no inference tokens
and create no fabricated provider receipt. Subsequent parent conversation remains AI.
"""

from datetime import UTC, datetime

from app.mana_ai.domain.chat import ResponseLanguage
from app.mana_ai.domain.conversion import ConversionOffer, PaidConversionOffer
from app.mana_ai.domain.conversion_grants import TrialGrantState


def render_parent_offer(offer: ConversionOffer, free_days: int, language: ResponseLanguage) -> str:
    if offer.kind == "free_premium_days":
        if language == "ru":
            return (
                f"Могу предложить бесплатный тариф Maxsus на {offer.grant_days} дн., "
                "один раз для вашего аккаунта. Без платежа и автосписания. "
                "Если хотите, напишите «активировать бесплатные дни»."
            )
        if language == "uz-Latn":
            return (
                f"Sizga Maxsus tarifini {offer.grant_days} kunga bepul taklif qila olaman, "
                "hisobingiz uchun faqat bir marta. To'lov va avtomatik yechishsiz. "
                "Xohlasangiz, «bepul kunlarni faollashtiring» deb yozing."
            )
        if language == "uz-Cyrl":
            return (
                f"Сизга Maxsus тарифини {offer.grant_days} кунга бепул таклиф қила оламан, "
                "ҳисобингиз учун фақат бир марта. Тўлов ва автоматик ечишсиз. "
                "Хоҳласангиз, «бепул кунларни фаоллаштиринг» деб ёзинг."
            )
        return (
            f"I can offer the Maxsus plan free for {offer.grant_days} days, once per account. "
            "No payment or automatic charge. Reply 'activate free days' if you want it."
        )
    price = f"{offer.price_minor // 100}.{offer.price_minor % 100:02d} {offer.currency}"
    discount = offer.discount_percent
    renewal = (
        f"{offer.renewal_price_minor // 100}.{offer.renewal_price_minor % 100:02d} {offer.currency}"
        if offer.renewal_price_minor
        else None
    )
    if language == "ru":
        lead = f"Вы пользуетесь бесплатным тарифом {free_days} дн."
        terms = f"Подписка на {offer.duration_days} дн. — {price}"
        if discount:
            terms += f" со скидкой {discount}%"
        repeat = (
            f" Автопродление — {renewal} за следующий период." if renewal else " Без автопродления."
        )
        return f"{lead} Можно перейти на платный: {terms}.{repeat} Условия — в разделе подписок."
    if language == "uz-Latn":
        lead = f"Siz {free_days} kundan beri bepul tarifdan foydalanasiz."
        terms = f"{offer.duration_days} kunlik obuna — {price}"
        if discount:
            terms += f", {discount}% chegirma bilan"
        repeat = (
            f" Keyingi davr uchun avtomatik uzaytirish — {renewal}."
            if renewal
            else " Avtomatik uzaytirilmaydi."
        )
        return (
            f"{lead} Pulli tarifga o'tishingiz mumkin: {terms}.{repeat} "
            "Shartlar va to'lov — obunalar bo'limida."
        )
    if language == "uz-Cyrl":
        lead = f"Сиз {free_days} кундан бери бепул тарифдан фойдаланасиз."
        terms = f"{offer.duration_days} кунлик обуна — {price}"
        if discount:
            terms += f", {discount}% чегирма билан"
        repeat = (
            f" Кейинги давр учун автоматик узайтириш — {renewal}."
            if renewal
            else " Автоматик узайтирилмайди."
        )
        return (
            f"{lead} Пулли тарифга ўтишингиз мумкин: {terms}.{repeat} Шартлар — обуналар бўлимида."
        )
    lead = f"You have used the free plan for {free_days} days."
    terms = f"A {offer.duration_days}-day subscription costs {price}"
    if discount:
        terms += f" with a {discount}% discount"
    repeat = (
        f" Automatically renews at {renewal} per period." if renewal else " No automatic renewal."
    )
    return f"{lead} You can upgrade: {terms}.{repeat} See the subscription section for checkout."


def render_expired_parent_offer(
    offer: PaidConversionOffer,
    free_days: int,
    ended_at: datetime,
    language: ResponseLanguage,
) -> str:
    """Retain all approved prices/renewal terms, replacing only the dated lead."""
    normal = render_parent_offer(offer, free_days, language)
    day = ended_at.astimezone(UTC).date().isoformat()
    leads: dict[ResponseLanguage, tuple[str, str]] = {
        "ru": (
            f"Вы пользуетесь бесплатным тарифом {free_days} дн.",
            f"Ваш бесплатный доступ на {free_days} дн. завершился {day} (UTC).",
        ),
        "uz-Latn": (
            f"Siz {free_days} kundan beri bepul tarifdan foydalanasiz.",
            f"{free_days} kunlik bepul kirishingiz {day} (UTC) kuni tugadi.",
        ),
        "uz-Cyrl": (
            f"Сиз {free_days} кундан бери бепул тарифдан фойдаланасиз.",
            f"{free_days} кунлик бепул киришингиз {day} (UTC) куни тугади.",
        ),
        "en": (
            f"You have used the free plan for {free_days} days.",
            f"Your {free_days}-day free access ended on {day} (UTC).",
        ),
    }
    old, new = leads[language]
    if not normal.startswith(old):
        raise ValueError("The approved offer template has an unexpected lead")
    return new + normal[len(old) :]


def render_trial_result(
    state: TrialGrantState,
    recorded_at: datetime,
    language: ResponseLanguage,
) -> str:
    """A service receipt, not a promotion, inference receipt or paid conversion."""
    recorded = recorded_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if state.status == "granted":
        if state.result is None or state.result.tariff != "Maxsus":
            raise ValueError("Free-day success requires its verified Maxsus receipt")
        end = state.result.valid_until.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        return {
            "ru": (
                f"Бесплатный Maxsus на {state.days} дн. подтверждён {recorded}. "
                f"Доступ до {end}. Это не оплата и не автосписание."
            ),
            "uz-Latn": (
                f"{state.days} kunlik bepul Maxsus {recorded} da tasdiqlandi. "
                f"Kirish {end} gacha. Bu to'lov yoki avtomatik yechish emas."
            ),
            "uz-Cyrl": (
                f"{state.days} кунлик бепул Maxsus {recorded} да тасдиқланди. "
                f"Кириш {end} гача. Бу тўлов ёки автоматик ечиш эмас."
            ),
            "en": (
                f"Your {state.days} free Maxsus days were confirmed at {recorded}. "
                f"Access ends at {end}. This is not a payment or automatic charge."
            ),
        }[language]
    if state.status == "submitting":
        raise ValueError("An in-flight action has no terminal result message")
    if state.status == "rejected":
        return {
            "ru": (
                f"На {recorded} backend отклонил выдачу бесплатных дней. "
                "Активация не подтверждена. Повторная выдача не запускалась; "
                "при необходимости обратитесь в поддержку."
            ),
            "uz-Latn": (
                f"{recorded} da backend bepul kunlarni rad etdi. Faollashuv tasdiqlanmadi. "
                "Qayta so'rov yuborilmadi; kerak bo'lsa yordam xizmatiga murojaat qiling."
            ),
            "uz-Cyrl": (
                f"{recorded} да backend бепул кунларни рад этди. Фаоллашув тасдиқланмади. "
                "Қайта сўров юборилмади; керак бўлса ёрдам хизматига мурожаат қилинг."
            ),
            "en": (
                f"At {recorded}, the backend rejected the free-day grant. "
                "Activation is not confirmed. No retry was sent; contact support if needed."
            ),
        }[language]
    return {
        "ru": (
            f"На {recorded} результат выдачи бесплатных дней неизвестен. "
            "Я не могу подтвердить активацию. Повторный запрос не отправлялся, "
            "чтобы не выполнить действие дважды; нужна проверка поддержки."
        ),
        "uz-Latn": (
            f"{recorded} da bepul kunlar natijasi noma'lum. Faollashuvni tasdiqlay olmayman. "
            "Takroriy amalni oldini olish uchun qayta so'rov yuborilmadi; "
            "yordam xizmati tekshirishi kerak."
        ),
        "uz-Cyrl": (
            f"{recorded} да бепул кунлар натижаси номаълум. Фаоллашувни тасдиқлай олмайман. "
            "Такрорий амални олдини олиш учун қайта сўров юборилмади; "
            "ёрдам хизмати текшириши керак."
        ),
        "en": (
            f"At {recorded}, the free-day grant outcome is unknown. I cannot confirm activation. "
            "No retry was sent to avoid repeating the action; support needs to check it."
        ),
    }[language]
