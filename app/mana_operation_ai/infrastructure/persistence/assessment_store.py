from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.mana_operation_ai.domain.cost_control import ProductScope
from app.mana_operation_ai.domain.retention import EngagementAssessment
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import EngagementAssessmentRow


class SqlAlchemyEngagementAssessmentStore:
    def __init__(self, database: OperationDatabase) -> None:
        self._database = database
        self._dialect = database.engine.dialect.name
        if self._dialect not in {"sqlite", "postgresql"}:
            raise ValueError("Assessment reuse supports SQLite and PostgreSQL")

    async def get(
        self, key: str, *, product: ProductScope, now: datetime
    ) -> EngagementAssessment | None:
        if now.utcoffset() is None:
            raise ValueError("Assessment reuse requires an aware clock")
        async with self._database.session_factory() as session:
            row = await session.get(EngagementAssessmentRow, key)
            if row is None or row.product != product.value:
                return None
            expiry = row.valid_until
            if expiry.utcoffset() is None:
                expiry = expiry.replace(tzinfo=UTC)
            if now >= expiry:
                return None
            result = EngagementAssessment.model_validate(row.payload)
            if result.product is not product or result.valid_until != expiry:
                return None
            return result

    async def put(self, key: str, result: EngagementAssessment) -> None:
        if result.product is ProductScope.UNVERIFIED or result.valid_until.utcoffset() is None:
            raise ValueError("Unverified or undated assessments cannot be reused")
        async with self._database.session_factory() as session, session.begin():
            insert: Any = sqlite_insert if self._dialect == "sqlite" else postgres_insert
            # The key covers complete immutable inputs and versioned pure rules.
            # Racing CPU-only calculations may finish, but cannot overwrite the
            # first accepted result or extend its validity. No paid work occurs here.
            await session.execute(
                insert(EngagementAssessmentRow)
                .values(
                    assessment_key=key,
                    product=result.product.value,
                    valid_until=result.valid_until,
                    payload=result.model_dump(mode="json"),
                )
                .on_conflict_do_nothing(index_elements=["assessment_key"])
            )
