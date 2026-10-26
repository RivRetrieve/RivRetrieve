"""Normalize official response rows without selecting preferred source variants."""

import json
from datetime import UTC, datetime
from math import isfinite

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.ch_foen.official_config import OfficialRoute
from rivretrieve._internal.providers.ch_foen.official_series import source_series
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


def _parse(payload: Payload, config: ProviderConfig) -> ParsedSeries:
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, OfficialRoute) or len(payload.station_products) != 1:
        raise FatalContractError("Official Swiss payload requires one station and route")
    station, product = payload.station_products[0]
    if product not in config.products or config.products[product].coordinates.value != coordinates:
        raise FatalContractError("Official Swiss payload contradicts configured route coordinates")
    try:
        document = json.loads(payload.content)
        records = document["data"]["water"]["observations"][coordinates.route]
    except (ValueError, UnicodeDecodeError, KeyError, TypeError) as error:
        raise UnsupportedSourceStructureError("Official Swiss response envelope is invalid") from error
    if not isinstance(records, list) or document.get("errors"):
        raise UnsupportedSourceStructureError("Official Swiss response does not contain successful rows")
    recent = coordinates.route == "data_live"
    evidence = f"source-call:{payload.acquisition_id}"
    groups = {}
    for record in records:
        if not isinstance(record, dict):
            raise UnsupportedSourceStructureError("Official Swiss observation must be an object")
        station_record = record.get("station")
        if not recent and not isinstance(station_record, dict):
            raise UnsupportedSourceStructureError("Official Swiss archive station must be an object")
        observed_station = record.get("stationNo") if recent else station_record.get("no")
        if observed_station != station or record.get("parameterName") != coordinates.parameter:
            raise UnsupportedSourceStructureError("Official Swiss observation contradicts requested coordinates")
        name = None if recent else record.get("tsName")
        if not recent and (not isinstance(name, str) or not name):
            raise UnsupportedSourceStructureError("Official Swiss archive observation lacks its source name")
        groups.setdefault(name, []).append(record)
    definitions = []
    rows = []
    outcomes = []
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    known = {
        item.variant: item for item in payload.known_series if item.station_id == station and item.product_id == product
    }
    for name in dict.fromkeys((*groups, *known)):
        entries = groups.get(name, [])
        if recent:
            candidate = known.get(name)
            units = tuple(dict.fromkeys(fact.source_unit.value for fact in candidate.facts)) if candidate else (None,)
            if len(units) != 1:
                raise UnsupportedSourceStructureError("Recent source unit binding is ambiguous")
        else:
            units = tuple(dict.fromkeys(entry.get("unitSymbol") for entry in entries))
            if not units and name in known:
                units = tuple(fact.source_unit.value for fact in known[name].facts)
            if any(not isinstance(unit, str) or not unit for unit in units):
                raise UnsupportedSourceStructureError("Official Swiss archive observation lacks a unit")
        definition = source_series(
            station,
            coordinates.route,
            coordinates.parameter,
            name,
            units=units,
            evidence=evidence,
            temporal_evidence="catalogue:ch_foen:source.product.temporal_meaning",
            origin="response",
        )
        candidate = known.get(name)
        if candidate is not None:
            retained = {fact.source_unit.value: fact for fact in candidate.facts}
            definition = definition.model_copy(
                update={
                    "facts": tuple(retained.get(fact.source_unit.value, fact) for fact in definition.facts),
                }
            )
        definitions.append(definition)
        for fact in definition.facts:
            decision = admission(fact)
            selected = (
                entries if recent else [entry for entry in entries if entry["unitSymbol"] == fact.source_unit.value]
            )
            native = []
            if decision.status == "supported":
                for entry in selected:
                    label = entry.get("timestamp")
                    if not isinstance(label, str):
                        raise UnsupportedSourceStructureError("Official Swiss timestamp must be explicit UTC")
                    try:
                        timestamp = datetime.fromisoformat(label)
                    except ValueError as error:
                        raise UnsupportedSourceStructureError("Official Swiss timestamp is invalid") from error
                    if timestamp.tzinfo is None or timestamp.utcoffset() != UTC.utcoffset(timestamp):
                        raise UnsupportedSourceStructureError("Official Swiss timestamp must be explicit UTC")
                    timestamp = timestamp.replace(tzinfo=None)
                    value = entry.get("value")
                    if "value" not in entry or (
                        value is not None and (type(value) not in (int, float) or not isfinite(value))
                    ):
                        raise UnsupportedSourceStructureError("Official Swiss observation must be numeric or null")
                    native.append(
                        {
                            "station_id": station,
                            "product_id": product,
                            "time": timestamp,
                            "value": value,
                            "time_zone": "+00:00",
                            "series_id": definition.series_id,
                            "facts_id": fact.facts_id,
                            "source_unit": fact.source_unit.value,
                        }
                    )
                rows.extend(native)
            status = (
                OutcomeStatus.UNSUPPORTED
                if decision.status != "supported"
                else OutcomeStatus.UNRESOLVED
                if recent and not native
                else OutcomeStatus.SUCCESS
                if native
                else OutcomeStatus.EMPTY
            )
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id),
                    series_id=definition.series_id,
                    station_id=station,
                    product_id=product,
                    window=window,
                    facts_ids=(fact.facts_id,),
                    status=status,
                    reason="Recent response does not establish retention or empty interval coverage"
                    if status is OutcomeStatus.UNRESOLVED
                    else "Source unit is not established"
                    if status is OutcomeStatus.UNSUPPORTED
                    else None,
                    retrieved_at=retrieved,
                    coverage="observations" if recent else "interval",
                    observation_keys=tuple(dict.fromkeys((fact.facts_id, row["time"], "+00:00") for row in native))
                    if recent
                    else (),
                )
            )
    if not definitions:
        outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(payload.acquisition_id, "unresolved"),
                series_id=None,
                station_id=station,
                product_id=product,
                window=window,
                status=OutcomeStatus.UNRESOLVED,
                reason="Successful empty response establishes no concrete source-series identity",
                retrieved_at=retrieved,
            )
        )
    scope = payload.scope or SeriesScope(provider_ids=("ch_foen",), station_ids=(station,), product_ids=(product,))
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, "inventory"),
        scope=scope,
        members=tuple(item.series_id for item in definitions),
        completeness=InventoryCompleteness.INCOMPLETE,
        access=coordinates.route,
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
        reason="Returned series establish this response, not an exhaustive historical inventory",
    )
    return ParsedSeries(
        pl.DataFrame(rows, schema=RowsSchema.polars_schema), tuple(definitions), (inventory,), tuple(outcomes)
    )


def parse(payload: Payload, config: ProviderConfig) -> ParsedSeries:
    """Preserve unsupported source responses as bounded failures, not lost siblings."""
    try:
        return _parse(payload, config)
    except UnsupportedSourceStructureError as error:
        station, product = payload.station_products[0]
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
            reason=str(error),
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), (outcome,))
