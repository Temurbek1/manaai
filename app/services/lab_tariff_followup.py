"""Small declared fake refinements; production interpretation belongs to the model."""

import re

from app.mana_ai.domain.client_upsell import UpsellChoice, UpsellEnquiry


def simulated_tariff_refinement(data: object, latest: str) -> UpsellEnquiry | None:
    if not isinstance(data, dict) or not isinstance(data.get("tariff_followup"), dict):
        return None
    context = data["tariff_followup"]
    prior = UpsellChoice.model_validate(context["previous_terms"])
    text = latest.strip().casefold().rstrip("?.!")
    duration = re.fullmatch(r"(?:а на|yana|what about) (30|90|180|365)(?: дней| kun| days)?", text)
    cheaper = text in {"а дешевле", "arzonrog‘i bormi", "cheaper"}
    if duration is None and not cheaper:
        return None
    values = prior.model_dump() | {"parent_quote": latest}
    if duration:
        values.update(minimum_days=int(duration[1]), maximum_days=int(duration[1]))
    if cheaper:
        reference = context.get("strictly_cheaper_reference")
        if not isinstance(reference, dict) or reference.get("positive_price_can_match") is not True:
            return None
        values["objective"] = "lowest_total"
        values["maximum_price_minor"] = reference["maximum_price_minor"]
    return UpsellEnquiry.model_validate(values)
