"""Bounded saved-report discovery contracts, not evidence or source-read authority."""

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.chat import ProductScope
from app.mana_operation_ai.domain.models import AgentReport

# A page bounds returned rows, not physical database scans. No automatic page loop.
REPORT_CATALOG_PAGE_SIZE = 10
REPORT_CATALOG_CURSOR_LIMIT = 1024


class SavedReportCatalogQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_id: str = Field(min_length=1, max_length=120)
    product: ProductScope
    agent_ids: tuple[Annotated[str, Field(min_length=1, max_length=80)], ...] = Field(
        min_length=1, max_length=8
    )
    before: AwareDatetime
    query: str = Field(default="", max_length=120)
    capability_key: str | None = Field(default=None, min_length=1, max_length=80)

    @property
    def scope_digest(self) -> str:
        value = self.model_dump(mode="json")
        value["agent_ids"] = sorted(set(self.agent_ids))
        value["before"] = self.before.astimezone(UTC).isoformat()
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class SavedReportCatalogPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    scope_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    report_id: str = Field(min_length=1, max_length=120)
    created_at: AwareDatetime

    @field_validator("version", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported catalog cursor version")
        return value


def catalog_cursor(query: SavedReportCatalogQuery, *, report_id: str, created_at: datetime) -> str:
    position = SavedReportCatalogPosition(
        scope_digest=query.scope_digest, report_id=report_id, created_at=created_at
    )
    return base64.urlsafe_b64encode(position.model_dump_json().encode()).decode()


def catalog_position(query: SavedReportCatalogQuery, cursor: str) -> SavedReportCatalogPosition:
    """An observation position, not a signed grant. SQL rechecks its exact anchor."""
    try:
        if not cursor or len(cursor) > REPORT_CATALOG_CURSOR_LIMIT:
            raise ValueError("Invalid cursor length")
        position = SavedReportCatalogPosition.model_validate_json(
            base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
        )
        if position.scope_digest != query.scope_digest or position.created_at >= query.before:
            raise ValueError("Cursor does not belong to the frozen query")
    except (ValueError, UnicodeError, binascii.Error, ValidationError) as exc:
        raise ChatError("Курсор не принадлежит этому поиску сохранённых отчётов.", 422) from exc
    return position


def catalog_report_matches(query: SavedReportCatalogQuery, report: AgentReport) -> bool:
    """Defend the application port even when a fake or future adapter misfilters."""
    return (
        report.agent_id in query.agent_ids
        and report.created_at.utcoffset() is not None
        and report.created_at < query.before
        and report.structured.get("product") == query.product
        and (query.capability_key is None or report.capability_key == query.capability_key)
        and (query.query in report.report_type or query.query in report.human_readable)
    )


@dataclass(frozen=True)
class SavedReportCandidatePage:
    # Infrastructure applies coarse SQL filters. Application scope validation is mandatory.
    reports: tuple[AgentReport, ...]
    next_cursor: str | None
