"""ca_eccc fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]]."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceCallOrigin,
    SourceQuery,
    UnknownOriginFact,
    WithIssues,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ca_eccc.config import HydatSourceCoordinates
from rivretrieve._internal.providers.ca_eccc.issue_codes import CaEcccObservationIssueCodes
from rivretrieve._internal.providers.ca_eccc.observation_client import _find_sqlite, default_cache_dir
from rivretrieve._internal.transport import Transport

PROVIDER_ID = ProviderId("ca_eccc")


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport | None = None,
) -> WithIssues[tuple[Payload, ...]]:
    del transport
    cache_dir = default_cache_dir()
    sqlite_path = _find_sqlite(cache_dir)
    if sqlite_path is None or not sqlite_path.is_file():
        return WithIssues(
            value=(),
            issues=(
                Issue(
                    severity="error",
                    code=CaEcccObservationIssueCodes.HYDAT_NOT_AVAILABLE,
                    message="The cached HYDAT SQLite database does not exist.",
                    details={"cache_dir": str(cache_dir)},
                    provider_id=PROVIDER_ID,
                ),
            ),
        )

    try:
        connection = _open_read_only(sqlite_path)
    except (OSError, sqlite3.DatabaseError) as error:
        return WithIssues(
            value=(),
            issues=(
                Issue(
                    severity="error",
                    code=CaEcccObservationIssueCodes.SOURCE_REQUEST_FAILED,
                    message="The cached HYDAT SQLite database could not be read.",
                    details={
                        "path": str(sqlite_path),
                        "exception_type": type(error).__name__,
                    },
                    provider_id=PROVIDER_ID,
                ),
            ),
        )

    payloads: list[Payload] = []
    issues: list[Issue] = []
    try:
        for product_id in products:
            product_windows = rendered_windows[product_id]
            start_year = product_windows[0].start
            end_year = product_windows[-1].start
            product = config.products[product_id]
            coordinates = product.coordinates.value
            if not isinstance(coordinates, HydatSourceCoordinates):
                raise FatalContractError(f"CA ECCC product {product_id!r} has non-HYDAT source coordinates")
            _require_hydat_schema(connection, coordinates)

            for station_id in stations:
                rows, query = _query_station_product(
                    connection,
                    coordinates,
                    station_id,
                    start_year,
                    end_year,
                )
                if not rows:
                    issues.append(
                        Issue(
                            severity="warning",
                            code=CaEcccObservationIssueCodes.MISSING_DATA,
                            message="HYDAT has no rows for the station-product and endpoint years.",
                            details={
                                "station_id": station_id,
                                "product_id": str(product_id),
                                "table_name": coordinates.table_name,
                                "start_year": start_year,
                                "end_year": end_year,
                            },
                            provider_id=PROVIDER_ID,
                        )
                    )
                    continue

                payloads.append(
                    Payload(
                        source_coordinates=product.coordinates,
                        station_products=((station_id, product_id),),
                        fetch_window=fetch_window,
                        content=_encode_rows(rows),
                        origin=SourceCallOrigin(
                            url=UnknownOriginFact(),
                            request_parameters=UnknownOriginFact(),
                            status_code=UnknownOriginFact(),
                            retrieved_at=UnknownOriginFact(),
                            content_type="application/json",
                            source_path=str(sqlite_path.resolve()),
                            query=query,
                        ),
                    )
                )
    finally:
        connection.close()

    return WithIssues(value=tuple(payloads), issues=tuple(issues))


def _open_read_only(sqlite_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{sqlite_path.resolve().as_uri()}?mode=ro",
        uri=True,
    )
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA schema_version").fetchone()
    except BaseException:
        connection.close()
        raise
    return connection


def _require_hydat_schema(
    connection: sqlite3.Connection,
    coordinates: HydatSourceCoordinates,
) -> None:
    table_identifier = _quote_identifier(coordinates.table_name)
    columns = {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table_identifier})").fetchall()}
    if not columns:
        raise FatalContractError(f"HYDAT table {coordinates.table_name!r} does not exist")

    required = {"STATION_NUMBER", "YEAR", "MONTH", "NO_DAYS"}
    for day in range(1, 32):
        required.add(f"{coordinates.value_prefix}{day}")
        required.add(f"{coordinates.symbol_prefix}{day}")
    missing = sorted(required - columns)
    if missing:
        raise FatalContractError(f"HYDAT table {coordinates.table_name!r} lacks required columns: {missing!r}")


def _query_station_product(
    connection: sqlite3.Connection,
    coordinates: HydatSourceCoordinates,
    station_id: str,
    start_year: str,
    end_year: str,
) -> tuple[list[dict[str, object]], SourceQuery]:
    table_identifier = _quote_identifier(coordinates.table_name)
    query = SourceQuery(
        statement=(
            f"SELECT * FROM {table_identifier} WHERE STATION_NUMBER = ? AND YEAR BETWEEN ? AND ? ORDER BY YEAR, MONTH"
        ),
        parameters=(station_id, start_year, end_year),
    )
    cursor = connection.execute(query.statement, query.parameters)
    return [dict(row) for row in cursor.fetchall()], query


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    return json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
