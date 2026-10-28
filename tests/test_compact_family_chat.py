"""Unavailable saved evidence remains useful and qualified in the actual fake chat."""

from pathlib import Path
from uuid import uuid4

import pytest

from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.services.mana_chat_lab import LAB_PARENT
from tests.test_compact_source_tools import setup


@pytest.mark.parametrize(
    "message,unknown,no_refresh",
    [
        ("Проверь сохранённый заряд ребёнка", "данные неизвестны", "Источник не обновлялся"),
        (
            "Iltimos, farzandning saqlangan quvvatini tekshiring",
            "ma’lumot noma’lum",
            "Manba qayta yangilanmagan",
        ),
    ],
)
async def test_missing_saved_observation_reaches_qualified_parent_reply(
    tmp_path: Path, message: str, unknown: str, no_refresh: str
) -> None:
    lab, _ = await setup(tmp_path / "missing")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message=message
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        reviewed = await lab.safety.process_one()
        assert reviewed and reviewed.status == "completed"
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "completed" and state.response
        assert unknown in state.response.answer and no_refresh in state.response.answer
        assert state.response.speaker == "parent-touch"
        assert lab.battery.calls == lab.location.calls == lab.app_usage.calls == 0
        with lab.store._connect() as db:
            assert (
                db.execute("SELECT status FROM saved_observation_inspections").fetchone()[0]
                == "unavailable"
            )
    finally:
        await lab.close()
