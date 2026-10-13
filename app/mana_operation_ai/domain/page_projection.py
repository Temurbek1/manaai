"""Exact read-only references to saved-page text already loaded into Goal evidence."""

from typing import Literal

from pydantic import Field, model_validator

from app.mana_operation_ai.domain.models import DomainModel


class SavedPageReceipt(DomainModel):
    report_id: str = Field(min_length=1, max_length=128)
    offset: int = Field(ge=0, le=32000, strict=True)
    text: str = Field(min_length=1, max_length=4000)
    total_characters: int = Field(ge=1, le=32000, strict=True)
    next_offset: int | None = Field(ge=1, le=32000, strict=True)
    loaded_into_evidence: Literal[True]
    reading_not_population_coverage: Literal[True]

    @model_validator(mode="after")
    def exact_range(self) -> "SavedPageReceipt":
        end = self.offset + len(self.text)
        if end > self.total_characters or self.next_offset != (
            end if end < self.total_characters else None
        ):
            raise ValueError("Saved page receipt has an inconsistent exact range")
        return self


class EvidenceTextPointer(DomainModel):
    location: Literal["goal.evidence.summary"] = "goal.evidence.summary"
    characters: int = Field(ge=1, le=4000, strict=True)
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    full_text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProjectedSavedPageReceipt(DomainModel):
    report_id: str = Field(min_length=1, max_length=128)
    offset: int = Field(ge=0, le=32000, strict=True)
    text_reference: EvidenceTextPointer
    total_characters: int = Field(ge=1, le=32000, strict=True)
    next_offset: int | None = Field(ge=1, le=32000, strict=True)
    loaded_into_evidence: Literal[True]
    reading_not_population_coverage: Literal[True]

    @model_validator(mode="after")
    def exact_range(self) -> "ProjectedSavedPageReceipt":
        end = self.offset + self.text_reference.characters
        if end > self.total_characters or self.next_offset != (
            end if end < self.total_characters else None
        ):
            raise ValueError("Projected page receipt has an inconsistent exact range")
        return self


class PageOutputRef(DomainModel):
    """Runtime provenance of a reduced function result; never a read grant."""

    position: int = Field(ge=0, le=127, strict=True)
    item_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    tool_position: int = Field(ge=0, le=119, strict=True)
    tool_call_id: str = Field(min_length=1, max_length=128)
    page: ProjectedSavedPageReceipt
