"""Offline transformations of Belgium - Wallonia (SPW Hydrométrie) KiWIS station and timeseries inventories."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    RecordingReference,
    RetainedInputReceipt,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.be_wal.series import (
    PRODUCT_SPECS,
    SPEC_BY_ROUTE_KEY,
    catalogue_product_rows,
    describe_associations,
)

ELIGIBLE_TYPE_STATIONS: frozenset[str] = frozenset({"Limnimètre", "Debitmètre"})
STANDING_RESERVOIR_EXCLUSIONS: frozenset[str] = frozenset({"5997", "640601", "656601", "7836", "9216"})
REQUIRED_TSLIST_SCOPES: frozenset[str] = frozenset(
    {
        "debit_05",
        "debit_10_12",
        "debit_20_22",
        "debit_40_42",
        "debit_50_52",
        "hauteur_05",
        "hauteur_10_12",
        "hauteur_20_22",
        "hauteur_40_42",
        "hauteur_50_52",
        "temperature_all",
    }
)
REQUIRED_EMPTY_SPANS: tuple[tuple[str, str], ...] = tuple(
    (f"{y:04d}-01-01T00:00:00Z", f"{min(y + 6, 2027):04d}-01-01T00:00:00Z") for y in range(1900, 2027, 6)
)
_CATCHMENT_SIZE_PATTERN = re.compile(r"^([0-9]+),([0-9]+)\s*km²$")

STATION_SOURCE_SCHEMA = pl.Schema(
    {
        "station_no": pl.String,
        "station_id": pl.String,
        "station_name": pl.String,
        "river_name": pl.String,
        "CATCHMENT_SIZE": pl.Float64,
        "CATCHMENT_SIZE_raw": pl.String,
        "station_latitude": pl.String,
        "station_longitude": pl.String,
        "station_local_x": pl.Float64,
        "station_local_y": pl.Float64,
        "station_georefsystem": pl.String,
        "TYPE_STATION": pl.String,
        "ADMINISTRATEUR": pl.String,
        "PAYS": pl.String,
        "STA_PUBINT": pl.String,
        "station_timezone": pl.String,
        "station_utcoffset": pl.String,
        "station_gauge_datum": pl.String,
        "station_gauge_datum_unit": pl.String,
        "in_scope_listed_ts_count": pl.Int64,
        "in_scope_available_ts_count": pl.Int64,
    }
)

ASSOCIATION_SCHEMA = pl.Schema(
    {
        "station_id": pl.String,
        "product_id": pl.String,
        "ts_id": pl.String,
        "ts_name": pl.String,
        "stationparameter_name": pl.String,
        "ts_unitsymbol": pl.String,
        "available": pl.Boolean,
        "from_raw": pl.String,
        "to_raw": pl.String,
    }
)


def parse_kiwis_table(raw_bytes: bytes, label: str) -> list[dict[str, str]]:
    """Decode one KiWIS tabular JSON ``[header, *rows]`` payload strictly."""
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FatalContractError(f"be_wal KiWIS {label} payload is not valid UTF-8 JSON") from error
    if not isinstance(payload, list) or not payload:
        raise FatalContractError(f"be_wal KiWIS {label} payload must be a non-empty JSON table")
    header_raw = payload[0]
    if (
        not isinstance(header_raw, list)
        or not header_raw
        or any(not isinstance(col, str) or not col for col in header_raw)
    ):
        raise FatalContractError(f"be_wal KiWIS {label} table lacks a valid string header row")
    header = cast("list[str]", header_raw)
    rows: list[dict[str, str]] = []
    width = len(header)
    for idx, row in enumerate(payload[1:], start=1):
        if not isinstance(row, list) or len(row) != width:
            raise FatalContractError(f"be_wal KiWIS {label} table row {idx} has unexpected shape")
        rows.append({str(col): "" if val is None else str(val) for col, val in zip(header, row, strict=True)})
    return rows


def parse_catchment_size(raw_value: str, *, station_no: str) -> float | None:
    """Parse ``CATCHMENT_SIZE`` in km2, mapping blanks and ``0,00 km²`` placeholders to null."""
    stripped = raw_value.strip()
    if not stripped:
        return None
    match = _CATCHMENT_SIZE_PATTERN.fullmatch(stripped)
    if match is None:
        raise FatalContractError(f"be_wal station {station_no} has unsupported CATCHMENT_SIZE {raw_value!r}")
    numeric = float(f"{match.group(1)}.{match.group(2)}")
    if not math.isfinite(numeric) or numeric < 0.0:
        raise FatalContractError(f"be_wal station {station_no} has non-finite CATCHMENT_SIZE {raw_value!r}")
    if numeric == 0.0:
        return None
    return numeric


def _parse_bounded_float(raw_value: str, label: str, *, low: float, high: float) -> float:
    stripped = raw_value.strip()
    if not stripped:
        raise FatalContractError(f"Missing required numeric field {label}")
    try:
        numeric = float(stripped)
    except ValueError as error:
        raise FatalContractError(f"Invalid numeric field {label}: {raw_value!r}") from error
    if not math.isfinite(numeric) or not (low <= numeric <= high):
        raise FatalContractError(f"Out-of-bounds {label}: {numeric!r}")
    return numeric


def _verify_empty_checks(
    empty_check_payloads: Sequence[tuple[str, Mapping[str, object], object]],
    *,
    empty_ts_meta: Mapping[str, tuple[str, str]],
) -> set[str]:
    """Verify full-history 1900..2027 zero-row proof across all empty-coverage series."""
    if not empty_ts_meta:
        return set()
    nonhourly_verified: set[str] = set()
    hourly_spans: dict[str, set[tuple[str, str]]] = {}

    for rec_id, meta, payload in empty_check_payloads:
        if not isinstance(payload, list) or not payload or any(not isinstance(item, dict) for item in payload):
            raise FatalContractError(f"Empty-check payload {rec_id!r} must be a non-empty JSON list of series objects")
        items = cast("list[dict[str, object]]", payload)
        kind_mode = str(meta.get("mode", ""))
        if kind_mode == "nonhourly":
            for item in items:
                ts_id = str(item.get("ts_id", ""))
                if item.get("rows") != "0" or item.get("data") != []:
                    raise FatalContractError(f"Empty-check {rec_id!r} for ts_id={ts_id!r} returned non-empty data")
                nonhourly_verified.add(ts_id)
        elif kind_mode == "hourly_chunk":
            span = (str(meta.get("from_iso", "")), str(meta.get("to_iso", "")))
            for item in items:
                ts_id = str(item.get("ts_id", ""))
                if item.get("rows") != "0" or item.get("data") != []:
                    raise FatalContractError(
                        f"Chunked empty-check {rec_id!r} for ts_id={ts_id!r} span={span!r} returned non-empty data"
                    )
                hourly_spans.setdefault(ts_id, set()).add(span)
        else:
            raise FatalContractError(f"Unsupported empty-check mode {kind_mode!r} in {rec_id!r}")

    expected_spans = set(REQUIRED_EMPTY_SPANS)
    verified: set[str] = set()
    for ts_id, (sno, ts_name) in sorted(empty_ts_meta.items()):
        if ts_name.startswith(("10-", "11-", "12-")):
            if hourly_spans.get(ts_id) != expected_spans:
                missing = sorted(expected_spans - hourly_spans.get(ts_id, set()))
                raise FatalContractError(
                    f"Empty-coverage hourly ts_id={ts_id} ({sno} {ts_name}) missing spans: {missing[:3]!r}"
                )
        else:
            if ts_id not in nonhourly_verified:
                raise FatalContractError(f"Empty-coverage non-hourly ts_id={ts_id} ({sno} {ts_name}) was not verified")
        verified.add(ts_id)
    return verified


def station_native_and_associations(
    station_rows: Sequence[Mapping[str, str]],
    tslist_rows: Sequence[Mapping[str, str]],
    *,
    empty_check_payloads: Sequence[tuple[str, Mapping[str, object], object]],
    retrieved_at: RetrievedAt,
) -> tuple[NativeTable, pl.DataFrame]:
    """Build the verified 338-gauge SPW Hydrométrie native table and 8,287 listed associations."""
    raw_by_station_no: dict[str, Mapping[str, str]] = {}
    for row in station_rows:
        sno = row.get("station_no", "").strip()
        if not sno:
            raise FatalContractError("SPW getStationList row lacks station_no")
        if sno in raw_by_station_no:
            raise FatalContractError(f"Duplicate SPW station_no {sno!r} in getStationList")
        raw_by_station_no[sno] = row

    seen_ts_ids: dict[str, tuple[str, str, str]] = {}
    pair_rows: dict[tuple[str, str], dict[str, object]] = {}
    in_scope_by_station: dict[str, list[dict[str, object]]] = {}

    for row in tslist_rows:
        param_name = row.get("stationparameter_name", "")
        ts_name = row.get("ts_name", "")
        spec = SPEC_BY_ROUTE_KEY.get((param_name, ts_name))
        if spec is None:
            continue
        sno = row.get("station_no", "").strip()
        ts_id = row.get("ts_id", "").strip()
        unit = row.get("ts_unitsymbol", "").strip()
        if not sno or not ts_id:
            raise FatalContractError(f"SPW tslist row missing station_no or ts_id: {row!r}")
        if unit != spec.source_unit:
            raise FatalContractError(
                f"SPW ts_id={ts_id} ({sno} {ts_name}) unit {unit!r} contradicts expected {spec.source_unit!r}"
            )
        prev_ts = seen_ts_ids.get(ts_id)
        key = (sno, spec.product_id)
        if prev_ts is not None:
            if prev_ts != (sno, param_name, ts_name):
                raise FatalContractError(f"Conflicting KiWIS ts_id={ts_id} rows: {prev_ts!r}")
            continue
        seen_ts_ids[ts_id] = (sno, param_name, ts_name)
        if key in pair_rows:
            raise FatalContractError(f"Multiple ts_ids for {key!r}: {pair_rows[key]['ts_id']!r} and {ts_id!r}")
        from_raw = row.get("from", "").strip()
        to_raw = row.get("to", "").strip()
        if bool(from_raw) != bool(to_raw):
            raise FatalContractError(f"Partial coverage bounds on {key!r} ts_id={ts_id}: {(from_raw, to_raw)!r}")
        assoc: dict[str, object] = {
            "station_id": sno,
            "product_id": spec.product_id,
            "ts_id": ts_id,
            "ts_name": ts_name,
            "stationparameter_name": param_name,
            "ts_unitsymbol": unit,
            "available": bool(from_raw and to_raw),
            "from_raw": from_raw,
            "to_raw": to_raw,
        }
        pair_rows[key] = assoc
        in_scope_by_station.setdefault(sno, []).append(assoc)

    retained_stations: list[dict[str, object]] = []
    empty_ts_meta: dict[str, tuple[str, str]] = {}
    retained_associations: list[dict[str, object]] = []

    for sno, raw in sorted(raw_by_station_no.items()):
        type_station = raw.get("TYPE_STATION", "").strip()
        lat_raw = raw.get("station_latitude", "").strip()
        lon_raw = raw.get("station_longitude", "").strip()
        if type_station not in ELIGIBLE_TYPE_STATIONS:
            continue
        if sno in STANDING_RESERVOIR_EXCLUSIONS:
            continue
        if not lat_raw or not lon_raw:
            continue
        station_assocs = in_scope_by_station.get(sno, [])
        if not station_assocs:
            continue

        _parse_bounded_float(lat_raw, f"{sno}.station_latitude", low=49.0, high=51.5)
        _parse_bounded_float(lon_raw, f"{sno}.station_longitude", low=2.5, high=6.8)
        local_x = _parse_bounded_float(
            raw.get("station_local_x", ""), f"{sno}.station_local_x", low=10_000.0, high=350_000.0
        )
        local_y = _parse_bounded_float(
            raw.get("station_local_y", ""), f"{sno}.station_local_y", low=10_000.0, high=250_000.0
        )

        georef = raw.get("station_georefsystem", "").strip()
        utcoff = raw.get("station_utcoffset", "").strip()
        sname = raw.get("station_name", "").strip()
        rname = raw.get("river_name", "").strip()
        if georef != "Lambert 72":
            raise FatalContractError(f"be_wal gauge {sno} has unexpected station_georefsystem {georef!r}")
        if utcoff != "-60":
            raise FatalContractError(f"be_wal gauge {sno} has unexpected station_utcoffset {utcoff!r}")
        if not sname or not rname:
            raise FatalContractError(f"be_wal gauge {sno} lacks non-blank station_name or river_name")

        catch_raw = raw.get("CATCHMENT_SIZE", "")
        catch_val = parse_catchment_size(catch_raw, station_no=sno)

        for assoc in station_assocs:
            if not assoc["available"]:
                empty_ts_meta[str(assoc["ts_id"])] = (sno, str(assoc["ts_name"]))
            retained_associations.append(assoc)

        avail_count = sum(1 for assoc in station_assocs if assoc["available"])
        retained_stations.append(
            {
                "station_no": sno,
                "station_id": raw.get("station_id", "").strip(),
                "station_name": raw.get("station_name", ""),
                "river_name": raw.get("river_name", ""),
                "CATCHMENT_SIZE": catch_val,
                "CATCHMENT_SIZE_raw": catch_raw,
                "station_latitude": lat_raw,
                "station_longitude": lon_raw,
                "station_local_x": local_x,
                "station_local_y": local_y,
                "station_georefsystem": georef,
                "TYPE_STATION": type_station,
                "ADMINISTRATEUR": raw.get("ADMINISTRATEUR", ""),
                "PAYS": raw.get("PAYS", ""),
                "STA_PUBINT": raw.get("STA_PUBINT", ""),
                "station_timezone": raw.get("station_timezone", ""),
                "station_utcoffset": utcoff,
                "station_gauge_datum": raw.get("station_gauge_datum", ""),
                "station_gauge_datum_unit": raw.get("station_gauge_datum_unit", ""),
                "in_scope_listed_ts_count": len(station_assocs),
                "in_scope_available_ts_count": avail_count,
            }
        )

    if not retained_stations:
        raise FatalContractError("SPW KiWIS inputs produced zero eligible gauges")
    _verify_empty_checks(empty_check_payloads, empty_ts_meta=empty_ts_meta)

    native_df = pl.DataFrame(retained_stations, schema=STATION_SOURCE_SCHEMA).sort("station_no")
    assoc_df = pl.DataFrame(retained_associations, schema=ASSOCIATION_SCHEMA).sort("station_id", "product_id")
    return stamp_native_table(native_df, retrieved_at), assoc_df


def catalogue_tables(
    native: NativeTable,
    associations: pl.DataFrame,
    *,
    checked_on: date,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Build canonical SPW Hydrométrie product, station, and 338 x 62 availability tables."""
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
        AvailabilityDtype,
        validate_catalogue,
    )

    stations = native.data.select(
        pl.lit("be_wal").alias("provider_id"),
        pl.col("station_no").alias("station_id"),
        pl.col("station_latitude").cast(pl.Float64).alias("latitude"),
        pl.col("station_longitude").cast(pl.Float64).alias("longitude"),
        pl.lit("EPSG:4326").alias("crs"),
    ).sort("station_id")

    station_set = set(stations["station_id"])
    if not set(associations["station_id"]) <= station_set:
        raise FatalContractError("be_wal association references a station absent from canonical gauge scope")

    products = pl.DataFrame(catalogue_product_rows(), schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")
    if products.height != len(PRODUCT_SPECS):
        raise FatalContractError("be_wal product catalogue row count disagrees with PRODUCT_SPECS")

    by_pair: dict[tuple[str, str], tuple[bool, str]] = {
        (str(row["station_id"]), str(row["product_id"])): (bool(row["available"]), str(row["ts_id"]))
        for row in associations.iter_rows(named=True)
    }

    pair_rows: list[dict[str, object]] = []
    for station_id in stations["station_id"]:
        for product_id in products["product_id"]:
            entry = by_pair.get((station_id, product_id))
            if entry is not None and entry[0]:
                availability = "available"
                reason = "Series listed in KiWIS getTimeseriesList with non-empty temporal coverage"
            elif entry is not None:
                availability = "unavailable"
                reason = (
                    "Series listed in KiWIS getTimeseriesList with empty coverage and verified "
                    "empty (0 rows across 1900-01-01..2027-01-01) in getTimeseriesValues"
                )
            else:
                availability = "unavailable"
                reason = "Series not listed for this station in KiWIS getTimeseriesList"
            pair_rows.append(
                {
                    "provider_id": "be_wal",
                    "station_id": station_id,
                    "product_id": product_id,
                    "availability": availability,
                    "availability_reason": reason,
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": checked_on,
                }
            )

    pairs = (
        pl.DataFrame(pair_rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema)
        .with_columns(pl.col("availability").cast(AvailabilityDtype))
        .sort("station_id", "product_id")
    )

    for frame, schema in (
        (products, PRODUCT_CATALOG_SCHEMA),
        (stations, STATION_CATALOG_SCHEMA),
        (pairs, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    return products, stations, pairs


def read_original(evidence_root: Path, reference: RecordingReference, *, input_receipt: RetainedInputReceipt) -> bytes:
    """Verify one explicitly selected publisher body before parsing it."""
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member = selected.get(reference.repository_path)
    if member is None:
        raise FatalContractError(
            f"be_wal original {reference.repository_path!r} is absent from selected retained inputs"
        )
    if member.sha256 != reference.sha256:
        raise FatalContractError(f"be_wal original {reference.repository_path!r} differs from recording identity")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return (evidence_root / reference.repository_path).read_bytes()


def _read_selection(evidence_root: Path, selection_path: str, input_receipt: RetainedInputReceipt) -> dict:
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("be_wal selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    if not isinstance(selection, dict) or not isinstance(selection.get("captures"), list):
        raise FatalContractError("be_wal selection requires explicit captures")
    return selection


def _read_selection_and_originals(
    evidence_root: Path,
    *,
    selection_path: str,
    input_receipt: RetainedInputReceipt,
) -> tuple[dict, tuple[RecordingReference, ...], NativeTable, pl.DataFrame]:
    selection = _read_selection(evidence_root, selection_path, input_receipt)
    recordings: list[RecordingReference] = []
    station_rows: list[dict[str, str]] | None = None
    station_retrieved_at: datetime | None = None
    tslist_scopes: dict[str, list[dict[str, str]]] = {}
    empty_check_payloads: list[tuple[str, Mapping[str, object], object]] = []

    for capture in selection["captures"]:
        kind = capture["kind"]
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError(f"be_wal selected body disagrees with recording identity for {kind!r}")
        raw = read_original(evidence_root, reference, input_receipt=input_receipt)
        recordings.append(reference)
        if kind in {"terms", "series_meaning"}:
            continue
        if kind == "station_list":
            if station_rows is not None:
                raise FatalContractError("be_wal selection requires exactly one station_list capture")
            station_rows = parse_kiwis_table(raw, "station_list")
            station_retrieved_at = reference.retrieved_at
        elif kind == "tslist":
            scope = str(capture.get("scope", ""))
            if scope in tslist_scopes:
                raise FatalContractError(f"Duplicate be_wal tslist scope {scope!r}")
            tslist_scopes[scope] = parse_kiwis_table(raw, f"tslist[{scope}]")
        elif kind == "tslist_excluded":
            parse_kiwis_table(raw, reference.recording_id)
        elif kind == "empty_check":
            empty_check_payloads.append((reference.recording_id, capture, json.loads(raw)))
        else:
            raise FatalContractError(f"Unsupported be_wal capture kind {kind!r}")

    if station_rows is None or station_retrieved_at is None:
        raise FatalContractError("be_wal selection requires a station_list capture")
    if set(tslist_scopes) != REQUIRED_TSLIST_SCOPES:
        missing = sorted(REQUIRED_TSLIST_SCOPES - set(tslist_scopes))
        raise FatalContractError(f"be_wal selection missing required tslist scopes: {missing!r}")

    all_tslist_rows = [row for scope in sorted(tslist_scopes) for row in tslist_scopes[scope]]
    native_table, associations = station_native_and_associations(
        station_rows,
        all_tslist_rows,
        empty_check_payloads=empty_check_payloads,
        retrieved_at=RetrievedAt(station_retrieved_at),
    )
    return selection, tuple(recordings), native_table, associations


def read_native_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> NativeTable:
    """Derive verified native station rows from selected KiWIS captures without reading native.parquet."""
    _, _, native_table, _ = _read_selection_and_originals(
        evidence_root,
        selection_path=selection_path,
        input_receipt=input_receipt,
    )
    return native_table


@dataclass(frozen=True)
class CatalogueSources:
    native_table: NativeTable
    associations: pl.DataFrame
    provenance: AcquisitionProvenance
    checked_on: date


def read_catalogue_sources(
    evidence_root: Path,
    *,
    selection_path: str,
    input_receipt: RetainedInputReceipt,
) -> CatalogueSources:
    """Read an explicitly selected offline be_wal build after exact member verification."""
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.be_wal import origins

    selection, recordings, recomputed_native, associations = _read_selection_and_originals(
        evidence_root,
        selection_path=selection_path,
        input_receipt=input_receipt,
    )
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection.get("native_table")
    if not isinstance(native_path, str) or native_path not in selected:
        raise FatalContractError("be_wal native table is absent from selected retained inputs")
    native_member = selected[native_path]
    retained_native = read_native_table(
        evidence_root / native_path,
        expected_sha256=native_member.sha256,
        expected_byte_size=native_member.byte_size,
    )
    if not retained_native.data.equals(recomputed_native.data):
        raise FatalContractError("be_wal retained native table differs from recomputed KiWIS station snapshot")

    native_revision = selection.get("native_revision")
    checked_on_raw = selection.get("checked_on")
    if not isinstance(native_revision, str) or not isinstance(checked_on_raw, str):
        raise FatalContractError("be_wal selection requires native_revision and checked_on strings")

    provenance = origins.build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path=native_path,
            revision=native_revision,
            sha256=native_member.sha256,
            byte_size=native_member.byte_size,
        ),
        recordings,
        acquisitions=tuple(
            AcquisitionRecord.model_validate(item)
            for item in cast("list[object]", selection["publication_acquisitions"])
        ),
        source_bindings=tuple(
            FactBinding.model_validate(item) for item in cast("list[object]", selection["source_bindings"])
        ),
        statements=tuple(
            SourceStatement.model_validate(item) for item in cast("list[object]", selection["statements"])
        ),
    )
    return CatalogueSources(
        native_table=retained_native,
        associations=associations,
        provenance=provenance,
        checked_on=date.fromisoformat(checked_on_raw),
    )


@dataclass(frozen=True)
class GeneratedBeWalCatalogue:
    provider_info: dict[str, object]
    products: pl.DataFrame
    stations: pl.DataFrame
    station_products: pl.DataFrame
    station_metadata: pl.DataFrame
    acquisition_provenance: AcquisitionProvenance
    source_descriptions: SourceDescriptions


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
    *,
    associations: pl.DataFrame,
    checked_on: date,
    provenance: AcquisitionProvenance,
) -> GeneratedBeWalCatalogue:
    """Assemble the official Belgium - Wallonia (`be_wal`) offline station and product catalogue."""
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.be_wal.station_metadata import project_station_metadata

    if native_table.data.drop("retrieved_at").schema != STATION_SOURCE_SCHEMA:
        raise FatalContractError("be_wal native table does not match STATION_SOURCE_SCHEMA")
    if native_table.data.is_empty():
        raise FatalContractError("be_wal native table must not be empty")

    products, stations, pairs = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId("be_wal"), origins, native_table, stations)
    if provenance is None or provenance.provider_id != "be_wal":
        raise FatalContractError("Official be_wal catalogue requires its selected acquisition provenance")
    station_metadata = project_station_metadata(native_table, stations)

    provider_info: dict[str, object] = {
        "provider_id": "be_wal",
        "name": "Service public de Wallonie (SPW) — Hydrométrie",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": None,
        "citation": "Service public de Wallonie (SPW) — Hydrométrie",
    }
    return GeneratedBeWalCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=pairs,
        station_metadata=station_metadata,
        acquisition_provenance=provenance,
        source_descriptions=describe_associations(associations),
    )


def write_catalogue(
    catalogue: GeneratedBeWalCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] = (),
) -> None:
    """Publish candidate runtime tables through the shared evidence-aware publication path."""
    from io import BytesIO

    from rivretrieve._internal.catalogues.descriptor import build_catalogue_descriptor
    from rivretrieve._internal.catalogues.evidence import EvidenceHeader
    from rivretrieve._internal.catalogues.evidence_encoding import EVIDENCE_FILENAMES, parse_catalogue_evidence
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.catalogues.source_series import decode_source_descriptions, encode_source_descriptions
    from rivretrieve._internal.providers.be_wal.origins import (
        STATION_CATALOGUE_ORIGINS,
        STATION_METADATA_FIELDS,
        STATION_METADATA_NOTICE,
    )

    files = {
        "provider.json": (json.dumps(catalogue.provider_info, sort_keys=True, separators=(",", ":")) + "\n").encode()
    }
    for name, frame in (
        ("products", catalogue.products),
        ("stations", catalogue.stations),
        ("station_products", catalogue.station_products),
    ):
        buffer = BytesIO()
        frame.write_parquet(buffer)
        files[f"{name}.parquet"] = buffer.getvalue()

    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (STATION_CATALOGUE_ORIGINS,),
        files,
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=metadata_fields or STATION_METADATA_FIELDS,
        station_metadata=catalogue.station_metadata,
        metadata_implementation=(
            "src/rivretrieve/_internal/providers/be_wal/station_metadata.py",
            "project_station_metadata",
        ),
        station_metadata_notice=STATION_METADATA_NOTICE,
        source_descriptions=catalogue.source_descriptions,
    )
    metadata["source_series.json"] = encode_source_descriptions(catalogue.source_descriptions, schema_version=2)
    if decode_source_descriptions(metadata["source_series.json"]) != catalogue.source_descriptions:
        raise FatalContractError("be_wal source-description encoding changed source definitions")
    evidence = parse_catalogue_evidence(
        EvidenceHeader.model_validate_json(metadata["provenance.json"]),
        {filename: metadata[filename] for filename in EVIDENCE_FILENAMES.values()},
    )
    metadata.pop("croissant.json")
    metadata["croissant.json"] = (
        json.dumps(
            build_catalogue_descriptor(
                evidence,
                (STATION_CATALOGUE_ORIGINS,),
                {**files, **metadata},
                station_metadata_notice=STATION_METADATA_NOTICE,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")

    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, content in {**files, **metadata}.items():
        (output / name).write_bytes(content)


def main(argv: list[str] | None = None) -> int:
    """Compose a derived native candidate or runtime be_wal catalogue outside source checkouts."""
    import argparse

    from rivretrieve._internal.catalogues.native import write_native_table

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--selection", default="maintenance/catalogue/be_wal/official/selection.json")
    parser.add_argument("--input-receipt", type=Path, required=True)
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--build-inputs", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    output = args.out.resolve()
    evidence_root = args.evidence_root.resolve(strict=True)
    if output.exists() or output.is_relative_to(evidence_root) or evidence_root.is_relative_to(output):
        raise FatalContractError("be_wal catalogue output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("be_wal catalogue output must stay outside source checkouts")

    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    if args.native_only:
        native = read_native_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        write_native_table(native, output / "native.parquet")
        return 0

    if args.build_inputs is None:
        raise FatalContractError("be_wal catalogue publication requires explicit --build-inputs")
    from rivretrieve._internal.providers.be_wal.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

    sources = read_catalogue_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
    catalogue = build_catalogue(
        sources.native_table,
        STATION_CATALOGUE_ORIGINS,
        associations=sources.associations,
        checked_on=sources.checked_on,
        provenance=sources.provenance,
    )
    write_catalogue(
        catalogue,
        output,
        build_inputs=CatalogueBuildInputs.model_validate_json(args.build_inputs.read_bytes()),
        native_table=sources.native_table,
        metadata_fields=STATION_METADATA_FIELDS,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
