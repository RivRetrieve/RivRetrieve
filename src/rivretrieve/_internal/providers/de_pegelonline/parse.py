"""Decode one PEGELONLINE `measurements.json` response body into rows and outcomes.

Split from `fetch.py` to match every other live-`fetch`/`parse` provider in this
codebase (`ch_foen`, `lt_lhmt`, `au_bom`, etc.): `fetch.py` keeps request
construction and imports the decode functions defined here for its own
inline fetch-time interpretation, so a fresh fetch never redundantly re-decodes
its own response. `parse()` is the standalone entry point the shared engine's
`ProviderStages` protocol calls when reusing a cached or replayed payload
(`driver.py`'s `provider.parse(payload, config)`), deriving `(station, product)`
from `payload.station_products[0]` rather than taking them as separate
arguments, exactly as `ch_foen/official_parse.py`'s `_validated_route_coordinates`
does for its own single-route payloads.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.de_pegelonline.annotations import DE_PEGELONLINE_TRM_SCHEMA
from rivretrieve._internal.source_annotations import (
    OBSERVATION_STRUCTURAL_SCHEMA,
    AnnotationBundle,
    ObservationAnnotationTable,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    admission,
    stable_id,
)

# TRM and TRM_WT (and only these two) additionally publish a per-observation
# "difference" field (change from the previous day's scheduled reading),
# matching step 3's DE_PEGELONLINE_TRM_SCHEMA annotation (live-verified).
_TRM_PRODUCTS = frozenset({"TRM", "TRM_WT"})


def _numeric_or_none(entry: dict[str, object], key: str) -> float | None:
    if key not in entry:
        raise UnsupportedSourceStructureError(f"de_pegelonline observation is missing required field {key!r}")
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise UnsupportedSourceStructureError(f"de_pegelonline observation field {key!r} must be numeric or null")
    try:
        numeric = float(value)
    except OverflowError as error:
        raise UnsupportedSourceStructureError(
            f"de_pegelonline observation field {key!r} must be numeric or null"
        ) from error
    if not isfinite(numeric):
        raise UnsupportedSourceStructureError(f"de_pegelonline observation field {key!r} must be numeric or null")
    return numeric


_VALID_OFFSETS = {timedelta(hours=1): "+01:00", timedelta(hours=2): "+02:00"}


def _parse_records(payload: Payload, station: str, product: ProductId) -> ParsedSeries:
    """Interpret one station/product's pre-decoded `measurements.json` response."""
    try:
        document = json.loads(payload.content)
    except (ValueError, UnicodeDecodeError) as error:
        raise UnsupportedSourceStructureError("de_pegelonline response is not valid JSON") from error
    if not isinstance(document, list):
        raise UnsupportedSourceStructureError("de_pegelonline response is not a JSON array")
    records = cast("list[object]", document)
    del document

    matches = tuple(
        item for item in payload.known_series if item.station_id == station and item.product_id == str(product)
    )
    if len(matches) > 1:
        raise FatalContractError("de_pegelonline payload matches more than one known source series")

    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None

    if not matches:
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, "unresolved"),
            series_id=None,
            station_id=station,
            product_id=product,
            window=window,
            status=OutcomeStatus.UNRESOLVED,
            reason="No established source-series identity for this station and product",
            retrieved_at=retrieved,
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), (outcome,))

    definition = matches[0]
    if len(definition.facts) != 1:
        raise FatalContractError("de_pegelonline source series requires exactly one physical-fact segment")
    fact = definition.facts[0]
    decision = admission(fact)

    track_difference = str(product) in _TRM_PRODUCTS
    rows: list[dict[str, object]] = []
    ann_rows: list[dict[str, object]] = []
    if decision.status == "supported":
        for item in records:
            if not isinstance(item, dict):
                raise UnsupportedSourceStructureError("de_pegelonline observation must be an object")
            entry = cast("dict[str, object]", item)
            label = entry.get("timestamp")
            if not isinstance(label, str):
                raise UnsupportedSourceStructureError("de_pegelonline observation requires a string timestamp")
            try:
                timestamp = datetime.fromisoformat(label)
            except ValueError as error:
                raise UnsupportedSourceStructureError("de_pegelonline observation timestamp is invalid") from error
            offset = timestamp.utcoffset() if timestamp.tzinfo is not None else None
            time_zone = _VALID_OFFSETS.get(offset) if offset is not None else None
            if time_zone is None:
                raise UnsupportedSourceStructureError(
                    "de_pegelonline observation timestamp must carry the Europe/Berlin +01:00 or +02:00 offset"
                )
            native_time = timestamp.replace(tzinfo=None)
            value = _numeric_or_none(entry, "value")
            rows.append(
                {
                    "station_id": station,
                    "product_id": str(product),
                    "time": native_time,
                    "value": value,
                    "time_zone": time_zone,
                    "series_id": definition.series_id,
                    "facts_id": fact.facts_id,
                    "source_unit": fact.source_unit.value,
                }
            )
            if track_difference:
                difference = _numeric_or_none(entry, "difference")
                ann_rows.append(
                    {
                        "series_id": definition.series_id,
                        "facts_id": fact.facts_id,
                        "station_id": station,
                        "product_id": str(product),
                        "time": native_time,
                        "time_zone": time_zone,
                        "measured": True,
                        "difference": difference,
                    }
                )
    status = (
        OutcomeStatus.UNSUPPORTED
        if decision.status != "supported"
        else OutcomeStatus.SUCCESS
        if rows
        else OutcomeStatus.EMPTY
    )
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id),
        series_id=definition.series_id,
        station_id=station,
        product_id=product,
        window=window,
        facts_ids=(fact.facts_id,),
        status=status,
        reason=decision.reason if status is OutcomeStatus.UNSUPPORTED else None,
        retrieved_at=retrieved,
    )
    evidence = f"source-call:{payload.acquisition_id}"
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, "inventory"),
        scope=payload.scope
        or SeriesScope(provider_ids=("de_pegelonline",), station_ids=(station,), product_ids=(str(product),)),
        members=(definition.series_id,),
        completeness=InventoryCompleteness.INCOMPLETE,
        access=str(product),
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
        reason="Returned series establishes this response, not an exhaustive historical inventory",
    )
    if ann_rows:
        ann_frame = pl.DataFrame(
            ann_rows,
            schema={**OBSERVATION_STRUCTURAL_SCHEMA, **DE_PEGELONLINE_TRM_SCHEMA.polars_schema()},
        )
        ann_table = ObservationAnnotationTable.from_rows(
            schema=DE_PEGELONLINE_TRM_SCHEMA,
            rows=ann_frame,
            measurement_indices=list(range(len(rows))),
        )
        annotations = AnnotationBundle(observation_tables={DE_PEGELONLINE_TRM_SCHEMA.schema_id: ann_table})
    else:
        annotations = AnnotationBundle.empty()
    return ParsedSeries(
        pl.DataFrame(rows, schema=RowsSchema.polars_schema),
        (definition,),
        (inventory,),
        (outcome,),
        annotations=annotations,
    )


def _failed_parsed(payload: Payload, station: str, product: ProductId, reason: str) -> ParsedSeries:
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, "unsupported"),
        series_id=None,
        station_id=station,
        product_id=product,
        window=window,
        status=OutcomeStatus.FAILED,
        reason=reason,
    )
    return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), (outcome,))


def parse_records(payload: Payload, station: str, product: ProductId) -> ParsedSeries:
    """Interpret pre-decoded payload content while preserving bounded failures.

    Used by `fetch.py`'s own inline interpretation during `_acquire`, where
    `station`/`product` are already known from the request just made.
    """
    try:
        return _parse_records(payload, station, product)
    except UnsupportedSourceStructureError as error:
        return _failed_parsed(payload, station, product, str(error))


def _validated_station_product(payload: Payload, config: ProviderConfig) -> tuple[str, ProductId]:
    """Derive and validate `(station, product)` for a single-pair payload.

    Mirrors `ch_foen/official_parse.py`'s `_validated_route_coordinates`: every
    `de_pegelonline` payload carries exactly one station/product pair (one
    `measurements.json` call per station x product x window), so there is no
    group of sibling pairs to disambiguate the way a shared-acquisition
    provider would.
    """
    if len(payload.station_products) != 1:
        raise FatalContractError("de_pegelonline payload requires exactly one station and product")
    station, product = payload.station_products[0]
    coordinates = payload.source_coordinates.value
    if product not in config.products or config.products[product].coordinates.value != coordinates:
        raise FatalContractError("de_pegelonline payload contradicts configured product coordinates")
    return station, product


def parse(payload: Payload, config: ProviderConfig) -> ParsedSeries:
    """Interpret one cached or replayed `measurements.json` payload.

    Entry point for the shared engine's `ProviderStages.parse` contract. Used
    when reusing a cached/replayed payload rather than a fresh fetch-time
    interpretation (`driver.py`'s own reuse logic); a fresh `fetch()` call
    instead calls `parse_records` directly with the station/product it just
    requested, so it never redundantly re-decodes.
    """
    station, product = _validated_station_product(payload, config)
    return parse_records(payload, station, product)
