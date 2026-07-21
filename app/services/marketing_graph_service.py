from datetime import UTC, datetime
from typing import cast

from pydantic import JsonValue

from app.schemas.marketing import (
    MarketingEntityType,
    MarketingGraphEdge,
    MarketingGraphEdgeType,
    MarketingGraphNode,
    MarketingGraphRequest,
    MarketingGraphResponse,
    RawMarketingRecord,
)
from app.services.marketing_repository import MarketingRepository


class MarketingGraphService:
    def __init__(self, *, repository: MarketingRepository) -> None:
        self._repository = repository

    async def build(self, request: MarketingGraphRequest) -> MarketingGraphResponse:
        entity_types = request.entity_types
        if entity_types is None and not request.include_insights:
            entity_types = ["app", "business", "ad_account", "campaign", "adset", "ad", "creative"]

        records, _ = await self._repository.list_raw_records(
            account_ids=request.account_ids,
            entity_types=entity_types,
            date_start=request.date_start,
            date_stop=request.date_stop,
            limit=request.max_records,
            offset=0,
        )
        if not request.include_insights:
            records = [record for record in records if record.entity_type != "insight"]

        builder = _MarketingGraphBuilder()
        for record in records:
            builder.add_record(record)

        return MarketingGraphResponse(
            generated_at=datetime.now(UTC),
            source_record_count=len(records),
            nodes=builder.nodes(),
            edges=builder.edges(),
        )


class _MarketingGraphBuilder:
    def __init__(self) -> None:
        self._nodes: dict[str, MarketingGraphNode] = {}
        self._edges: dict[tuple[str, str, MarketingGraphEdgeType], MarketingGraphEdge] = {}

    def add_record(self, record: RawMarketingRecord) -> None:
        node_id = _node_id(record.entity_type, _record_entity_id(record))
        self._upsert_node(
            node_id=node_id,
            node_type=record.entity_type,
            label=_record_label(record),
            provider_record_id=record.provider_record_id,
            account_id=record.account_id,
            record_id=record.id,
            attributes=_record_attributes(record),
        )

        if record.account_id and record.entity_type not in {"ad_account", "app", "business"}:
            account_node_id = _node_id("ad_account", record.account_id)
            self._upsert_node(
                node_id=account_node_id,
                node_type="ad_account",
                label=record.account_id,
                provider_record_id=record.account_id,
                account_id=record.account_id,
                record_id=record.id,
                attributes={},
            )
            self._upsert_edge(
                source_id=account_node_id,
                target_id=node_id,
                edge_type="contains" if record.entity_type != "insight" else "reports",
                record_id=record.id,
            )

        self._add_known_parent_edges(record=record, node_id=node_id)

    def nodes(self) -> list[MarketingGraphNode]:
        return sorted(self._nodes.values(), key=lambda node: (node.type, node.label, node.id))

    def edges(self) -> list[MarketingGraphEdge]:
        return sorted(
            self._edges.values(),
            key=lambda edge: (edge.type, edge.source_id, edge.target_id),
        )

    def _add_known_parent_edges(self, *, record: RawMarketingRecord, node_id: str) -> None:
        payload = record.payload

        if record.entity_type == "ad_account":
            business_id = _nested_id(payload.get("business"))
            if business_id:
                business_node_id = _node_id("business", business_id)
                self._upsert_node(
                    node_id=business_node_id,
                    node_type="business",
                    label=business_id,
                    provider_record_id=business_id,
                    account_id=None,
                    record_id=record.id,
                    attributes={},
                )
                self._upsert_edge(
                    source_id=business_node_id,
                    target_id=node_id,
                    edge_type="owns",
                    record_id=record.id,
                )

        if record.entity_type == "adset":
            campaign_id = _json_str(payload.get("campaign_id")) or record.parent_id
            if campaign_id:
                self._edge_from_parent(
                    parent_type="campaign",
                    parent_id=campaign_id,
                    child_id=node_id,
                    record=record,
                    edge_type="contains",
                )

        if record.entity_type == "ad":
            adset_id = _json_str(payload.get("adset_id")) or record.parent_id
            campaign_id = _json_str(payload.get("campaign_id"))
            if adset_id:
                self._edge_from_parent(
                    parent_type="adset",
                    parent_id=adset_id,
                    child_id=node_id,
                    record=record,
                    edge_type="contains",
                )
            elif campaign_id:
                self._edge_from_parent(
                    parent_type="campaign",
                    parent_id=campaign_id,
                    child_id=node_id,
                    record=record,
                    edge_type="contains",
                )

            creative_id = _nested_id(payload.get("creative"))
            if creative_id:
                creative_node_id = _node_id("creative", creative_id)
                self._upsert_node(
                    node_id=creative_node_id,
                    node_type="creative",
                    label=creative_id,
                    provider_record_id=creative_id,
                    account_id=record.account_id,
                    record_id=record.id,
                    attributes={},
                )
                self._upsert_edge(
                    source_id=node_id,
                    target_id=creative_node_id,
                    edge_type="created_from",
                    record_id=record.id,
                )

        if record.entity_type == "insight":
            parent = _insight_parent(payload)
            if parent is not None:
                parent_type, parent_id = parent
                self._edge_from_parent(
                    parent_type=parent_type,
                    parent_id=parent_id,
                    child_id=node_id,
                    record=record,
                    edge_type="measures",
                )

    def _edge_from_parent(
        self,
        *,
        parent_type: MarketingEntityType,
        parent_id: str,
        child_id: str,
        record: RawMarketingRecord,
        edge_type: MarketingGraphEdgeType,
    ) -> None:
        parent_node_id = _node_id(parent_type, parent_id)
        self._upsert_node(
            node_id=parent_node_id,
            node_type=parent_type,
            label=parent_id,
            provider_record_id=parent_id,
            account_id=record.account_id,
            record_id=record.id,
            attributes={},
        )
        self._upsert_edge(
            source_id=parent_node_id,
            target_id=child_id,
            edge_type=edge_type,
            record_id=record.id,
        )

    def _upsert_node(
        self,
        *,
        node_id: str,
        node_type: MarketingEntityType | str,
        label: str,
        provider_record_id: str | None,
        account_id: str | None,
        record_id: str,
        attributes: dict[str, JsonValue],
    ) -> None:
        existing = self._nodes.get(node_id)
        if existing is None:
            self._nodes[node_id] = MarketingGraphNode(
                id=node_id,
                type=node_type,
                label=label,
                provider_record_id=provider_record_id,
                account_id=account_id,
                source_record_ids=[record_id],
                attributes=attributes,
            )
            return

        if record_id not in existing.source_record_ids:
            existing.source_record_ids.append(record_id)
        if not existing.attributes and attributes:
            existing.attributes.update(attributes)

    def _upsert_edge(
        self,
        *,
        source_id: str,
        target_id: str,
        edge_type: MarketingGraphEdgeType,
        record_id: str,
    ) -> None:
        key = (source_id, target_id, edge_type)
        existing = self._edges.get(key)
        if existing is None:
            self._edges[key] = MarketingGraphEdge(
                source_id=source_id,
                target_id=target_id,
                type=edge_type,
                source_record_ids=[record_id],
            )
            return

        if record_id not in existing.source_record_ids:
            existing.source_record_ids.append(record_id)


def _record_entity_id(record: RawMarketingRecord) -> str:
    return record.provider_record_id or _payload_id(record.payload) or record.id


def _record_label(record: RawMarketingRecord) -> str:
    name = _json_str(record.payload.get("name")) or _entity_name(record.payload)
    return name or record.provider_record_id or record.id


def _record_attributes(record: RawMarketingRecord) -> dict[str, JsonValue]:
    keys = [
        "status",
        "effective_status",
        "objective",
        "optimization_goal",
        "billing_event",
        "currency",
        "timezone_name",
        "date_start",
        "date_stop",
        "title",
        "body",
        "object_type",
        "object_url",
        "call_to_action_type",
        "thumbnail_url",
        "image_url",
        "object_story_id",
        "effective_object_story_id",
        "object_story_spec",
        "asset_feed_spec",
        "instagram_permalink_url",
    ]
    return {key: value for key in keys if (value := record.payload.get(key)) is not None}


def _node_id(entity_type: str, provider_id: str) -> str:
    return f"{entity_type}:{provider_id}"


def _payload_id(payload: dict[str, JsonValue]) -> str | None:
    return _json_str(payload.get("id"))


def _entity_name(payload: dict[str, JsonValue]) -> str | None:
    for key in ("ad_name", "adset_name", "campaign_name", "account_name"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _insight_parent(payload: dict[str, JsonValue]) -> tuple[MarketingEntityType, str] | None:
    for entity_type, key in [
        ("ad", "ad_id"),
        ("adset", "adset_id"),
        ("campaign", "campaign_id"),
        ("ad_account", "account_id"),
    ]:
        value = _json_str(payload.get(key))
        if value:
            return cast(MarketingEntityType, entity_type), value
    return None


def _nested_id(value: JsonValue | None) -> str | None:
    if isinstance(value, dict):
        nested = value.get("id")
        return str(nested) if nested is not None else None
    return None


def _json_str(value: JsonValue | None) -> str | None:
    return str(value) if value is not None else None
