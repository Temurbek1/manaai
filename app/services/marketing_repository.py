import asyncio
import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from app.schemas.marketing import (
    RAW_FILTER_KEY_PATTERN,
    MarketingAnalysisReport,
    MarketingAnalysisReportSummary,
    MarketingAnalysisRequest,
    MarketingAnalysisResponse,
    MarketingEntityType,
    MarketingGraphResponse,
    MarketingKpiSummary,
    RawMarketingRecord,
    RawMarketingRecordInput,
)


class MarketingRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def insert_raw_records(
        self,
        records: Sequence[RawMarketingRecordInput],
    ) -> list[RawMarketingRecord]:
        return await asyncio.to_thread(self._insert_raw_records_sync, records)

    async def list_raw_records(
        self,
        *,
        account_ids: Sequence[str] | None = None,
        entity_types: Sequence[MarketingEntityType] | None = None,
        provider_record_ids: Sequence[str] | None = None,
        date_start: date | None = None,
        date_stop: date | None = None,
        payload_filters: Mapping[str, str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[RawMarketingRecord], int]:
        return await asyncio.to_thread(
            self._list_raw_records_sync,
            account_ids,
            entity_types,
            provider_record_ids,
            date_start,
            date_stop,
            payload_filters,
            limit,
            offset,
        )

    async def get_raw_records_by_ids(
        self,
        record_ids: Sequence[str],
    ) -> list[RawMarketingRecord]:
        return await asyncio.to_thread(self._get_raw_records_by_ids_sync, record_ids)

    async def save_analysis_report(
        self,
        *,
        request: MarketingAnalysisRequest,
        response: MarketingAnalysisResponse,
    ) -> None:
        await asyncio.to_thread(self._save_analysis_report_sync, request, response)

    async def list_analysis_reports(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[MarketingAnalysisReportSummary], int]:
        return await asyncio.to_thread(self._list_analysis_reports_sync, limit, offset)

    async def get_analysis_report(self, report_id: str) -> MarketingAnalysisResponse | None:
        return await asyncio.to_thread(self._get_analysis_report_sync, report_id)

    def _initialize_sync(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS marketing_raw_records (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    provider_record_id TEXT,
                    account_id TEXT,
                    parent_id TEXT,
                    observed_at TEXT,
                    collected_at TEXT NOT NULL,
                    api_version TEXT,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_marketing_raw_entity
                    ON marketing_raw_records(entity_type);
                CREATE INDEX IF NOT EXISTS idx_marketing_raw_account
                    ON marketing_raw_records(account_id);
                CREATE INDEX IF NOT EXISTS idx_marketing_raw_observed
                    ON marketing_raw_records(observed_at);

                CREATE TABLE IF NOT EXISTS marketing_analysis_reports (
                    id TEXT PRIMARY KEY,
                    generated_at TEXT NOT NULL,
                    model TEXT NOT NULL,
                    source_record_count INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    kpi_json TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    source_record_ids_json TEXT NOT NULL,
                    response_json TEXT
                );
                """
            )
            self._ensure_analysis_report_columns(connection)

    def _insert_raw_records_sync(
        self,
        records: Sequence[RawMarketingRecordInput],
    ) -> list[RawMarketingRecord]:
        inserted: list[RawMarketingRecord] = []
        collected_at = datetime.now(UTC)

        with self._connect() as connection:
            for record in records:
                payload_json = _json_dumps(record.payload)
                raw_record = RawMarketingRecord(
                    id=str(uuid.uuid4()),
                    source=record.source,
                    entity_type=record.entity_type,
                    provider_record_id=record.provider_record_id,
                    account_id=record.account_id,
                    parent_id=record.parent_id,
                    observed_at=record.observed_at,
                    collected_at=collected_at,
                    api_version=record.api_version,
                    payload_hash=hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                    payload=record.payload,
                )
                connection.execute(
                    """
                    INSERT INTO marketing_raw_records (
                        id,
                        source,
                        entity_type,
                        provider_record_id,
                        account_id,
                        parent_id,
                        observed_at,
                        collected_at,
                        api_version,
                        payload_hash,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        raw_record.id,
                        raw_record.source,
                        raw_record.entity_type,
                        raw_record.provider_record_id,
                        raw_record.account_id,
                        raw_record.parent_id,
                        _datetime_to_db(raw_record.observed_at),
                        _datetime_to_db(raw_record.collected_at),
                        raw_record.api_version,
                        raw_record.payload_hash,
                        payload_json,
                    ),
                )
                inserted.append(raw_record)

        return inserted

    def _list_raw_records_sync(
        self,
        account_ids: Sequence[str] | None,
        entity_types: Sequence[MarketingEntityType] | None,
        provider_record_ids: Sequence[str] | None,
        date_start: date | None,
        date_stop: date | None,
        payload_filters: Mapping[str, str] | None,
        limit: int,
        offset: int,
    ) -> tuple[list[RawMarketingRecord], int]:
        where_clauses: list[str] = []
        values: list[str | int] = []

        if account_ids:
            where_clauses.append(f"account_id IN ({_placeholders(len(account_ids))})")
            values.extend(account_ids)

        if entity_types:
            where_clauses.append(f"entity_type IN ({_placeholders(len(entity_types))})")
            values.extend(entity_types)

        if provider_record_ids:
            where_clauses.append(
                f"provider_record_id IN ({_placeholders(len(provider_record_ids))})",
            )
            values.extend(provider_record_ids)

        if date_start is not None:
            where_clauses.append("observed_at >= ?")
            values.append(_date_start_to_db(date_start))

        if date_stop is not None:
            where_clauses.append("observed_at <= ?")
            values.append(_date_stop_to_db(date_stop))

        for key, expected_value in sorted((payload_filters or {}).items()):
            _validate_payload_filter_key(key)
            where_clauses.append("CAST(json_extract(payload_json, ?) AS TEXT) = ?")
            values.extend([f"$.{key}", expected_value])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        with self._connect() as connection:
            count_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM marketing_raw_records {where_sql}",
                values,
            ).fetchone()
            total = int(cast(sqlite3.Row, count_row)["total"])

            rows = connection.execute(
                f"""
                SELECT *
                FROM marketing_raw_records
                {where_sql}
                ORDER BY collected_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*values, limit, offset],
            ).fetchall()

        return [_raw_record_from_row(row) for row in rows], total

    def _get_raw_records_by_ids_sync(
        self,
        record_ids: Sequence[str],
    ) -> list[RawMarketingRecord]:
        ordered_ids = _unique_ordered(record_ids)
        if not ordered_ids:
            return []

        records_by_id: dict[str, RawMarketingRecord] = {}
        with self._connect() as connection:
            for chunk in _chunks(ordered_ids, size=500):
                rows = connection.execute(
                    f"""
                    SELECT *
                    FROM marketing_raw_records
                    WHERE id IN ({_placeholders(len(chunk))})
                    """,
                    chunk,
                ).fetchall()
                for row in rows:
                    raw_record = _raw_record_from_row(row)
                    records_by_id[raw_record.id] = raw_record

        return [records_by_id[record_id] for record_id in ordered_ids if record_id in records_by_id]

    def _save_analysis_report_sync(
        self,
        request: MarketingAnalysisRequest,
        response: MarketingAnalysisResponse,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO marketing_analysis_reports (
                    id,
                    generated_at,
                    model,
                    source_record_count,
                    request_json,
                    kpi_json,
                    report_json,
                    source_record_ids_json,
                    response_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    response.report_id,
                    _datetime_to_db(response.generated_at),
                    response.model,
                    response.source_record_count,
                    request.model_dump_json(),
                    response.kpi_summary.model_dump_json(),
                    response.report.model_dump_json(),
                    _json_dumps(response.source_record_ids),
                    response.model_dump_json(),
                ),
            )

    def _list_analysis_reports_sync(
        self,
        limit: int,
        offset: int,
    ) -> tuple[list[MarketingAnalysisReportSummary], int]:
        with self._connect() as connection:
            count_row = connection.execute(
                "SELECT COUNT(*) AS total FROM marketing_analysis_reports",
            ).fetchone()
            total = int(cast(sqlite3.Row, count_row)["total"])
            rows = connection.execute(
                """
                SELECT id, generated_at, model, source_record_count
                FROM marketing_analysis_reports
                ORDER BY generated_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        return [_analysis_report_summary_from_row(row) for row in rows], total

    def _get_analysis_report_sync(self, report_id: str) -> MarketingAnalysisResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    generated_at,
                    model,
                    source_record_count,
                    kpi_json,
                    report_json,
                    source_record_ids_json,
                    response_json
                FROM marketing_analysis_reports
                WHERE id = ?
                """,
                (report_id,),
            ).fetchone()

        if row is None:
            return None

        return _analysis_response_from_report_row(cast(sqlite3.Row, row))

    def _ensure_analysis_report_columns(self, connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(marketing_analysis_reports)")
        }
        if "response_json" not in columns:
            connection.execute(
                "ALTER TABLE marketing_analysis_reports ADD COLUMN response_json TEXT",
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _analysis_response_from_report_row(row: sqlite3.Row) -> MarketingAnalysisResponse:
    response_json = _optional_str(row["response_json"])
    if response_json is not None:
        return MarketingAnalysisResponse.model_validate_json(response_json)

    generated_at = _datetime_from_db(str(row["generated_at"])) or datetime.now(UTC)
    source_record_count = int(row["source_record_count"])
    return MarketingAnalysisResponse(
        report_id=str(row["id"]),
        generated_at=generated_at,
        model=str(row["model"]),
        source_record_count=source_record_count,
        source_record_ids=cast(list[str], json.loads(str(row["source_record_ids_json"]))),
        kpi_summary=MarketingKpiSummary.model_validate_json(str(row["kpi_json"])),
        kpis=[],
        patterns=[],
        graph=MarketingGraphResponse(
            generated_at=generated_at,
            source_record_count=source_record_count,
            nodes=[],
            edges=[],
        ),
        report=MarketingAnalysisReport.model_validate_json(str(row["report_json"])),
    )


def _analysis_report_summary_from_row(row: sqlite3.Row) -> MarketingAnalysisReportSummary:
    return MarketingAnalysisReportSummary(
        report_id=str(row["id"]),
        generated_at=_datetime_from_db(str(row["generated_at"])) or datetime.now(UTC),
        model=str(row["model"]),
        source_record_count=int(row["source_record_count"]),
    )


def _raw_record_from_row(row: sqlite3.Row) -> RawMarketingRecord:
    payload = cast(dict[str, JsonValue], json.loads(str(row["payload_json"])))
    return RawMarketingRecord(
        id=str(row["id"]),
        source=cast(str, row["source"]),
        entity_type=cast(MarketingEntityType, row["entity_type"]),
        provider_record_id=_optional_str(row["provider_record_id"]),
        account_id=_optional_str(row["account_id"]),
        parent_id=_optional_str(row["parent_id"]),
        observed_at=_datetime_from_db(_optional_str(row["observed_at"])),
        collected_at=_datetime_from_db(str(row["collected_at"])) or datetime.now(UTC),
        api_version=_optional_str(row["api_version"]),
        payload_hash=str(row["payload_hash"]),
        payload=payload,
    )


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _datetime_to_db(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_from_db(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _date_start_to_db(value: date) -> str:
    return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()


def _date_stop_to_db(value: date) -> str:
    return datetime.combine(value, datetime.max.time(), tzinfo=UTC).isoformat()


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _validate_payload_filter_key(key: str) -> None:
    if RAW_FILTER_KEY_PATTERN.fullmatch(key) is None:
        raise ValueError("Payload filter keys must be top-level JSON field names")


def _placeholders(count: int) -> str:
    return ",".join("?" for _ in range(count))


def _unique_ordered(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _chunks(values: Sequence[str], *, size: int) -> list[list[str]]:
    return [list(values[index : index + size]) for index in range(0, len(values), size)]
