from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import polars as pl

from rivretrieve._internal.issues import Issue, apply_on_issue
from rivretrieve._internal.observations import (
    AnnotationTable,
    ObservationProvenance,
    ObservationRequest,
    ObservationResult,
    RawPayload,
    RowAnnotationTableSchema,
    SeriesAnnotationTableSchema,
)
from rivretrieve._internal.primitives import OnIssue, ProviderId
from rivretrieve._internal.providers.ca_eccc.issue_codes import CaEcccObservationIssueCodes
from rivretrieve._internal.providers.ca_eccc.observation_client import (
    HYDAT_URL_TEMPLATE,
    HydatClient,
)
from rivretrieve._internal.providers.ca_eccc.parser import parse_hydat_rows
from rivretrieve._internal.providers.ca_eccc.transform import (
    CaEcccTransformedSeries,
    empty_data,
    empty_row_annotations,
    empty_series_annotations,
    resolve_product_policy,
    transform_series,
)

PROVIDER_ID = ProviderId("ca_eccc")


def retrieve_observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
    client_factory: Callable[[], HydatClient] = HydatClient,
    rivretrieve_version: str | None = None,
    catalogue_version: str | None = None,
) -> ObservationResult:
    requested_at = datetime.now(UTC)
    client = client_factory()
    issues: list[Issue] = []

    # --- Ensure HYDAT database is available --------------------------------
    sqlite_path, db_issues = client.ensure_database()
    issues.extend(db_issues)

    if sqlite_path is None:
        issues.append(
            _issue(
                CaEcccObservationIssueCodes.HYDAT_NOT_AVAILABLE,
                "HYDAT SQLite database is not available. Observation retrieval aborted.",
                {"cache_dir": str(client.cache_dir)},
                severity="error",
            )
        )
        result = ObservationResult(
            data=empty_data(),
            row_annotations=AnnotationTable(data=empty_row_annotations(), schema=RowAnnotationTableSchema),
            series_annotations=AnnotationTable(data=empty_series_annotations(), schema=SeriesAnnotationTableSchema),
            provenance=ObservationProvenance(
                source="local",
                provider_id=PROVIDER_ID,
                rivretrieve_version=rivretrieve_version,
                catalogue_version=catalogue_version,
                requested_at=requested_at,
                retrieved_at=None,
                request={
                    "stations": list(request.stations),
                    "products": list(request.products),
                    "start": request.start.isoformat(),
                    "end": request.end.isoformat(),
                },
                calls_made=(),
                time_windows=(),
                decomposition=("hydat_sqlite_query",),
                endpoints=(HYDAT_URL_TEMPLATE,),
            ),
            issues=tuple(issues),
            raw=None,
        )
        apply_on_issue(result.issues, on_issue)
        return result

    # HYDAT source identifier (basename only — no absolute path in provenance).
    hydat_source = sqlite_path.name

    # Load DATA_SYMBOLS once for all series.
    data_symbols = client.query_data_symbols(sqlite_path)

    start_year = request.start.year
    end_year = request.end.year

    # --- Retrieve series ---------------------------------------------------
    series_results: list[CaEcccTransformedSeries] = []

    for station_id in request.stations:
        for product_id in request.products:
            policy = resolve_product_policy(product_id)

            rows = client.query_daily_table(
                sqlite_path,
                policy.table_name,
                station_id,
                start_year,
                end_year,
            )

            parsed = parse_hydat_rows(
                rows,
                station_id=station_id,
                value_prefix=policy.value_prefix,
                symbol_prefix=policy.symbol_prefix,
            )
            issues.extend(parsed.issues)

            filtered = _filter_date_range(parsed.records, request.start, request.end)

            if not filtered.is_empty():
                transformed = transform_series(
                    filtered,
                    station_id=station_id,
                    policy=policy,
                    query_years=(start_year, end_year),
                    hydat_source=hydat_source,
                    data_symbols=data_symbols,
                )
                series_results.append(transformed)
            else:
                issues.append(
                    _issue(
                        CaEcccObservationIssueCodes.MISSING_DATA,
                        "No data in HYDAT for station/product/date range",
                        {
                            "station_id": station_id,
                            "product_id": product_id,
                            "start": request.start.isoformat(),
                            "end": request.end.isoformat(),
                        },
                    )
                )

    # --- Assemble result ---------------------------------------------------
    if series_results:
        data = pl.concat([s.data for s in series_results], how="vertical")
        row_annotations = pl.concat([s.row_annotations for s in series_results], how="vertical")
        series_annotations = pl.concat([s.series_annotations for s in series_results], how="vertical")
        issues.extend(issue for s in series_results for issue in s.issues)
    else:
        data = empty_data()
        row_annotations = empty_row_annotations()
        series_annotations = empty_series_annotations()

    data = data.sort(["station_id", "product_id", "time"]) if not data.is_empty() else data

    result = ObservationResult(
        data=data,
        row_annotations=AnnotationTable(data=row_annotations, schema=RowAnnotationTableSchema),
        series_annotations=AnnotationTable(data=series_annotations, schema=SeriesAnnotationTableSchema),
        provenance=ObservationProvenance(
            source="local",
            provider_id=PROVIDER_ID,
            rivretrieve_version=rivretrieve_version,
            catalogue_version=catalogue_version,
            requested_at=requested_at,
            retrieved_at=datetime.now(UTC),
            request={
                "stations": list(request.stations),
                "products": list(request.products),
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
            },
            calls_made=(),
            time_windows=(),
            decomposition=("hydat_sqlite_query", f"years_{start_year}_to_{end_year}"),
            endpoints=(HYDAT_URL_TEMPLATE,),
        ),
        issues=tuple(issues),
        raw=_raw_payload(sqlite_path),
    )
    apply_on_issue(result.issues, on_issue)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _filter_date_range(records: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    if records.is_empty():
        return records
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    start_day = datetime(start_utc.year, start_utc.month, start_utc.day, tzinfo=UTC)
    end_next_day = datetime(end_utc.year, end_utc.month, end_utc.day, tzinfo=UTC) + timedelta(days=1)
    return records.filter((pl.col("time") >= start_day) & (pl.col("time") < end_next_day))


def _raw_payload(sqlite_path: Path) -> RawPayload:
    import json

    return RawPayload(
        provider_id=PROVIDER_ID,
        content_type="application/vnd.rivretrieve.ca_eccc.hydat-metadata+json",
        content=None,
        metadata=json.dumps({"hydat_source": sqlite_path.name}, separators=(",", ":")),
    )


def _issue(
    code: CaEcccObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
    *,
    severity: Literal["info", "warning", "error"] = "warning",
) -> Issue:
    return Issue(severity=severity, code=str(code), message=message, details=details, provider_id=PROVIDER_ID)
