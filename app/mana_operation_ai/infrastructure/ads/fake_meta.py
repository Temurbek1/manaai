import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from pydantic import JsonValue

from app.mana_operation_ai.application.marketing.metrics import build_metrics
from app.mana_operation_ai.application.ports import Clock, ProviderObjectNotFoundError
from app.mana_operation_ai.domain.enums import ActionType, IntegrationStatus, ProviderMode
from app.mana_operation_ai.domain.marketing import (
    AdAccount,
    AdEntity,
    AdEntityType,
    AdsCollectionRequest,
    AdsSnapshot,
    Audience,
    Creative,
    InsightRow,
    ProviderActionResult,
    ProviderDiagnostic,
    ProviderObjectState,
)
from app.mana_operation_ai.domain.models import (
    ActionParameters,
    AudienceActionParameters,
    BudgetActionParameters,
    IntegrationHealth,
    StatusActionParameters,
)


class FakeMetaAdsAdapter:
    """Mutable sandbox provider used for demos and all write-path tests."""

    def __init__(self, *, clock: Clock, snapshot: AdsSnapshot | None = None) -> None:
        self._clock = clock
        self._snapshot = snapshot or build_demo_snapshot(clock.now())
        self._states = _states_from_snapshot(self._snapshot)
        self._results: dict[str, ProviderActionResult] = {}
        self._lock = asyncio.Lock()

    @property
    def provider_name(self) -> str:
        return "fake_meta"

    @property
    def provider_mode(self) -> ProviderMode:
        return ProviderMode.FAKE_EXECUTABLE

    async def collect(self, request: AdsCollectionRequest) -> AdsSnapshot:
        rows = [
            row
            for row in self._snapshot.insights
            if row.date_start <= request.date_stop and row.date_stop >= request.date_start
        ]
        return self._snapshot.model_copy(
            update={
                "collected_at": self._clock.now(),
                "period_start": datetime.combine(
                    request.date_start,
                    datetime.min.time(),
                    tzinfo=UTC,
                ),
                "period_end": datetime.combine(request.date_stop, datetime.max.time(), tzinfo=UTC),
                "attribution_window": request.attribution_window,
                "insights": rows,
            },
            deep=True,
        )

    async def health(self) -> IntegrationHealth:
        now = self._clock.now()
        return IntegrationHealth(
            integration_id="fake_meta",
            status=IntegrationStatus.HEALTHY,
            checked_at=now,
            last_success_at=now,
            latency_ms=0,
            message="Sandbox Meta adapter is ready",
            diagnostics={"mode": "fake", "real_spend_possible": False},
        )

    async def get_object_state(
        self,
        object_type: str,
        provider_object_id: str,
    ) -> ProviderObjectState:
        del object_type
        async with self._lock:
            try:
                return self._states[provider_object_id].model_copy(deep=True)
            except KeyError as exc:
                raise ProviderObjectNotFoundError(
                    f"Fake Meta object {provider_object_id!r} was not found",
                ) from exc

    async def execute(
        self,
        *,
        object_type: str,
        provider_object_id: str,
        parameters: ActionParameters,
        idempotency_key: str,
    ) -> ProviderActionResult:
        del object_type
        async with self._lock:
            previous_result = self._results.get(idempotency_key)
            if previous_result is not None:
                return previous_result.model_copy(deep=True)
            try:
                current = self._states[provider_object_id]
            except KeyError as exc:
                raise ProviderObjectNotFoundError(
                    f"Fake Meta object {provider_object_id!r} was not found",
                ) from exc

            updated = _apply_parameters(current, parameters, self._clock.now())
            self._states[provider_object_id] = updated
            self._snapshot = _update_snapshot_entity(self._snapshot, updated)
            result = ProviderActionResult(
                provider_request_id=f"fake-request-{len(self._results) + 1}",
                accepted=True,
                applied_state=updated,
                diagnostics={"sandbox": True, "real_spend_possible": False},
            )
            self._results[idempotency_key] = result
            return result.model_copy(deep=True)


def build_demo_snapshot(now: datetime) -> AdsSnapshot:
    current_day = now.date()
    previous_day = current_day - timedelta(days=8)
    account = AdAccount(
        provider_id="act_demo",
        name="MANA Demo Ads",
        currency="USD",
        timezone="UTC",
        status="ACTIVE",
    )
    campaigns = [
        _entity("cmp_growth", AdEntityType.CAMPAIGN, "Growth", "120"),
        _entity("cmp_retarget", AdEntityType.CAMPAIGN, "Retargeting", "80"),
    ]
    ad_sets = [
        _entity("set_cheap", AdEntityType.AD_SET, "Parents - broad", "60", "cmp_growth"),
        _entity("set_expensive", AdEntityType.AD_SET, "Parents - narrow", "45", "cmp_retarget"),
    ]
    ads = [
        _entity("ad_best", AdEntityType.AD, "Not Answering the Phone", None, "set_cheap"),
        _entity("ad_weak", AdEntityType.AD, "Generic Safety", None, "set_expensive"),
    ]
    creatives = [
        Creative(
            provider_id="creative_best",
            account_id="act_demo",
            name="Not Answering the Phone",
            title="Know when they need you",
            format="video",
        ),
        Creative(
            provider_id="creative_weak",
            account_id="act_demo",
            name="Generic Safety",
            title="Family safety",
            format="image",
        ),
    ]
    audiences = [
        Audience(
            provider_id="aud_cheap",
            account_id="act_demo",
            name="Parents - broad",
            subtype="saved",
            status="ACTIVE",
            targeting_attributes={"age_min": 25, "age_max": 44},
        ),
        Audience(
            provider_id="aud_expensive",
            account_id="act_demo",
            name="Parents - narrow",
            subtype="saved",
            status="ACTIVE",
            targeting_attributes={"age_min": 35, "age_max": 44},
        ),
    ]
    current_rows = [
        _insight(
            row_id="current-best",
            day=current_day,
            ad_id="ad_best",
            ad_name="Not Answering the Phone",
            creative_id="creative_best",
            audience_id="aud_cheap",
            campaign_id="cmp_growth",
            ad_set_id="set_cheap",
            spend="20",
            impressions="2500",
            reach="2100",
            clicks="105",
            link_clicks="100",
            conversions="25",
            leads="25",
            revenue="500",
            dimensions={
                "placement": "facebook_feed",
                "region": "Tashkent",
                "age": "25-34",
                "gender": "female",
                "hour": "20",
                "day": current_day.strftime("%A"),
            },
        ),
        _insight(
            row_id="current-weak",
            day=current_day,
            ad_id="ad_weak",
            ad_name="Generic Safety",
            creative_id="creative_weak",
            audience_id="aud_expensive",
            campaign_id="cmp_retarget",
            ad_set_id="set_expensive",
            spend="100",
            impressions="5000",
            reach="900",
            clicks="30",
            link_clicks="24",
            conversions="2",
            leads="2",
            revenue="10",
            dimensions={
                "placement": "instagram_reels",
                "region": "Samarkand",
                "age": "35-44",
                "gender": "male",
                "hour": "03",
                "day": current_day.strftime("%A"),
            },
        ),
    ]
    baseline_rows = [
        _insight(
            row_id="baseline-best",
            day=previous_day,
            ad_id="ad_best",
            ad_name="Not Answering the Phone",
            creative_id="creative_best",
            audience_id="aud_cheap",
            campaign_id="cmp_growth",
            ad_set_id="set_cheap",
            spend="20",
            impressions="2400",
            reach="2000",
            clicks="80",
            link_clicks="76",
            conversions="15",
            leads="15",
            revenue="260",
            dimensions={"placement": "facebook_feed", "region": "Tashkent"},
        ),
        _insight(
            row_id="baseline-weak",
            day=previous_day,
            ad_id="ad_weak",
            ad_name="Generic Safety",
            creative_id="creative_weak",
            audience_id="aud_expensive",
            campaign_id="cmp_retarget",
            ad_set_id="set_expensive",
            spend="60",
            impressions="4000",
            reach="1800",
            clicks="60",
            link_clicks="50",
            conversions="6",
            leads="6",
            revenue="50",
            dimensions={"placement": "instagram_reels", "region": "Samarkand"},
        ),
    ]
    return AdsSnapshot(
        provider="fake_meta",
        collected_at=now,
        period_start=datetime.combine(previous_day, datetime.min.time(), tzinfo=UTC),
        period_end=datetime.combine(current_day, datetime.max.time(), tzinfo=UTC),
        attribution_window="7d_click",
        accounts=[account],
        campaigns=campaigns,
        ad_sets=ad_sets,
        ads=ads,
        creatives=creatives,
        audiences=audiences,
        available_targeting_attributes={
            "age": ["18-24", "25-34", "35-44", "45-54"],
            "gender": ["female", "male", "unknown"],
            "region": ["Tashkent", "Samarkand"],
            "placement": ["facebook_feed", "instagram_reels"],
        },
        insights=[*baseline_rows, *current_rows],
        diagnostics=[
            ProviderDiagnostic(operation="collect", status_code=200, message="fixture"),
        ],
    )


def _entity(
    provider_id: str,
    entity_type: AdEntityType,
    name: str,
    budget: str | None,
    parent_id: str | None = None,
) -> AdEntity:
    return AdEntity(
        provider_id=provider_id,
        entity_type=entity_type,
        account_id="act_demo",
        parent_id=parent_id,
        name=name,
        status="ACTIVE",
        effective_status="ACTIVE",
        daily_budget=Decimal(budget) if budget is not None else None,
        currency="USD",
    )


def _insight(
    *,
    row_id: str,
    day: date,
    ad_id: str,
    ad_name: str,
    creative_id: str,
    audience_id: str,
    campaign_id: str,
    ad_set_id: str,
    spend: str,
    impressions: str,
    reach: str,
    clicks: str,
    link_clicks: str,
    conversions: str,
    leads: str,
    revenue: str,
    dimensions: dict[str, str],
) -> InsightRow:
    return InsightRow(
        row_id=row_id,
        account_id="act_demo",
        entity_type=AdEntityType.AD,
        entity_id=ad_id,
        entity_name=ad_name,
        currency="USD",
        attribution_window="7d_click",
        campaign_id=campaign_id,
        ad_set_id=ad_set_id,
        ad_id=ad_id,
        creative_id=creative_id,
        audience_id=audience_id,
        date_start=day,
        date_stop=day,
        dimensions=dimensions,
        metrics=build_metrics(
            spend=Decimal(spend),
            impressions=Decimal(impressions),
            reach=Decimal(reach),
            clicks=Decimal(clicks),
            link_clicks=Decimal(link_clicks),
            conversions=Decimal(conversions),
            leads=Decimal(leads),
            revenue=Decimal(revenue),
        ),
    )


def _states_from_snapshot(snapshot: AdsSnapshot) -> dict[str, ProviderObjectState]:
    states: dict[str, ProviderObjectState] = {}
    for entity in [*snapshot.campaigns, *snapshot.ad_sets, *snapshot.ads]:
        states[entity.provider_id] = _state(
            provider=snapshot.provider,
            object_type=entity.entity_type,
            provider_object_id=entity.provider_id,
            status=entity.status,
            daily_budget=entity.daily_budget,
            currency=entity.currency,
            updated_at=entity.updated_at,
        )
    for audience in snapshot.audiences:
        states[audience.provider_id] = _state(
            provider=snapshot.provider,
            object_type=AdEntityType.AUDIENCE,
            provider_object_id=audience.provider_id,
            status=audience.status,
            daily_budget=None,
            currency=None,
            updated_at=None,
        )
    return states


def _apply_parameters(
    current: ProviderObjectState,
    parameters: ActionParameters,
    now: datetime,
) -> ProviderObjectState:
    if isinstance(parameters, BudgetActionParameters):
        return _state(
            provider=current.provider,
            object_type=current.object_type,
            provider_object_id=current.provider_object_id,
            status=current.status,
            daily_budget=parameters.proposed_daily_budget,
            currency=parameters.currency,
            updated_at=now,
        )
    if isinstance(parameters, StatusActionParameters):
        return _state(
            provider=current.provider,
            object_type=current.object_type,
            provider_object_id=current.provider_object_id,
            status=parameters.proposed_status,
            daily_budget=current.daily_budget,
            currency=current.currency,
            updated_at=now,
        )
    if isinstance(parameters, AudienceActionParameters):
        budget = current.daily_budget
        if parameters.budget_change is not None:
            budget = parameters.budget_change.proposed_daily_budget
        return _state(
            provider=current.provider,
            object_type=current.object_type,
            provider_object_id=current.provider_object_id,
            status=parameters.proposed_status,
            daily_budget=budget,
            currency=current.currency,
            updated_at=now,
        )
    if parameters.kind in {ActionType.MAINTAIN, ActionType.OBSERVE, ActionType.PROPOSE_TEST}:
        raise ValueError(f"Action {parameters.kind.value!r} is not executable")
    raise TypeError("Unsupported typed action parameters")


def _update_snapshot_entity(
    snapshot: AdsSnapshot,
    state: ProviderObjectState,
) -> AdsSnapshot:
    def update(entities: list[AdEntity]) -> list[AdEntity]:
        return [
            entity.model_copy(
                update={
                    "status": state.status,
                    "effective_status": state.status,
                    "daily_budget": state.daily_budget,
                    "updated_at": state.updated_at,
                },
            )
            if entity.provider_id == state.provider_object_id
            else entity
            for entity in entities
        ]

    return snapshot.model_copy(
        update={
            "campaigns": update(snapshot.campaigns),
            "ad_sets": update(snapshot.ad_sets),
            "ads": update(snapshot.ads),
        },
    )


def _state(
    *,
    provider: str,
    object_type: AdEntityType,
    provider_object_id: str,
    status: str,
    daily_budget: Decimal | None,
    currency: str | None,
    updated_at: datetime | None,
) -> ProviderObjectState:
    safe: dict[str, JsonValue] = {
        "id": provider_object_id,
        "status": status,
        "daily_budget": str(daily_budget) if daily_budget is not None else None,
        "currency": currency,
    }
    serialized = json.dumps(safe, sort_keys=True, separators=(",", ":"))
    return ProviderObjectState(
        provider=provider,
        object_type=object_type,
        provider_object_id=provider_object_id,
        status=status,
        daily_budget=daily_budget,
        currency=currency,
        updated_at=updated_at,
        state_hash=hashlib.sha256(serialized.encode()).hexdigest(),
        raw_safe=safe,
    )
