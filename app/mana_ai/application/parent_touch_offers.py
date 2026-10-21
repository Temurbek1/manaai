"""Parent-Touch's approved commercial wording, not model-generated financial terms.

Eligibility requires no LLM. These assistant-only messages use no inference tokens
and create no fabricated provider receipt. Subsequent parent conversation remains AI.
"""

from app.mana_ai.domain.chat import ResponseLanguage
from app.mana_ai.domain.conversion import ConversionOffer


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
