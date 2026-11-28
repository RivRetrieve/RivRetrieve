"""Decode every identifiable HydAPI version with its own source physical facts.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.no_nve.annotations import NO_NVE_OBSERVATIONS_SCHEMA
from rivretrieve._internal.providers.no_nve.config import NoNveBatchCoordinates, NoNveSourceCoordinates
from rivretrieve._internal.providers.no_nve.series import NVE_EVIDENCE, describe_series
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

PROVIDER_ID = ProviderId("no_nve")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_SOURCE_ZONE = "+00:00"
_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1


class SourceStructureError(ValueError):
    """A source series cannot be decoded faithfully."""


def _decode_pair_series_blocks(
    station: str,
    product: str,
    coordinates: NoNveSourceCoordinates,
    window: SeriesWindow,
    scope: SeriesScope | None,
    content_hash: str,
    retrieved_at_origin: object,
    retrieved: datetime | None,
    raw_blocks: list[object],
    *,
    expected_versions: set[int] | None = None,
    pre_error: str | None = None,
    version_counts_by_key: dict[tuple[str, int, int], int] | None = None,
    blocks_by_key: dict[tuple[str, int, int], list[dict[str, object]]] | None = None,
) -> ParsedSeries:
    definitions = []
    rows = []
    ann_rows = []
    outcomes = []
    issues = []

    def unsupported(reason: str, definition=None) -> None:
        series_id = definition.series_id if definition else None
        facts_ids = tuple(f.facts_id for f in definition.facts) if definition else ()
        outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(
                    content_hash,
                    str(retrieved_at_origin),
                    station,
                    product,
                    series_id,
                    reason,
                    str(window),
                ),
                series_id=series_id,
                station_id=station,
                product_id=product,
                window=window,
                status=OutcomeStatus.UNSUPPORTED,
                facts_ids=facts_ids,
                reason=reason,
                retrieved_at=retrieved,
            )
        )
        issues.append(
            Issue(
                severity="warning",
                code="source.unsupported_series",
                message=reason,
                details={"station_id": station, "product_id": product, "series_id": series_id},
                provider_id=PROVIDER_ID,
            )
        )

    if pre_error is not None:
        unsupported(pre_error)
        data: list[object] = []
    else:
        data = raw_blocks

    # An observation response provides no segment identity for repeated versions.
    # Preflight the entire identity before admitting any block: equality or disjoint
    # timestamps cannot establish an undocumented concatenation/deduplication rule.
    if version_counts_by_key is None or blocks_by_key is None:
        local_counts: Counter[tuple[str, int, int]] = Counter()
        local_blocks: dict[tuple[str, int, int], list[dict[str, object]]] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            item_obj = cast("dict[str, object]", item)
            ver_val = item_obj.get("serieVersionNo")
            if (
                item_obj.get("stationId") == station
                and item_obj.get("parameter") == int(coordinates.parameter)
                and type(ver_val) is int
            ):
                key = (station, int(coordinates.parameter), ver_val)
                local_counts[key] += 1
                local_blocks.setdefault(key, []).append(item_obj)
        counts_map: Mapping[tuple[str, int, int], int] = local_counts
        repeated_map: Mapping[tuple[str, int, int], list[dict[str, object]]] = local_blocks
    else:
        counts_map = version_counts_by_key
        repeated_map = blocks_by_key

    refused_versions: set[int] = set()
    seen_versions: set[int] = set()
    for raw_entry in data:
        definition = None
        try:
            if not isinstance(raw_entry, dict):
                raise SourceStructureError("HydAPI series is not an object")
            raw = cast("dict[str, object]", raw_entry)
            if raw.get("stationId") != station:
                raise SourceStructureError("HydAPI returned station differs from requested station")
            if raw.get("parameter") != int(coordinates.parameter):
                raise SourceStructureError("HydAPI returned parameter differs from requested parameter")
            version = raw.get("serieVersionNo")
            if type(version) is not int:
                raise SourceStructureError("HydAPI series version identifier is absent or malformed")
            if expected_versions is not None:
                if version not in expected_versions:
                    raise SourceStructureError("HydAPI returned version differs from explicitly requested version")
            elif coordinates.version_number is not None and version != coordinates.version_number:
                raise SourceStructureError("HydAPI returned version differs from explicitly requested version")
            seen_versions.add(version)
            identity_key = (station, int(coordinates.parameter), version)
            if counts_map.get(identity_key, 0) > 1:
                if version in refused_versions:
                    continue
                refused_versions.add(version)
                # Retain only facts shared by every block, never first-block facts.
                repeated = repeated_map[identity_key]
                methods = [item.get("method") for item in repeated]
                units = [item.get("unit") for item in repeated]
                shared_method = (
                    methods[0] if isinstance(methods[0], str) and all(m == methods[0] for m in methods) else None
                )
                shared_unit = (
                    units[0] if isinstance(units[0], str) and units[0] and all(u == units[0] for u in units) else None
                )
                definition = describe_series(
                    station,
                    int(coordinates.parameter),
                    version,
                    int(coordinates.resolution_time),
                    shared_method,
                    shared_unit,
                )
                definitions.append(definition)
                raise SourceStructureError(
                    "HydAPI response repeats a version identity without an established segment distinction"
                )
            method = raw.get("method")
            if method is not None and not isinstance(method, str):
                raise SourceStructureError("HydAPI series method is malformed")
            unit = raw.get("unit")
            if unit == "" or (unit is not None and not isinstance(unit, str)):
                definition = describe_series(
                    station, int(coordinates.parameter), version, int(coordinates.resolution_time), method, None
                )
                definitions.append(definition)
                raise SourceStructureError(
                    "HydAPI source unit label is an empty string"
                    if unit == ""
                    else "HydAPI source unit label is malformed"
                )
            definition = describe_series(
                station, int(coordinates.parameter), version, int(coordinates.resolution_time), method, unit
            )
            definitions.append(definition)
            decision = admission(definition.facts[0])
            if decision.status != "supported":
                raise SourceStructureError(decision.reason or "HydAPI series is below admission")
            observations = _observations(raw)
            if type(raw.get("observationCount")) is not int or raw["observationCount"] != len(observations):
                raise SourceStructureError("HydAPI observationCount differs from its observations")
            native = []
            native_ann = []
            for index, observation in enumerate(observations):
                if not isinstance(observation, dict):
                    raise SourceStructureError("HydAPI observation is not an object")
                observation = cast("dict[str, object]", observation)
                label = _time(observation, index)
                quality = _code(observation, "quality", index)
                correction = _code(observation, "correction", index)
                facts = definition.facts[0]
                native.append(
                    {
                        "station_id": station,
                        "product_id": product,
                        "time": label,
                        "value": _value(observation, index),
                        "time_zone": _SOURCE_ZONE,
                        "series_id": definition.series_id,
                        "facts_id": facts.facts_id,
                        "source_unit": unit,
                    }
                )
                native_ann.append(
                    {
                        "series_id": definition.series_id,
                        "facts_id": facts.facts_id,
                        "station_id": station,
                        "product_id": product,
                        "time": label,
                        "time_zone": _SOURCE_ZONE,
                        "measured": True,
                        "quality": quality,
                        "correction": correction,
                    }
                )
            rows.extend(native)
            ann_rows.extend(native_ann)
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(
                        content_hash,
                        str(retrieved_at_origin),
                        definition.series_id,
                        str(window),
                        "response",
                    ),
                    series_id=definition.series_id,
                    station_id=station,
                    product_id=product,
                    window=window,
                    status=OutcomeStatus.SUCCESS if native else OutcomeStatus.EMPTY,
                    facts_ids=(definition.facts[0].facts_id,),
                    retrieved_at=retrieved,
                )
            )
        except SourceStructureError as exc:
            unsupported(str(exc), definition)
    if expected_versions is not None and pre_error is None:
        missing_versions = sorted(expected_versions - seen_versions)
        if not data and not outcomes:
            reason = "HydAPI response contains no concrete series identity; inventory remains unresolved"
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(
                        content_hash,
                        str(retrieved_at_origin),
                        station,
                        product,
                        str(window),
                        reason,
                    ),
                    series_id=None,
                    station_id=station,
                    product_id=product,
                    window=window,
                    status=OutcomeStatus.UNRESOLVED,
                    reason=reason,
                    retrieved_at=retrieved,
                )
            )
        elif missing_versions:
            for missing_ver in missing_versions:
                reason = "HydAPI response contains no concrete series identity; inventory remains unresolved"
                outcomes.append(
                    RetrievalOutcome(
                        outcome_id=stable_id(
                            content_hash,
                            str(retrieved_at_origin),
                            station,
                            product,
                            str(missing_ver),
                            str(window),
                            reason,
                        ),
                        series_id=None,
                        station_id=station,
                        product_id=product,
                        window=window,
                        status=OutcomeStatus.UNRESOLVED,
                        reason=reason,
                        retrieved_at=retrieved,
                    )
                )
    elif not data and not outcomes:
        reason = "HydAPI response contains no concrete series identity; inventory remains unresolved"
        outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(
                    content_hash,
                    str(retrieved_at_origin),
                    station,
                    product,
                    str(window),
                    reason,
                ),
                series_id=None,
                station_id=station,
                product_id=product,
                window=window,
                status=OutcomeStatus.UNRESOLVED,
                reason=reason,
                retrieved_at=retrieved,
            )
        )
    resolved_scope = scope or SeriesScope(provider_ids=("no_nve",), station_ids=(station,), product_ids=(product,))
    inventory = InventorySnapshot(
        snapshot_id=stable_id(
            content_hash,
            str(retrieved_at_origin),
            "no_nve",
            station,
            product,
            str(window),
            str(retrieved),
            str(coordinates.version_number),
        ),
        scope=resolved_scope,
        members=tuple(s.series_id for s in definitions),
        completeness=InventoryCompleteness.INCOMPLETE,
        access=(
            "HydAPI explicit version"
            if expected_versions is not None or coordinates.version_number is not None
            else "HydAPI source-selected version"
        ),
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(NVE_EVIDENCE,),
        reason="An observation response establishes its requested versions, not a complete current or historical version inventory",
    )
    frame = pl.DataFrame(rows, schema=RowsSchema.polars_schema)
    if rows:
        ann_frame = pl.DataFrame(
            ann_rows,
            schema={**OBSERVATION_STRUCTURAL_SCHEMA, **NO_NVE_OBSERVATIONS_SCHEMA.polars_schema()},
        )
        ann_table = ObservationAnnotationTable.from_rows(
            schema=NO_NVE_OBSERVATIONS_SCHEMA,
            rows=ann_frame,
            measurement_indices=list(range(frame.height)),
        )
        annotations = AnnotationBundle(observation_tables={NO_NVE_OBSERVATIONS_SCHEMA.schema_id: ann_table})
    else:
        annotations = AnnotationBundle.empty()
    return ParsedSeries(
        frame,
        tuple(definitions),
        (inventory,),
        tuple(outcomes),
        tuple(issues),
        annotations,
    )


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    if len(payload.station_products) != 1:
        raise FatalContractError("no_nve payload must contain exactly one station-product pair")
    station, product = payload.station_products[0]
    if product not in provider_config.products:
        raise FatalContractError("no_nve payload product is undeclared")
    coordinates = payload.source_coordinates.value
    configured = provider_config.products[product].coordinates.value
    if not isinstance(coordinates, NoNveSourceCoordinates) or not isinstance(configured, NoNveSourceCoordinates):
        raise FatalContractError("no_nve payload source coordinates have invalid type")
    if (coordinates.parameter, coordinates.resolution_time) != (configured.parameter, configured.resolution_time):
        raise FatalContractError("no_nve payload coordinates contradict product request")
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    content_hash = hashlib.sha256(payload.content).hexdigest()
    pre_error: str | None = None
    data: list[object] = []
    try:
        document = json.loads(payload.content)
        if not isinstance(document, dict) or not isinstance(document.get("data"), list):
            raise SourceStructureError("HydAPI response lacks data series array")
        data = document["data"]
    except (ValueError, UnicodeDecodeError) as exc:
        pre_error = "HydAPI response is unreadable: " + str(exc)
    return _decode_pair_series_blocks(
        station,
        product,
        coordinates,
        window,
        payload.scope,
        content_hash,
        payload.origin.retrieved_at,
        retrieved,
        data,
        pre_error=pre_error,
    )


def parse_batch_group(
    payload: Payload,
    pair_payloads: Mapping[tuple[str, ProductId], Payload],
    provider_config: ProviderConfig,
) -> Mapping[tuple[str, ProductId], ParsedSeries]:
    """Decode one shared POST /Observations payload once across all requested pairs."""
    batch_coords = payload.source_coordinates.value
    if not isinstance(batch_coords, NoNveBatchCoordinates):
        raise FatalContractError("no_nve batch payload source coordinates must be NoNveBatchCoordinates")
    expected_versions_by_pair: dict[tuple[str, ProductId], set[int]] = {}
    pair_by_key: dict[tuple[str, int, int], tuple[str, ProductId, NoNveSourceCoordinates]] = {}
    pairs_by_station_param: dict[tuple[str, int], list[tuple[str, ProductId]]] = {}
    base_coords_by_pair: dict[tuple[str, ProductId], NoNveSourceCoordinates] = {}
    for pair_key in pair_payloads:
        station, product = pair_key
        if product not in provider_config.products:
            raise FatalContractError("no_nve payload product is undeclared")
        configured = provider_config.products[product].coordinates.value
        if not isinstance(configured, NoNveSourceCoordinates):
            raise FatalContractError("no_nve payload source coordinates have invalid type")
        base_coords_by_pair[pair_key] = configured
    for station, product, item_coords in batch_coords.items:
        pair_key = (station, product)
        if pair_key not in pair_payloads:
            continue
        configured = base_coords_by_pair[pair_key]
        if (item_coords.parameter, item_coords.resolution_time) != (configured.parameter, configured.resolution_time):
            raise FatalContractError("no_nve batch item coordinates contradict product request")
        if item_coords.version_number is None:
            raise FatalContractError("no_nve batch item requires an explicit version_number")
        expected_versions_by_pair.setdefault(pair_key, set()).add(item_coords.version_number)
        key = (station, int(item_coords.parameter), item_coords.version_number)
        if key in pair_by_key:
            raise FatalContractError("no_nve batch coordinates contain ambiguous response identity")
        pair_by_key[key] = (station, product, item_coords)
        pairs_by_station_param.setdefault((station, int(item_coords.parameter)), []).append(pair_key)

    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    content_hash = hashlib.sha256(payload.content).hexdigest()
    pre_error: str | None = None
    data: list[object] = []
    try:
        document = json.loads(payload.content)
        if not isinstance(document, dict) or not isinstance(document.get("data"), list):
            raise SourceStructureError("HydAPI response lacks data series array")
        data = document["data"]
    except (ValueError, UnicodeDecodeError) as exc:
        pre_error = "HydAPI response is unreadable: " + str(exc)

    blocks_by_pair: dict[tuple[str, ProductId], list[object]] = {pair_key: [] for pair_key in pair_payloads}
    version_counts_by_key: Counter[tuple[str, int, int]] = Counter()
    blocks_by_key: dict[tuple[str, int, int], list[dict[str, object]]] = {}
    if pre_error is None:
        unmatched_blocks: list[object] = []
        for raw_entry in data:
            if not isinstance(raw_entry, dict):
                unmatched_blocks.append(raw_entry)
                continue
            raw_obj = cast("dict[str, object]", raw_entry)
            raw_station = raw_obj.get("stationId")
            raw_param = raw_obj.get("parameter")
            raw_ver = raw_obj.get("serieVersionNo")
            if isinstance(raw_station, str) and type(raw_param) is int and type(raw_ver) is int:
                identity = (raw_station, raw_param, raw_ver)
                if identity in pair_by_key:
                    target_pair = (pair_by_key[identity][0], pair_by_key[identity][1])
                    blocks_by_pair[target_pair].append(raw_obj)
                    version_counts_by_key[identity] += 1
                    blocks_by_key.setdefault(identity, []).append(raw_obj)
                    continue
                if (raw_station, raw_param) in pairs_by_station_param:
                    for target_pair in pairs_by_station_param[(raw_station, raw_param)]:
                        blocks_by_pair[target_pair].append(raw_obj)
                    continue
            unmatched_blocks.append(raw_obj)
        if unmatched_blocks:
            first_bad = unmatched_blocks[0]
            if not isinstance(first_bad, dict):
                pre_error = "HydAPI series is not an object"
            else:
                pre_error = "HydAPI batch response contains unexpected series metadata"

    result: dict[tuple[str, ProductId], ParsedSeries] = {}
    for pair_key, pair_payload in pair_payloads.items():
        station, product = pair_key
        window = SeriesWindow(
            start=datetime.fromisoformat(pair_payload.fetch_window.start.isoformat()),
            end=datetime.fromisoformat(pair_payload.fetch_window.end.isoformat()),
        )
        result[pair_key] = _decode_pair_series_blocks(
            station,
            str(product),
            base_coords_by_pair[pair_key],
            window,
            pair_payload.scope,
            content_hash,
            payload.origin.retrieved_at,
            retrieved,
            blocks_by_pair[pair_key],
            expected_versions=expected_versions_by_pair.get(pair_key),
            pre_error=pre_error,
            version_counts_by_key=version_counts_by_key,
            blocks_by_key=blocks_by_key,
        )
    return result


def _observations(series: dict[str, object]) -> list[object]:
    observations = series.get("observations")
    if not isinstance(observations, list):
        raise SourceStructureError("no_nve series observations must be a list")
    return cast("list[object]", observations)


def _time(observation: dict[str, object], index: int) -> datetime:
    value = observation.get("time")
    if not isinstance(value, str):
        raise SourceStructureError(f"no_nve observation {index} time must be a string")
    try:
        return datetime.strptime(value, _TIME_FORMAT)
    except ValueError as error:
        raise SourceStructureError(f"no_nve observation {index} time must be a strict UTC instant label") from error


def _value(observation: dict[str, object], index: int) -> float | None:
    if "value" not in observation:
        raise SourceStructureError(f"no_nve observation {index} is missing its value")
    value = observation["value"]
    if value is None:
        return None
    if type(value) not in (int, float):
        raise SourceStructureError(f"no_nve observation {index} value must be numeric or null")
    try:
        number = float(cast("int | float", value))
    except OverflowError as error:
        raise SourceStructureError(
            f"no_nve observation {index} value is not representable as a finite number"
        ) from error
    if not isfinite(number):
        raise SourceStructureError(f"no_nve observation {index} value must be finite")
    return number


def _code(observation: dict[str, object], name: str, index: int) -> int | None:
    if name not in observation:
        raise SourceStructureError(f"no_nve observation {index} is missing its {name}")
    value = observation[name]
    if value is None:
        return None
    if type(value) is not int or not (_INT64_MIN <= value <= _INT64_MAX):
        raise SourceStructureError(f"no_nve observation {index} {name} must be a signed 64-bit integer or null")
    return value
