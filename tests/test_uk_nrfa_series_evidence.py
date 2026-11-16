"""Recorded genuine-source tests for NRFA Step 3 series identities and annotations (#595)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.conversion import convert, filter_annotations_for_window
from rivretrieve._internal.engine import (
    ProductConfig,
    ProviderConfig,
    RequestedWindow,
    SourceCoordinates,
    Unit,
    UnknownTemporalSupport,
    WindowEndpoint,
    ZoneValue,
)
from rivretrieve._internal.observations import ObservationProvenance, ObservationResult, Receipts
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.uk_nrfa.annotations import (
    UK_NRFA_AMAX_REJECTION_SCHEMA,
    UK_NRFA_OBSERVATIONS_SCHEMA,
    UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA,
    UK_NRFA_SERIES_METADATA_SCHEMA,
)
from rivretrieve._internal.providers.uk_nrfa.series import (
    PRODUCT_IDS,
    build_peak_rejection_annotations,
    decode_time_series_response,
    source_series,
)
from rivretrieve._internal.source_annotations import with_annotations
from rivretrieve._internal.source_series import EvidenceState, SeriesScope

_EVIDENCE_SCOPE = "maintenance/catalogue/uk_nrfa/series-identity"

_TIME_SERIES_CAPTURES = (
    "capture-01/amax-flow.json",
    "capture-01/gmf.json",
    "capture-01/nmf.json",
    "capture-01/pot-flow.json",
    "capture-02/amax-flow.json",
    "capture-02/gdf.json",
    "capture-02/nmf.json",
    "capture-03/gdf.json",
    "capture-04/amax-stage-6007.json",
    "capture-04/gauging-flow-39001.json",
    "capture-04/gauging-stage-39001.json",
    "capture-04/gdf-39001-recent.json",
    "capture-04/ndf-39001.json",
    "capture-04/pot-stage-6007.json",
)


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        zone=ZoneValue("unknown"),
        products={
            ProductId(pid): ProductConfig(
                coordinates=SourceCoordinates(pid),
                unit=Unit("m" if pid.endswith("stage") else "m3/s"),
                semantics=UnknownTemporalSupport(),
            )
            for pid in PRODUCT_IDS
        },
    )


def _parse_feh_rejected(feh_path: Path) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in feh_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "[END]":
            current = None
        elif line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, [])
        elif current is not None and line:
            sections[current].append(line)
    return {
        "am_rejected": sections.get("AM Rejected", []),
        "pot_rejected": sections.get("POT Rejected", []),
    }


@pytest.mark.recorded(_EVIDENCE_SCOPE)
def test_recorded_nrfa_time_series_captures_decode_all_ten_products(retained_evidence_root: Path) -> None:
    root = retained_evidence_root / _EVIDENCE_SCOPE
    observed_products: set[str] = set()
    observed_flags: set[str] = set()
    cfg = _provider_config()

    for rel_path in _TIME_SERIES_CAPTURES:
        payload = json.loads((root / rel_path).read_bytes())
        defined, rows, bundle = decode_time_series_response(payload)
        observed_products.add(defined.product_id)
        assert rows["time_zone"].to_list() == ["unknown"] * rows.height

        meta_table = bundle.schema_table(UK_NRFA_SERIES_METADATA_SCHEMA.schema_id)
        assert meta_table["data_type_name"].to_list() == [payload["data-type"]["name"]]
        assert meta_table["measurement_type"].to_list() == [payload["data-type"]["measurement-type"]]
        assert meta_table["source_period"].to_list() == [payload["data-type"]["period"]]

        if rows.height == 0:
            assert not bundle.observation_tables
            continue

        obs_table = bundle.schema_table(UK_NRFA_OBSERVATIONS_SCHEMA.schema_id)
        observed_flags.update(flag for flag in obs_table["flag"].to_list() if flag is not None)
        if defined.product_id in {"gmf", "nmf"}:
            assert all(dt.day == 1 and dt.hour == 0 and dt.minute == 0 and dt.second == 0 for dt in rows["time"])
            # Genuine monthly series exercises full-month vs mid-month nominal clipping and bundles.
            first_label = obs_table["source_label"][0]
            year, month = (int(part) for part in first_label.split("-"))
            month_start = datetime(year, month, 1)
            next_month = datetime(year + (month == 12), (month % 12) + 1, 1)
            full_window = RequestedWindow(
                start=WindowEndpoint.from_datetime(month_start),
                end=WindowEndpoint.from_datetime(next_month),
            )
            converted = convert(rows, cfg, full_window, series=(defined,))
            filtered_bundle = filter_annotations_for_window(rows, bundle, full_window, series=(defined,))
            result = with_annotations(
                ObservationResult(
                    data=converted.value,
                    provenance=ObservationProvenance(source="live", provider_id=ProviderId("uk_nrfa"), request={}),
                    receipts=Receipts(provider_id=ProviderId("uk_nrfa")),
                    source_series=(defined,),
                    scope=SeriesScope(provider_ids=("uk_nrfa",)),
                ),
                filtered_bundle,
            )
            restored = rr.from_bundle(rr.to_bundle(result))
            assert isinstance(restored, ObservationResult)
            assert first_label in restored.to_polars(annotations=True)["source_label"].to_list()

    assert observed_products == set(PRODUCT_IDS)
    assert observed_flags == {"E", "S"}

    # Explicit verification of empty nmf capture vs midnight amax-flow capture.
    empty_def, empty_rows, empty_bundle = decode_time_series_response(
        json.loads((root / "capture-01/nmf.json").read_bytes()),
        expected_product_id="nmf",
    )
    assert empty_def.product_id == "nmf"
    assert empty_rows.is_empty()
    assert not empty_bundle.observation_tables

    amax_def, amax_rows, _ = decode_time_series_response(
        json.loads((root / "capture-02/amax-flow.json").read_bytes()),
        expected_product_id="amax-flow",
    )
    assert amax_def.facts[0].statistic.value == "max"
    assert any(dt.hour == 0 and dt.minute == 0 and dt.second == 0 for dt in amax_rows["time"])

    _, amax_stage_rows, _ = decode_time_series_response(
        json.loads((root / "capture-04/amax-stage-6007.json").read_bytes()),
        expected_product_id="amax-stage",
    )
    assert amax_stage_rows["time"].null_count() == 0
    amax_stage_def = source_series("6007", "amax-stage", origin="response")
    assert amax_stage_def.facts[0].statistic.state == EvidenceState.NOT_ESTABLISHED
    assert amax_stage_def.facts[0].vertical_reference.value == "gauge_zero"


@pytest.mark.recorded(_EVIDENCE_SCOPE)
def test_recorded_nrfa_peak_metadata_and_feh_correspondence(retained_evidence_root: Path) -> None:
    root = retained_evidence_root / _EVIDENCE_SCOPE

    # Both peak-metadata captures decode cleanly and preserve null vs populated rejection lists.
    for meta_rel in ("capture-01/peak-metadata.json", "capture-02/peak-metadata.json"):
        payload = json.loads((root / meta_rel).read_bytes())
        for station_row in payload["data"]:
            station_id = str(station_row["id"])
            all_ten = tuple(source_series(station_id, pid, origin="response") for pid in PRODUCT_IDS)
            tables = build_peak_rejection_annotations(station_row, series=all_ten)
            amax_tbl = tables[UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id]
            periods_tbl = tables[UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.schema_id]
            assert amax_tbl.rows["series_id"].to_list() == [
                s.series_id for s in all_ten if s.product_id in {"amax-flow", "amax-stage"}
            ]
            assert periods_tbl.rows["series_id"].to_list() == [
                s.series_id for s in all_ten if s.product_id in {"amax-flow", "amax-stage", "pot-flow", "pot-stage"}
            ]
            raw_years = station_row["peak-flow-rejected-amax-years"]
            expected_years = None if raw_years is None else raw_years["excluded-years"]
            assert amax_tbl.rows["rejected_amax_years"].to_list() == [expected_years] * 2

            raw_periods = station_row["peak-flow-rejected-periods"]
            expected_periods = None if raw_periods is None else raw_periods["rejected-periods"]
            assert periods_tbl.rows["rejected_periods"].to_list() == [expected_periods] * 4

    # Reconcile paired FEH files and JSON peak-metadata rejection annotations at station 82001.
    am_flow = (root / "capture-04/amax-flow-82001.feh").read_bytes()
    am_stage = (root / "capture-04/amax-stage-82001.feh").read_bytes()
    pt_flow = (root / "capture-04/pot-flow-82001.feh").read_bytes()
    pt_stage = (root / "capture-04/pot-stage-82001.feh").read_bytes()
    assert am_flow == am_stage
    assert pt_flow == pt_stage

    feh_am = _parse_feh_rejected(root / "capture-04/amax-flow-82001.feh")
    feh_pt = _parse_feh_rejected(root / "capture-04/pot-flow-82001.feh")
    meta_02 = json.loads((root / "capture-02/peak-metadata.json").read_bytes())
    row_82001 = next(row for row in meta_02["data"] if row["id"] == 82001)
    tables_82001 = build_peak_rejection_annotations(
        row_82001,
        series=tuple(source_series("82001", pid, origin="response") for pid in PRODUCT_IDS),
    )
    excluded_years = tables_82001[UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id].rows["rejected_amax_years"].to_list()[0]
    rejected_periods = (
        tables_82001[UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.schema_id].rows["rejected_periods"].to_list()[0]
    )
    assert excluded_years == [int(line.split(",", 1)[0]) for line in feh_am["am_rejected"]]
    expected_from_feh = [
        "/".join(datetime.strptime(part.strip(), "%d %b %Y").date().isoformat() for part in line.split(",", 1))
        for line in feh_pt["pot_rejected"]
    ]
    assert rejected_periods == expected_from_feh

    # Non-rejected station keeps explicit nulls across series annotations.
    row_6007 = next(row for row in meta_02["data"] if row["id"] == 6007)
    tables_6007 = build_peak_rejection_annotations(
        row_6007,
        series=tuple(source_series("6007", pid, origin="response") for pid in PRODUCT_IDS),
    )
    assert tables_6007[UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id].rows["rejected_amax_years"].to_list() == [None, None]
    assert tables_6007[UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.schema_id].rows["rejected_periods"].to_list() == [None] * 4
    assert pl.Series(
        tables_82001[UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id].rows["rejected_amax_years"]
    ).dtype == pl.List(pl.Int64)
