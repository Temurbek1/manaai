from datetime import datetime, timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, ValidationError

from app.mana_operation_ai.application.ports import Clock, ProviderPermanentError
from app.mana_operation_ai.domain.parents import ParentSummary
from app.mana_operation_ai.infrastructure.retention.manakids import ManakidsAdminActivityAdapter


class _Child(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int = Field(strict=True, gt=0)
    is_connected: StrictBool


class _Parent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int = Field(strict=True, gt=0)
    fullname: str | None
    phone: str | None
    age: int | None = Field(ge=0, le=150)
    region: str | None
    district: str | None
    tariff_name: str | None
    valid_until: str | None
    payment_date: str | None
    children: list[_Child] = Field(max_length=1000)
    children_count: int | None = Field(default=None, ge=0)


class _Page(BaseModel):
    model_config = ConfigDict(extra="ignore")
    count: int = Field(strict=True, ge=0)
    next: str | None
    results: list[_Parent] = Field(max_length=100)


class _Timestamp(BaseModel):
    value: AwareDatetime


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _Timestamp(value=value).value
    except ValidationError:
        return None


class ManakidsParentSummaryAdapter:
    """A bounded prefix sample. Raw parent/child fields never leave this adapter."""

    integration_id = "manakids_parent_api"

    def __init__(self, reader: ManakidsAdminActivityAdapter, clock: Clock, limit: int) -> None:
        if not 1 <= limit <= 100:
            raise ValueError("Parent sample limit must be between 1 and 100")
        self._reader = reader
        self._clock = clock
        self._limit = limit

    async def collect_summary(self) -> ParentSummary:
        payload, request_id = await self._reader.read_parent_page(limit=self._limit)
        try:
            page = _Page.model_validate(payload)
        except ValidationError:
            raise ProviderPermanentError("Parent API response contract is invalid") from None
        if len(page.results) > self._limit or len(page.results) > page.count:
            raise ProviderPermanentError("Parent API response exceeded the requested sample")
        if len({row.id for row in page.results}) != len(page.results):
            raise ProviderPermanentError("Parent API returned duplicate parent rows")
        if page.count and not page.results:
            raise ProviderPermanentError("Parent API returned an inconsistent empty page")
        now = self._clock.now()
        counts = dict.fromkeys(
            [
                "parents_with_name",
                "parents_with_phone",
                "parents_with_known_age",
                "parents_with_region",
                "parents_with_district",
                "parents_with_current_tariff",
                "parents_without_current_tariff",
                "parents_with_inconsistent_tariff",
                "tariffs_expiring_within_7_days",
                "tariffs_expiring_within_30_days",
                "parents_with_purchase_date",
                "parents_with_children",
                "parents_with_connected_children",
                "child_relationships_observed",
                "connected_child_relationships",
            ],
            0,
        )
        children_incomplete = False
        for row in page.results:
            if len({child.id for child in row.children}) != len(row.children):
                raise ProviderPermanentError("Parent API returned duplicate child relationships")
            for field in ["name", "phone", "region", "district"]:
                value = getattr(row, "fullname" if field == "name" else field)
                counts[f"parents_with_{field}"] += bool(value and value.strip())
            counts["parents_with_known_age"] += bool(row.age and row.age > 0)
            expiry = _timestamp(row.valid_until)
            purchase = _timestamp(row.payment_date)
            current = bool(row.tariff_name and row.tariff_name.strip() and expiry and expiry >= now)
            absent = all(
                value is None for value in [row.tariff_name, row.valid_until, row.payment_date]
            )
            counts["parents_with_current_tariff"] += current
            counts["parents_without_current_tariff"] += absent
            counts["parents_with_inconsistent_tariff"] += not current and not absent
            if current and expiry:
                counts["tariffs_expiring_within_7_days"] += expiry <= now + timedelta(days=7)
                counts["tariffs_expiring_within_30_days"] += expiry <= now + timedelta(days=30)
            counts["parents_with_purchase_date"] += purchase is not None and purchase <= now
            connected = sum(child.is_connected for child in row.children)
            counts["parents_with_children"] += bool(row.children)
            counts["parents_with_connected_children"] += connected > 0
            counts["child_relationships_observed"] += len(row.children)
            counts["connected_child_relationships"] += connected
            children_incomplete |= row.children_count is not None and row.children_count != len(
                row.children
            )
        limitations = [
            "Источник относится только к MANA; привязка подтверждена владельцем интеграции.",
            "Только ограниченная первая страница, не случайная и не репрезентативная выборка. "
            "Все показатели, кроме общего count, относятся лишь к прочитанным родителям.",
            "Текущий тариф может быть бесплатным; payment_date — дата записи покупки, "
            "не доказательство платежа. Выручка, платящие пользователи и история оплат неизвестны.",
            "Отсутствие текущего тарифа не доказывает отмену, отток или причину отказа.",
            "Связи с детьми считаются по родителям, не как уникальные дети всей базы. "
            "is_connected — связь с этим родителем, не online-статус и не активность в приложении.",
            "Имена, телефоны, возраст, адресные значения, ID, аватары и данные детей "
            "не сохраняются и не передаются модели; сохраняются только счётчики.",
        ]
        if children_incomplete:
            limitations.append(
                "Количество children_count не совпадает с вложенным списком; "
                "связи наблюдаются частично."
            )
        if counts["parents_with_inconsistent_tariff"]:
            limitations.append(
                "Есть неполные/противоречивые тарифные поля; они не считаются отсутствием тарифа."
            )
        return ParentSummary(
            source=self.integration_id,
            mode="live_read_only",
            collected_at=now,
            total_parents=page.count,
            sampled_parents=len(page.results),
            has_more=bool(page.next) or page.count > len(page.results),
            source_request_ids=[request_id] if request_id else [],
            limitations=limitations,
            **counts,
        )


class UnavailableParentSummaryAdapter:
    integration_id = "manakids_parent_api"

    async def collect_summary(self) -> ParentSummary:
        raise ProviderPermanentError("MANA Parent API is disabled; configure its read-only source")


class FakeParentSummaryAdapter:
    integration_id = "fake_mana_parent_api"

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def collect_summary(self) -> ParentSummary:
        return ParentSummary(
            source=self.integration_id,
            mode="demo",
            collected_at=self._clock.now(),
            total_parents=120,
            sampled_parents=10,
            has_more=True,
            parents_with_name=7,
            parents_with_phone=10,
            parents_with_known_age=3,
            parents_with_region=8,
            parents_with_district=5,
            parents_with_current_tariff=6,
            parents_without_current_tariff=3,
            parents_with_inconsistent_tariff=1,
            tariffs_expiring_within_7_days=2,
            tariffs_expiring_within_30_days=4,
            parents_with_purchase_date=6,
            parents_with_children=8,
            parents_with_connected_children=5,
            child_relationships_observed=12,
            connected_child_relationships=7,
            limitations=["Synthetic test sample, not live MANA data; not payment evidence."],
        )
