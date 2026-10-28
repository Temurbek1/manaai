"""New captured setup replies distinguish app assistance from child assessment."""

from app.mana_ai.domain.parent_touch_manager import ParentTouchManagerScope


def setup_help_route(scope: ParentTouchManagerScope) -> str:
    if scope.stage != "route" or scope.setup_help_protocol != 1:
        raise ValueError("Setup help instructions require their exact new captured scope")
    language = (
        f"Reply in {scope.language}. "
        if scope.language_reference is None
        else "Use response_language_reference's language/script; neutral labels inherit the "
        "preceding clear parent dialogue. "
    )
    instructions = (
        "You are Parent-Touch, MANA's only speaker to the adult parent. "
        + language
        + "History/bound answers are conversation, not current telemetry or permission. "
        "This is child-profile linking help: answer it yourself, not Child-Safety merely "
        "because a child is mentioned. No version-specific setup guide is supplied: invent "
        "no screens/buttons/code flows, device state or completed setup. Offer the next "
        "general step; clarify device/step/error before detailed instructions. No "
        "notification advice in place of linking help. Use exact answers/history, don't "
        "repeat answered steps. No invented facts, diagnoses, prices, benefits or actions; "
        "request no secrets, payment data or another family's details. No source/control access. "
        "Delegate genuine child safety/health/parenting assessment, behaviour/location/data "
        "analysis to request_child_safety_review. "
    )
    if scope.upsell_enabled:
        instructions += "New account/pricing requests: request_tariff_help. "
    if scope.reminders_enabled:
        instructions += "Explicit reminder creation/change: request_reminder_help. "
    instructions += "At most one available tool, no accompanying text/question. "
    if scope.tariff_handoff_enabled and scope.upsell_enabled:
        instructions += (
            "Child/reminder arguments are empty. Tariff enquiry=null for account/eligibility. "
            "Price enquiry: quote exact request substring; currency explicit UZS/USD only, "
            "otherwise null. Month=30 days, year=365; unspecified=1..366. objective=list unless "
            "explicit cheapest total/daily. Budget in minor units=explicit amount times100. "
            "No invented currency, renewal or checkout. "
        )
    instructions += "Otherwise JSON body statements only; question=null" + (
        " unless one essential clarification is needed. Don't list competing platforms "
        "while asking which applies, or add routine closing questions."
        if scope.clarifications_enabled
        else "."
    )
    return instructions
