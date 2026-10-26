"""Explicit fictional clock/text for the isolated, model-free comparison lab."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.mana_ai.domain.source_reviews import CounterComparisonView


class LabUsageComparisonClock:
    def __init__(self) -> None:
        self._phase: Literal["baseline", "current", "ready"] = "baseline"
        self._path: Path | None = None

    def now(self) -> datetime:
        return datetime(
            2026,
            10,
            25 if self._phase == "baseline" else 26,
            9,
            second=3 if self._phase == "ready" else 0,
            tzinfo=UTC,
        )

    def restore(self, directory: Path) -> None:
        self._path = directory / "comparison-clock.json"
        if self._path.is_symlink():
            raise ValueError("A fictional clock cannot use a symlink")
        if self._path.exists():
            value = json.loads(self._path.read_text())
            if (
                not isinstance(value, dict)
                or set(value) != {"kind", "phase"}
                or value["kind"] != "fictional_usage_comparison_v1"
                or value["phase"] not in {"baseline", "current", "ready"}
            ):
                raise ValueError("Invalid fictional comparison clock")
            self._phase = value["phase"]

    def _save(self, phase: Literal["current", "ready"]) -> None:
        if self._path is None:
            raise ValueError("A fictional comparison clock must be restored before advancing")
        if self._phase == "ready" or self._phase == phase:
            return
        temporary = self._path.with_suffix(".next")
        with os.fdopen(
            os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as stream:
            json.dump({"kind": "fictional_usage_comparison_v1", "phase": phase}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self._path)
        self._phase = phase

    def next_day(self) -> None:
        self._save("current")

    def ready(self) -> None:
        self._save("ready")


def comparison_text(view: CounterComparisonView, *, uzbek: bool = False) -> str:
    left, right = view.previous_query_calendar_day, view.current_query_calendar_day
    if not view.matched_single_rows:
        return (
            f"{left} va {right} so‘rovlarida solishtirish uchun aniq mos qatorlar yo‘q."
            if uzbek
            else f"В запросах за {left} и {right} нет однозначно сопоставимых строк."
        )
    row = view.matched_single_rows[0]
    return (
        f"{left} va {right} so‘rovlarida {row.app_name} hisoblagichi "
        f"{row.previous_reported_seconds} va {row.current_reported_seconds} soniya. "
        "Sahifalar qisman; davr va vaqt zonasi noma’lum. Bu kunlik ekran vaqti emas."
        if uzbek
        else f"В запросах за {left} и {right} счётчик {row.app_name}: "
        f"{row.previous_reported_seconds} и {row.current_reported_seconds} секунд. "
        "Страницы неполные, период и часовой пояс неизвестны. Это не экранное время за день."
    )
