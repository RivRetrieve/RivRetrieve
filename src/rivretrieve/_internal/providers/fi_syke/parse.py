"""Normalize SYKE Hydrologiarajapinta OData observation pages."""

from __future__ import annotations

import json
from datetime import datetime

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.fi_syke.series import describe_series
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

_PROVIDER_ID = ProviderId("fi_syke")


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
    flag_occurrences: list[tuple[datetime, int]] = []
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
        if flag_code is not None:
            if not isinstance(flag_code, int):
                raise UnsupportedSourceStructureError("fi_syke Lippu_id is not an integer")
            flag_occurrences.append((naive_time, flag_code))

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
    # Lippu is a mixed vocabulary (quality/processing, percentile, simulated-
    # value, device-id codes -- research/fi-syke-series-identity.md); record
    # each occurrence as a fact, never a ranking or exclusion (port guide
    # step 3's explicit instruction).
    issues = tuple(
        Issue(
            severity="info",
            code="source.flag_code",
            message=f"SYKE reports Lippu_id {code} for {station} {product} at {occurred_at.isoformat()}",
            details={
                "station_id": station,
                "product_id": str(product),
                "series_id": series.series_id,
                "source_flag_code": code,
                "source_time": occurred_at.isoformat(),
            },
            provider_id=_PROVIDER_ID,
        )
        for occurred_at, code in flag_occurrences
    )
    return ParsedSeries(combined, (series,), (inventory,), (outcome,), issues)
