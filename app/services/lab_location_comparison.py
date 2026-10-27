"""Explicit model-free two-point fixture; never real GPS or a collection schedule."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.child_location import ChildLocationFacts, LocationComparisonView
from app.mana_ai.domain.family_sources import FamilySourceTarget
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.services.lab_usage_comparison import LabUsageComparisonClock

if TYPE_CHECKING:
    from app.services.mana_chat_lab import ChatLab


class LabLocationComparisonClock(LabUsageComparisonClock):
    kind = "fictional_location_comparison_v1"
    filename = "location-comparison-clock.json"


class LabComparisonLocationSource:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock, self.calls = clock, 0

    async def read(self, child_id: int) -> ChildLocationFacts:
        self.calls += 1
        now = self._clock()
        return ChildLocationFacts(
            child_id=child_id,
            status="available",
            position_fingerprint=("a" if now.day == 25 else "b") * 64,
            observed_at=now - timedelta(minutes=1),
            source_updated_at=now - timedelta(seconds=30),
            collected_at=now,
            quality="dated",
            mock=False,
            sample=False,
            is_moving=None,
            accuracy_reported=True,
        )


def location_comparison_text(view: LocationComparisonView, *, uzbek: bool = False) -> str:
    previous, current = view.previous.observed_at, view.current.observed_at
    return (
        f"Saqlangan GPS yozuvlari: {previous} va {current}. "
        "Ikki yozuv yo‘nalish, haqiqiy harakat yoki xavfni tasdiqlamaydi."
        if uzbek
        else f"Сохранённые GPS-записи: {previous} и {current}. "
        "По двум записям нельзя восстановить маршрут или подтвердить перемещение и опасность."
    )


async def prepare_location_comparison(lab: "ChatLab") -> dict[str, object]:
    from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT

    if (
        not lab.options.location_comparisons
        or lab.options.real_model
        or not isinstance(lab.options.clock, LabLocationComparisonClock)
    ):
        raise ParentChatError("lab_location_comparison_disabled", 409)
    assert lab.touch.proactive is not None
    baseline = await lab.sources.read(
        FamilySourceTarget(
            parent_id=LAB_PARENT,
            child_id=LAB_CHILD,
            source="firebase.child_location.v1",
            request_id=uuid5(NAMESPACE_URL, "fictional-location-comparison-baseline-v1"),
        )
    )
    if baseline.status != "completed":
        raise ParentChatError("lab_location_comparison_unresolved", 409)
    lab.options.clock.next_day()
    now = lab.options.clock.now()
    if await lab.store.contact_context(LAB_PARENT, now) is None:
        await lab.touch.proactive.register(
            ParentContactContext(
                parent_id=LAB_PARENT,
                event_id=uuid4(),
                revision=int(now.timestamp() * 1000000),
                observed_at=now,
                valid_until=now + timedelta(days=1),
                language="ru",
                timezone="Asia/Samarkand",
                safety_chat_consent=True,
                safety_push_consent=False,
                marketing_push_consent=False,
            )
        )
    current = await lab.sources.read(
        FamilySourceTarget(
            parent_id=LAB_PARENT,
            child_id=LAB_CHILD,
            source="firebase.child_location.v1",
            request_id=uuid5(NAMESPACE_URL, "fictional-location-comparison-current-v1"),
        )
    )
    if current.status != "completed":
        raise ParentChatError("lab_location_comparison_unresolved", 409)
    lab.options.clock.ready()
    return {"status": "completed", "external_requests": 0}
