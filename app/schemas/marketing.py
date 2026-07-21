from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

MarketingSource = Literal["meta_marketing_api", "manual_upload"]
MarketingEntityType = Literal[
    "app",
    "business",
    "ad_account",
    "pixel",
    "custom_conversion",
    "campaign",
    "adset",
    "ad",
    "creative",
    "insight",
    "insights_job",
    "custom",
]
MetaInsightLevel = Literal["account", "campaign", "adset", "ad"]
FindingType = Literal["opportunity", "risk", "trend", "anomaly", "next_step"]
ConfidenceLevel = Literal["low", "medium", "high"]
MarketingPatternType = Literal[
    "spend_concentration",
    "wasted_spend",
    "efficiency_opportunity",
    "cost_outlier",
    "engagement_outlier",
    "trend",
    "data_quality",
]
MarketingPatternDirection = Literal["positive", "negative", "neutral"]
MarketingGraphEdgeType = Literal[
    "owns",
    "contains",
    "targets",
    "reports",
    "measures",
    "created_from",
]


def default_meta_insight_levels() -> list[MetaInsightLevel]:
    return ["campaign", "adset", "ad"]


class RawMarketingRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: MarketingSource = "manual_upload"
    entity_type: MarketingEntityType
    provider_record_id: str | None = Field(default=None, min_length=1, max_length=255)
    account_id: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: str | None = Field(default=None, min_length=1, max_length=255)
    observed_at: datetime | None = None
    api_version: str | None = Field(default=None, min_length=1, max_length=32)
    payload: dict[str, JsonValue]


class RawMarketingIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[RawMarketingRecordInput] = Field(min_length=1, max_length=500)


class RawMarketingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: MarketingSource
    entity_type: MarketingEntityType
    provider_record_id: str | None
    account_id: str | None
    parent_id: str | None
    observed_at: datetime | None
    collected_at: datetime
    api_version: str | None
    payload_hash: str
    payload: dict[str, JsonValue]


class RawMarketingIngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inserted_count: int
    record_ids: list[str]


class RawMarketingRecordListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    limit: int
    offset: int
    records: list[RawMarketingRecord]


class MetaSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    date_start: date
    date_stop: date
    account_ids: list[str] | None = Field(default=None, max_length=100)
    levels: list[MetaInsightLevel] = Field(default_factory=default_meta_insight_levels)
    include_structure: bool = True
    include_insights: bool = True

    @model_validator(mode="after")
    def validate_range(self) -> "MetaSyncRequest":
        if self.date_start > self.date_stop:
            raise ValueError("date_start must be before or equal to date_stop")
        if not self.include_structure and not self.include_insights:
            raise ValueError("at least one of include_structure or include_insights must be true")
        return self


class MetaSyncResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sync_id: str
    api_version: str
    collected_at: datetime
    account_ids: list[str]
    inserted_count: int
    records_by_entity_type: dict[str, int]
    warnings: list[str]


class MetaDiscoveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discovery_id: str
    api_version: str
    collected_at: datetime
    app_collected: bool
    ad_account_count: int
    inserted_count: int
    records_by_entity_type: dict[str, int]
    record_ids: list[str]


class MetaInsightsAsyncJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    account_id: str = Field(min_length=1, max_length=255)
    date_start: date
    date_stop: date
    level: MetaInsightLevel = "ad"
    fields: list[str] | None = Field(default=None, max_length=200)
    breakdowns: list[str] | None = Field(default=None, max_length=50)
    action_breakdowns: list[str] | None = Field(default=None, max_length=50)
    time_increment: int | Literal["all_days"] = Field(default=1)

    @model_validator(mode="after")
    def validate_range(self) -> "MetaInsightsAsyncJobRequest":
        if self.date_start > self.date_stop:
            raise ValueError("date_start must be before or equal to date_stop")
        if isinstance(self.time_increment, int) and self.time_increment < 1:
            raise ValueError("time_increment must be at least 1")
        return self


class MetaInsightsAsyncJobCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_run_id: str
    account_id: str
    level: MetaInsightLevel
    api_version: str
    raw_record_id: str | None


class MetaInsightsAsyncJobStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_run_id: str
    async_status: str | None
    async_percent_completion: int | None
    is_complete: bool
    raw_status: dict[str, JsonValue]


class MetaInsightsAsyncJobIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str | None = Field(default=None, min_length=1, max_length=255)
    level: MetaInsightLevel | None = None
    limit: int = Field(default=100, ge=1, le=500)


class MetaInsightsAsyncJobIngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_run_id: str
    inserted_count: int
    record_ids: list[str]


class MarketingIntegrationConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta_configured: bool
    meta_app_id_configured: bool
    meta_business_id_configured: bool
    meta_ad_account_ids_configured: int
    meta_graph_api_version: str
    openai_configured: bool
    openai_model: str
    raw_storage_path: str


class MarketingKpiRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    level: MetaInsightLevel | str
    entity_id: str | None
    entity_name: str | None
    account_id: str | None
    date_start: date | None
    date_stop: date | None
    spend: float
    impressions: int
    reach: int
    clicks: int
    inline_link_clicks: int
    conversions: float
    conversion_value: float
    ctr: float | None
    cpc: float | None
    cpm: float | None
    cpa: float | None
    roas: float | None


class MarketingKpiSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_spend: float
    total_impressions: int
    total_reach: int
    total_clicks: int
    total_inline_link_clicks: int
    total_conversions: float
    total_conversion_value: float
    ctr: float | None
    cpc: float | None
    cpm: float | None
    cpa: float | None
    roas: float | None


class MarketingPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: MarketingPatternType
    direction: MarketingPatternDirection
    title: str = Field(min_length=1, max_length=160)
    explanation: str = Field(min_length=1, max_length=1_200)
    entity_id: str | None
    entity_name: str | None
    level: str | None
    metric: str = Field(min_length=1, max_length=80)
    value: float | None
    benchmark: float | None
    confidence: ConfidenceLevel
    evidence_record_ids: list[str] = Field(max_length=20)
    suggested_raw_queries: list[str] = Field(max_length=8)


class MarketingPatternsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    account_ids: list[str] | None = Field(default=None, max_length=100)
    date_start: date | None = None
    date_stop: date | None = None
    max_records: int = Field(default=500, ge=1, le=5_000)
    max_patterns: int = Field(default=20, ge=1, le=100)
    min_spend: float = Field(default=1.0, ge=0.0)
    spend_concentration_threshold: float = Field(default=0.4, ge=0.05, le=1.0)
    outlier_multiplier: float = Field(default=2.0, ge=1.1, le=10.0)

    @model_validator(mode="after")
    def validate_range(self) -> "MarketingPatternsRequest":
        if (
            self.date_start is not None
            and self.date_stop is not None
            and self.date_start > self.date_stop
        ):
            raise ValueError("date_start must be before or equal to date_stop")
        return self


class MarketingPatternsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    source_record_count: int
    kpi_summary: MarketingKpiSummary
    patterns: list[MarketingPattern]


class MarketingGraphRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    account_ids: list[str] | None = Field(default=None, max_length=100)
    date_start: date | None = None
    date_stop: date | None = None
    entity_types: list[MarketingEntityType] | None = Field(default=None, max_length=20)
    include_insights: bool = True
    max_records: int = Field(default=1_000, ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_range(self) -> "MarketingGraphRequest":
        if (
            self.date_start is not None
            and self.date_stop is not None
            and self.date_start > self.date_stop
        ):
            raise ValueError("date_start must be before or equal to date_stop")
        return self


class MarketingGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: MarketingEntityType | str
    label: str
    provider_record_id: str | None
    account_id: str | None
    source_record_ids: list[str] = Field(max_length=100)
    attributes: dict[str, JsonValue]


class MarketingGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    target_id: str
    type: MarketingGraphEdgeType
    source_record_ids: list[str] = Field(max_length=100)


class MarketingGraphResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    source_record_count: int
    nodes: list[MarketingGraphNode]
    edges: list[MarketingGraphEdge]


class MarketingFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: FindingType
    title: str = Field(min_length=1, max_length=160)
    explanation: str = Field(min_length=1, max_length=1_200)
    evidence: list[str] = Field(min_length=1, max_length=8)
    confidence: ConfidenceLevel
    recommended_action: str = Field(min_length=1, max_length=800)


class MarketingAnalysisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str = Field(min_length=1, max_length=1_500)
    health_score: int = Field(ge=0, le=100)
    key_findings: list[MarketingFinding] = Field(max_length=10)
    prioritized_actions: list[str] = Field(max_length=10)
    data_quality_notes: list[str] = Field(max_length=10)
    raw_data_followups: list[str] = Field(max_length=10)


class MarketingAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    account_ids: list[str] | None = Field(default=None, max_length=100)
    date_start: date | None = None
    date_stop: date | None = None
    question: str | None = Field(default=None, min_length=1, max_length=2_000)
    max_records: int = Field(default=200, ge=1, le=2_000)
    include_raw_samples: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "MarketingAnalysisRequest":
        if (
            self.date_start is not None
            and self.date_stop is not None
            and self.date_start > self.date_stop
        ):
            raise ValueError("date_start must be before or equal to date_stop")
        return self


class MarketingAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    generated_at: datetime
    model: str
    source_record_count: int
    source_record_ids: list[str]
    kpi_summary: MarketingKpiSummary
    kpis: list[MarketingKpiRow]
    patterns: list[MarketingPattern]
    graph: MarketingGraphResponse
    report: MarketingAnalysisReport


class MarketingAnalysisReportSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    generated_at: datetime
    model: str
    source_record_count: int


class MarketingAnalysisReportListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    limit: int
    offset: int
    reports: list[MarketingAnalysisReportSummary]
