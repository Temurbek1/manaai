from typing import Protocol

from app.mana_operation_ai.application.ports import ProviderPermanentError
from app.mana_operation_ai.domain.parents import ParentSummary


class ParentSummaryPort(Protocol):
    integration_id: str

    async def collect_summary(self) -> ParentSummary: ...


class ParentReadCooldownError(ProviderPermanentError):
    """The shared source-read admission lease has not expired."""
