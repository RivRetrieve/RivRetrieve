"""Normalize SYKE Hydrologiarajapinta OData observation pages."""

from __future__ import annotations

import json
from datetime import datetime

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.fi_syke.annotations import FI_SYKE_OBSERVATIONS_SCHEMA
from rivretrieve._internal.providers.fi_syke.series import describe_series
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

_ANNOTATION_PRODUCTS = frozenset({"discharge_reported", "stage_reported"})
_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one SYKE observation page: at most one station-product pair."""
    if len(payload.station_products) != 1:
        raise FatalContractError("fi_syke payload must identify exactly one station-product pair")
    station, product = payload.station_products[0]

    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    scope = payload.scope or SeriesScope(provider_ids=("fi_syke",), station_ids=(station,), product_ids=(str(product),))
    evidence = f"source-call:{payload.acquisition_id}"

    try:
        document = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("fi_syke observation response is not valid JSON") from error
    if not isinstance(document, dict) or not isinstance(document.get("value"), list):
        raise UnsupportedSourceStructureError("fi_syke observation response must be a JSON object with a value array")
    rows = document["value"]

    series = describe_series(station, str(product))
    fact = series.facts[0]

    if admission(fact).status != "supported":
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, series.series_id, fact.facts_id, "unsupported"),
            series_id=series.series_id,
            station_id=station,
            product_id=str(product),
            window=window,
            status=OutcomeStatus.UNSUPPORTED,
            facts_ids=(fact.facts_id,),
            reason=f"Source unit {fact.source_unit.value!r} is not supported",
            retrieved_at=retrieved,
        )
        return ParsedSeries(
            pl.DataFrame(schema=RowsSchema.polars_schema),
            (series,),
            (
                InventorySnapshot(
                    snapshot_id=stable_id(payload.acquisition_id, series.series_id, "unsupported-inventory"),
                    scope=scope,
                    members=(series.series_id,),
                    member_facts=((series.series_id, (fact.facts_id,)),),
                    completeness=InventoryCompleteness.COMPLETE,
                    access=f"Hydrologiarajapinta/{fact.facts_id}",
                    origin="response",
                    acquired_at=retrieved,
                    window=window,
                    evidence=(evidence,),
                ),
            ),
            (outcome,),
            (),
        )

    numeric_rows: list[dict[str, object]] = []
    flag_values: list[int | None] = []
    for raw_row in rows:
        if not isinstance(raw_row, dict) or "Aika" not in raw_row or "Arvo" not in raw_row:
            raise UnsupportedSourceStructureError("fi_syke observation row lacks Aika or Arvo")
        label = raw_row["Aika"]
        if not isinstance(label, str):
            raise UnsupportedSourceStructureError("fi_syke observation timestamp is not a string")
        try:
            # Aika carries no offset (confirmed live, #755); treated as a plain
            # naive wall-clock label, time_zone stays an unestablished fact.
            naive_time = datetime.fromisoformat(label).replace(tzinfo=None)
        except ValueError as error:
            raise UnsupportedSourceStructureError(f"fi_syke malformed observation timestamp {label!r}") from error
        value = raw_row["Arvo"]
        if value is not None and not isinstance(value, (int, float, str)):
            raise UnsupportedSourceStructureError("fi_syke observation value is not numeric")
        try:
            numeric_value = float(value) if value is not None else None
        except ValueError as error:
            raise UnsupportedSourceStructureError(f"fi_syke observation value {value!r} is not numeric") from error
        numeric_rows.append(
            {
                "station_id": station,
                "product_id": str(product),
                "time": naive_time,
                "value": numeric_value,
                "time_zone": "unknown",
                "series_id": series.series_id,
                "facts_id": fact.facts_id,
                "source_unit": fact.source_unit.value,
            }
        )
        flag_code = raw_row.get("Lippu_id")
        if flag_code is not None and (
            isinstance(flag_code, bool) or not isinstance(flag_code, int) or not (_INT64_MIN <= flag_code <= _INT64_MAX)
        ):
            raise UnsupportedSourceStructureError("fi_syke Lippu_id must be a signed 64-bit integer or null")
        flag_values.append(flag_code)

    combined = (
        pl.DataFrame(numeric_rows, schema=RowsSchema.polars_schema)
        if numeric_rows
        else pl.DataFrame(schema=RowsSchema.polars_schema)
    )
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, series.series_id, fact.facts_id, "interval"),
        series_id=series.series_id,
        station_id=station,
        product_id=str(product),
        window=window,
        status=OutcomeStatus.SUCCESS if numeric_rows else OutcomeStatus.EMPTY,
        facts_ids=(fact.facts_id,),
        retrieved_at=retrieved,
        coverage="interval",
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, series.series_id, "values-inventory"),
        scope=scope,
        members=(series.series_id,),
        member_facts=((series.series_id, (fact.facts_id,)),),
        completeness=InventoryCompleteness.COMPLETE,
        access=f"Hydrologiarajapinta/{fact.facts_id}",
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
    )
    if numeric_rows and str(product) in _ANNOTATION_PRODUCTS:
        ann_frame = combined.select(
            "series_id", "facts_id", "station_id", "product_id", "time", "time_zone"
        ).with_columns(
            pl.lit(True).cast(pl.Boolean()).alias("measured"),
            pl.Series("Lippu_id", flag_values, dtype=pl.Int64()),
        )
        ann_table = ObservationAnnotationTable.from_rows(
            schema=FI_SYKE_OBSERVATIONS_SCHEMA,
            rows=ann_frame.select(*OBSERVATION_STRUCTURAL_SCHEMA, *FI_SYKE_OBSERVATIONS_SCHEMA.polars_schema()),
            measurement_indices=list(range(combined.height)),
        )
        annotations = AnnotationBundle(observation_tables={FI_SYKE_OBSERVATIONS_SCHEMA.schema_id: ann_table})
    else:
        annotations = AnnotationBundle.empty()
    return ParsedSeries(combined, (series,), (inventory,), (outcome,), (), annotations)
