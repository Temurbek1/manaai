"""A fresh collection timestamp never manufactures observation or SQL-save dates."""

from datetime import UTC, datetime, timedelta

from app.mana_operation_ai.application.chat_service import INSTRUCTIONS, _budget_fallback
from app.mana_operation_ai.application.evidence_dates import EVIDENCE_DATE_INSTRUCTIONS
from app.mana_operation_ai.application.goal_service import GOAL_INSTRUCTIONS
from app.mana_operation_ai.application.runtime import SystemClock
from scripts.operation_goal_evaluate import SyntheticAdmin


class FixedClock(SystemClock):
    def now(self) -> datetime:
        return datetime(2026, 10, 14, tzinfo=UTC)


def test_both_model_lanes_share_the_same_explicit_timestamp_roles() -> None:
    for instructions in (INSTRUCTIONS, GOAL_INSTRUCTIONS):
        assert instructions.count(EVIDENCE_DATE_INSTRUCTIONS) == 1
        assert "not user activity, cohort start, payment or" in instructions
        assert "unknown even if collected_at is present and recent" in instructions
        assert "never observation or report-save time" in instructions
        assert "grant another source read" in instructions
    assert "without an application-database analytics" in INSTRUCTIONS
    assert "request" in INSTRUCTIONS


def test_budget_fallback_labels_collection_without_claiming_observation_or_storage() -> None:
    clock = FixedClock()
    report = SyntheticAdmin(clock).report
    collected = clock.now() - timedelta(minutes=10)
    assert report.created_at != collected
    answer = _budget_fallback([report], now=clock.now())
    assert f"Сбор данных: {collected.isoformat()}" in answer
    assert "давность сбора: 10 мин" in answer
    assert "Данные на" not in answer and "сохранён " not in answer
    assert "Новый AI-анализ не выполнялся" in answer
    assert "новые данные не запрашивались" in answer
