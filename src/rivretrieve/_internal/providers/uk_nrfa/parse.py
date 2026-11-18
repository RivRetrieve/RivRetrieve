"""Parse NRFA ``/time-series`` and shared ``/station-info`` payloads with bounded failures."""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.uk_nrfa.config import (
    UkNrfaPeakMetadataCoordinates,
    UkNrfaSourceCoordinates,
)
from rivretrieve._internal.providers.uk_nrfa.fetch import extract_peak_metadata_row
from rivretrieve._internal.providers.uk_nrfa.series import (
    PEAK_REJECTED_PERIOD_PRODUCTS,
    build_peak_rejection_annotations,
    decode_time_series_response,
)
from rivretrieve._internal.source_annotations import AnnotationBundle
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    stable_id,
)

_PROVIDER_ID = ProviderId("uk_nrfa")


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one NRFA peak-metadata or time-series payload into observations and annotations."""
    station, coords = _validated_payload_contract(payload, provider_config)
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
        axis=payload.acquisition_axis,
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None

    if isinstance(coords, UkNrfaPeakMetadataCoordinates):
        try:
            extract_peak_metadata_row(payload.content, station)
        except UnsupportedSourceStructureError as error:
            return _failed_parsed_series(
                payload.acquisition_id, payload.station_products, window, retrieved, str(error)
            )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ())

    _, product = payload.station_products[0]
    try:
        document = _decode_json_object(payload.content, station=station, product=product)
        defined, rows, bundle = decode_time_series_response(
            document,
            expected_station_id=station,
            expected_product_id=str(product),
        )
        if coords.peak_metadata_content is not None:
            station_row = extract_peak_metadata_row(coords.peak_metadata_content, station)
            rejection_tables = build_peak_rejection_annotations(station_row, series=(defined,))
            bundle = AnnotationBundle(
                observation_tables=bundle.observation_tables,
                series_tables={**bundle.series_tables, **rejection_tables},
            )
    except UnsupportedSourceStructureError as error:
        return _failed_parsed_series(payload.acquisition_id, payload.station_products, window, retrieved, str(error))

    facts = defined.facts[0]
    scope = payload.scope or SeriesScope(
        provider_ids=("uk_nrfa",),
        station_ids=(station,),
        product_ids=(str(product),),
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, defined.series_id, facts.facts_id, "time-series-inventory"),
        scope=scope,
        members=(defined.series_id,),
        member_facts=((defined.series_id, (facts.facts_id,)),),
        completeness=InventoryCompleteness.COMPLETE,
        access="time-series",
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(f"source-call:{payload.acquisition_id}",),
    )
    if not scope.matches(defined):
        return ParsedSeries(
            pl.DataFrame(schema=RowsSchema.polars_schema),
            (defined,),
            (inventory,),
            (),
        )

    status = OutcomeStatus.EMPTY if rows.is_empty() else OutcomeStatus.SUCCESS
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, defined.series_id, facts.facts_id, "interval"),
        series_id=defined.series_id,
        station_id=station,
        product_id=str(product),
        window=window,
        status=status,
        facts_ids=(facts.facts_id,),
        retrieved_at=retrieved,
        coverage="interval",
    )
    return ParsedSeries(
        rows,
        (defined,),
        (inventory,),
        (outcome,),
        (),
        annotations=bundle,
    )


def _validated_payload_contract(
    payload: Payload,
    provider_config: ProviderConfig,
) -> tuple[str, UkNrfaPeakMetadataCoordinates | UkNrfaSourceCoordinates]:
    if not payload.station_products:
        raise FatalContractError("uk_nrfa payload requires at least one station-product pair")
    stations = {station for station, _ in payload.station_products}
    if len(stations) != 1 or not next(iter(stations)):
        raise FatalContractError("uk_nrfa payload must identify exactly one non-empty station")
    station = next(iter(stations))

    coords = payload.source_coordinates.value
    for _, product in payload.station_products:
        if product not in provider_config.products:
            raise FatalContractError(f"uk_nrfa product is absent from provider config: {product}")

    if isinstance(coords, UkNrfaPeakMetadataCoordinates):
        if any(str(product) not in PEAK_REJECTED_PERIOD_PRODUCTS for _, product in payload.station_products):
            raise FatalContractError("uk_nrfa peak-metadata payload must target only peak products")
        return station, coords

    if isinstance(coords, UkNrfaSourceCoordinates):
        if len(payload.station_products) != 1:
            raise FatalContractError("uk_nrfa time-series payload must identify one station-product pair")
        _, product = payload.station_products[0]
        if coords.data_type != str(product):
            raise FatalContractError("uk_nrfa payload coordinates contradict configured product")
        if str(product) in PEAK_REJECTED_PERIOD_PRODUCTS and coords.peak_metadata_content is None:
            raise FatalContractError(f"uk_nrfa peak product requires peak_metadata_content: {product}")
        return station, coords

    raise FatalContractError(f"uk_nrfa payload has unsupported source coordinate type: {type(coords)!r}")


def _decode_json_object(content: bytes, *, station: str, product: ProductId) -> dict[str, object]:
    if not content:
        raise UnsupportedSourceStructureError(
            f"NRFA time-series returned empty body for station {station} product {product}"
        )
    try:
        text = content.decode("utf-8")
        document = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise UnsupportedSourceStructureError(
            f"NRFA time-series body is not valid JSON for station {station} product {product}"
        ) from exc
    if not isinstance(document, dict):
        raise UnsupportedSourceStructureError(
            f"NRFA time-series payload must be a JSON object for station {station} product {product}"
        )
    return cast("dict[str, object]", document)


def _failed_parsed_series(
    acquisition_id: str,
    station_products: tuple[tuple[str, ProductId], ...],
    window: SeriesWindow,
    retrieved: datetime | None,
    reason: str,
) -> ParsedSeries:
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []
    for station, product in station_products:
        outcome = RetrievalOutcome(
            outcome_id=stable_id(acquisition_id, station, str(product), "failed"),
            series_id=None,
            station_id=station,
            product_id=str(product),
            window=window,
            status=OutcomeStatus.FAILED,
            reason=reason,
            retrieved_at=retrieved,
        )
        outcomes.append(outcome)
        issues.append(
            Issue(
                severity="error",
                code="source.unsupported_structure",
                message=reason,
                details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
                provider_id=_PROVIDER_ID,
            )
        )
    return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), tuple(outcomes), tuple(issues))


__all__ = ("parse",)
