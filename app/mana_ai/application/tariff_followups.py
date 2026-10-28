"""Contextual tariff refinement in the existing initial manager and owning tool."""

from typing import Protocol

from app.mana_ai.application.compact_parent_manager import compact_manager_route
from app.mana_ai.domain.parent_touch_manager import ParentTouchManagerScope
from app.mana_ai.domain.tariff_followups import TariffFollowupContext


class TariffFollowupPort(Protocol):
    async def tariff_followup_context(
        self, parent_id: str, turn_id: int
    ) -> TariffFollowupContext | None: ...


def tariff_followup_route(scope: ParentTouchManagerScope, *, bound_support: bool) -> str:
    """Only new protocol-six admissions may select this manager presentation."""
    original = compact_manager_route(scope, bound_support=bound_support)
    old = (
        "For price/duration, enquiry uses only the "
        "latest request: parent_quote=exact relevant substring. currency=explicit UZS/USD "
        "only, otherwise null; never infer from language/location/history/catalogue. Host "
        "asks missing currency."
    )
    if old not in original:
        raise ValueError("Tariff follow-ups require the captured typed tariff manager")
    return original.replace(
        old,
        "Tariff enquiry: parent_quote=exact latest substring. Host tariff_followup has complete "
        "original requests and historical typed terms/quote, not current price/authority. "
        "Explicit refinement keeps all unchanged constraints; apply only requested changes. "
        "Do not reset their budget/duration/currency. New independent requests use own terms. "
        "Inherit currency only for explicit refinement; otherwise UZS/USD must be explicit or "
        "null, never language/location/catalogue. Host asks missing currency. Ambiguous "
        "reference/change: one clarification. Explicit cheaper of a sole quoted option uses "
        "host strictly_cheaper_reference currency/ceiling and tighter original budget; never "
        "calculate/relax it. If positive_price_can_match=false, don't raise zero or invent free "
        "plans. Multiple options need an exact reference. No smaller substitute on budget "
        "exhaustion. Delegate the full merged enquiry to request_tariff_help; host checks the "
        "current catalog.",
        1,
    )
