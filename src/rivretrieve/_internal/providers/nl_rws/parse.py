"""Decode Rijkswaterstaat DDAPI 2.0 OphalenWaarnemingen responses into ParsedSeries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.nl_rws.annotations import NL_RWS_OBSERVATION_SCHEMA
from rivretrieve._internal.providers.nl_rws.series import (
    PROVIDER_ID,
    is_missing_observation_value,
    parse_tijdstip_offset,
    resolve_response_series,
)
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
    SourceSeries,
    admission,
    stable_id,
)


def _as_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def _decode_waarnemingen(content: bytes) -> list[dict[str, object]]:
    """Decode DDAPI 2.0 JSON bytes once into WaarnemingenLijst entries.

    HTTP 204 No Content arrives as empty bytes (``b""``) and returns ``[]``.
    """
    if not content.strip():
        return []
    try:
        document = json.loads(content)
    except (ValueError, UnicodeDecodeError) as error:
        raise UnsupportedSourceStructureError("nl_rws response is not valid JSON") from error
    doc = _as_dict(document)
    if doc is None:
        raise UnsupportedSourceStructureError("nl_rws response must be a JSON object")
    raw_list = doc.get("WaarnemingenLijst")
    if raw_list is None:
        return []
    if not isinstance(raw_list, list):
        raise UnsupportedSourceStructureError("nl_rws WaarnemingenLijst must be a JSON array")
    entries: list[dict[str, object]] = []
    for item in raw_list:
        entry = _as_dict(item)
        if entry is None:
            raise UnsupportedSourceStructureError("nl_rws WaarnemingenLijst entry must be a JSON object")
        entries.append(entry)
    return entries


def _extract_metadata_str(meta: dict[str, object], scalar_key: str, list_key: str) -> str | None:
    val = meta.get(scalar_key)
    if isinstance(val, str):
        return val
    vals = meta.get(list_key)
    if isinstance(vals, list) and vals and isinstance(vals[0], str):
        return vals[0]
    return None


def _failed_parsed(payload: Payload, station: str, product: ProductId, reason: str) -> ParsedSeries:
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, station, str(product), "failed"),
        series_id=None,
        station_id=station,
        product_id=product,
        window=window,
        status=OutcomeStatus.FAILED,
        reason=reason,
        retrieved_at=retrieved,
    )
    return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), (outcome,))


def _parse_decoded_for_product(
    entries: list[dict[str, object]],
    *,
    payload: Payload,
    station: str,
    product: ProductId,
) -> ParsedSeries:
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    product_str = str(product)

    rows: list[dict[str, object]] = []
    ann_rows: list[dict[str, object]] = []
    series_list: list[SourceSeries] = []
    outcomes: list[RetrievalOutcome] = []

    for entry in entries:
        aquo_meta = _as_dict(entry.get("AquoMetadata"))
        if aquo_meta is None:
            raise UnsupportedSourceStructureError("nl_rws WaarnemingenLijst entry missing AquoMetadata")
        raw_metingen = entry.get("MetingenLijst")
        if raw_metingen is None:
            raw_metingen = []
        if not isinstance(raw_metingen, list):
            raise UnsupportedSourceStructureError("nl_rws MetingenLijst must be a JSON array")

        # First pass: parse timestamps/offsets for this series so mixed-offset segments can be resolved
        parsed_items: list[tuple[datetime, str, float | None, str | None, str | None]] = []
        offsets: list[str] = []
        for raw_m in raw_metingen:
            m = _as_dict(raw_m)
            if m is None:
                raise UnsupportedSourceStructureError("nl_rws MetingenLijst item must be a JSON object")
            tijdstip = m.get("Tijdstip")
            if not isinstance(tijdstip, str):
                raise UnsupportedSourceStructureError("nl_rws observation missing string Tijdstip")
            try:
                native_time, offset_str = parse_tijdstip_offset(tijdstip)
            except (ValueError, FatalContractError) as error:
                raise UnsupportedSourceStructureError(f"nl_rws invalid Tijdstip: {tijdstip!r}") from error
            offsets.append(offset_str)

            meetwaarde = _as_dict(m.get("Meetwaarde")) or {}
            num_raw = meetwaarde.get("Waarde_Numeriek")
            alpha_raw = meetwaarde.get("Waarde_Alfanumeriek")
            numeric_val: float | int | None = (
                num_raw if isinstance(num_raw, (int, float)) and not isinstance(num_raw, bool) else None
            )
            alpha_val: str | None = alpha_raw if isinstance(alpha_raw, str) else None

            wm = _as_dict(m.get("WaarnemingMetadata")) or {}
            statuswaarde = _extract_metadata_str(wm, "Statuswaarde", "StatuswaardeLijst")
            qcode = _extract_metadata_str(wm, "Kwaliteitswaardecode", "KwaliteitswaardecodeLijst")

            if is_missing_observation_value(numeric_val, alpha_val, qcode):
                clean_value: float | None = None
            else:
                assert numeric_val is not None
                clean_value = float(numeric_val)

            parsed_items.append((native_time, offset_str, clean_value, statuswaarde, qcode))

        resolved = resolve_response_series(
            station_id=station,
            aquo_metadata=aquo_meta,
            offsets=offsets,
        )
        if resolved is None or resolved.product_id != product_str:
            continue

        facts_by_offset = {f.time_zone.value: f for f in resolved.facts}
        series_list.append(resolved)

        series_row_count = 0
        supported_facts_ids: list[str] = []
        unsupported_reason: str | None = None
        for f in resolved.facts:
            adm = admission(f)
            if adm.status != "supported":
                unsupported_reason = adm.reason
            else:
                supported_facts_ids.append(f.facts_id)

        if unsupported_reason is None:
            for native_time, offset_str, clean_value, statuswaarde, qcode in parsed_items:
                fact = facts_by_offset[offset_str]
                rows.append(
                    {
                        "station_id": station,
                        "product_id": product_str,
                        "time": native_time,
                        "value": clean_value,
                        "time_zone": offset_str,
                        "series_id": resolved.series_id,
                        "facts_id": fact.facts_id,
                        "source_unit": fact.source_unit.value,
                    }
                )
                ann_rows.append(
                    {
                        "series_id": resolved.series_id,
                        "facts_id": fact.facts_id,
                        "station_id": station,
                        "product_id": product_str,
                        "time": native_time,
                        "time_zone": offset_str,
                        "measured": True,
                        "statuswaarde": statuswaarde,
                        "kwaliteitswaardecode": qcode,
                    }
                )
                series_row_count += 1

        status = (
            OutcomeStatus.UNSUPPORTED
            if unsupported_reason is not None
            else OutcomeStatus.SUCCESS
            if series_row_count > 0
            else OutcomeStatus.EMPTY
        )
        outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(payload.acquisition_id, resolved.series_id, product_str),
                series_id=resolved.series_id,
                station_id=station,
                product_id=product,
                window=window,
                facts_ids=tuple(supported_facts_ids),
                status=status,
                reason=unsupported_reason,
                retrieved_at=retrieved,
            )
        )

    if not series_list:
        reason = f"No Rijkswaterstaat DDAPI 2.0 observations returned for {station}/{product_str} in requested window"
        evidence = f"source-call:{payload.acquisition_id}"
        empty_inventory = InventorySnapshot(
            snapshot_id=stable_id(payload.acquisition_id, station, product_str, "empty-inventory"),
            scope=payload.scope
            or SeriesScope(provider_ids=(PROVIDER_ID,), station_ids=(station,), product_ids=(product_str,)),
            members=(),
            completeness=InventoryCompleteness.COMPLETE,
            access=product_str,
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(evidence,),
        )
        no_match_outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, station, product_str, "no-match"),
            series_id=None,
            station_id=station,
            product_id=product,
            window=window,
            status=OutcomeStatus.NO_MATCH,
            reason=reason,
            retrieved_at=retrieved,
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (empty_inventory,), (no_match_outcome,))

    evidence = f"source-call:{payload.acquisition_id}"
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, station, product_str, "inventory"),
        scope=payload.scope
        or SeriesScope(provider_ids=(PROVIDER_ID,), station_ids=(station,), product_ids=(product_str,)),
        members=tuple(s.series_id for s in series_list),
        completeness=InventoryCompleteness.INCOMPLETE,
        access=product_str,
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
        reason="Returned series establish this response window, not an exhaustive historical inventory",
    )
    if ann_rows:
        ann_frame = pl.DataFrame(
            ann_rows,
            schema={**OBSERVATION_STRUCTURAL_SCHEMA, **NL_RWS_OBSERVATION_SCHEMA.polars_schema()},
        )
        ann_table = ObservationAnnotationTable.from_rows(
            schema=NL_RWS_OBSERVATION_SCHEMA,
            rows=ann_frame,
            measurement_indices=list(range(len(rows))),
        )
        annotations = AnnotationBundle(observation_tables={NL_RWS_OBSERVATION_SCHEMA.schema_id: ann_table})
    else:
        annotations = AnnotationBundle.empty()

    return ParsedSeries(
        pl.DataFrame(rows, schema=RowsSchema.polars_schema),
        tuple(series_list),
        (inventory,),
        tuple(outcomes),
        annotations=annotations,
    )


def parse(payload: Payload, config: ProviderConfig) -> ParsedSeries:
    """Parse one single-pair DDAPI 2.0 response payload."""
    if len(payload.station_products) != 1:
        raise FatalContractError(
            "nl_rws parse() expects a single (station, product) pair; use parse_group() for shared payloads"
        )
    station, product = payload.station_products[0]
    try:
        entries = _decode_waarnemingen(payload.content)
        result = _parse_decoded_for_product(entries, payload=payload, station=station, product=product)
    except UnsupportedSourceStructureError as error:
        return _failed_parsed(payload, station, product, str(error))
    finally:
        entries = []
    return result


def parse_group(
    payload: Payload,
    pair_payloads: Mapping[tuple[str, ProductId], Payload],
    config: ProviderConfig,
) -> Mapping[tuple[str, ProductId], ParsedSeries]:
    """Decode a shared DDAPI 2.0 response once into independent per-product ParsedSeries."""
    try:
        entries = _decode_waarnemingen(payload.content)
    except UnsupportedSourceStructureError as error:
        return {
            (station, product): _failed_parsed(pair_payload, station, product, str(error))
            for (station, product), pair_payload in pair_payloads.items()
        }

    results: dict[tuple[str, ProductId], ParsedSeries] = {}
    try:
        for (station, product), pair_payload in pair_payloads.items():
            try:
                results[(station, product)] = _parse_decoded_for_product(
                    entries,
                    payload=pair_payload,
                    station=station,
                    product=product,
                )
            except UnsupportedSourceStructureError as error:
                results[(station, product)] = _failed_parsed(pair_payload, station, product, str(error))
    finally:
        entries.clear()
    return results
