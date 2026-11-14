"""Synthetic VandA catalogue identity and source-fidelity checks."""

from datetime import UTC, date, datetime

import polars as pl
import pytest

from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.providers.dk_vanda.generate_catalogue import (
    ASSOCIATION_SCHEMA,
    catalogue_tables,
    describe_associations,
    station_native_table,
    station_product_associations,
)
from rivretrieve._internal.providers.dk_vanda.series import series_mappings


def examination(sc, parameter, unit):
    return {"examinationTypeSc": sc, "parameter": parameter, "unit": unit}


def station(station_id, location_type="Vandløb", x=664540.0, y=6147229.0, srid="25832", examinations=()):
    return {
        "stationId": station_id,
        "stationUid": f"uid-{station_id}",
        "name": f"Synthetic {station_id}",
        "locationType": location_type,
        "stationOwnerName": "Miljøstyrelsen",
        "operatorName": "DCE, Aarhus Universitet",
        "location": {"x": x, "y": y, "srid": srid},
        "catchmentAreaKm2": None,
        "measurementPoints": [{"number": 1, "examinations": list(examinations)}],
    }


def test_native_table_keeps_only_river_stations():
    native = station_native_table(
        [station("A"), station("B", location_type="Sø")],
        retrieved_at=RetrievedAt(datetime(2026, 11, 9, tzinfo=UTC)),
    )
    assert native.data["stationId"].to_list() == ["A"]


def test_native_table_rejects_unexpected_srid():
    with pytest.raises(Exception, match="coordinate reference system"):
        station_native_table([station("A", srid="4326")], retrieved_at=RetrievedAt(datetime(2026, 11, 9, tzinfo=UTC)))


def test_native_table_rejects_conflicting_duplicate_identity():
    rows = [station("A", x=1.0), station("A", x=2.0)]
    with pytest.raises(Exception, match="sharing one stationId"):
        station_native_table(rows, retrieved_at=RetrievedAt(datetime(2026, 11, 9, tzinfo=UTC)))


def test_associations_keep_admitted_examinations_and_drop_the_rest():
    rows = [
        station(
            "A",
            examinations=(
                examination(27, "Vandføring", "l/s"),
                examination(25, "Vandstand", "cm"),
                examination(24, "Vandføring Feltmåling", "l/s"),
                examination(42, "Batterispænding", "volt"),
            ),
        ),
        station("B", examinations=()),
    ]
    associations = station_product_associations(rows, station_ids={"A", "B"})
    assert set(associations.select("station_id", "examination_type_sc").iter_rows()) == {("A", 25), ("A", 27)}


def test_associations_ignore_stations_outside_the_selected_registry():
    rows = [station("A", examinations=(examination(27, "Vandføring", "l/s"),))]
    associations = station_product_associations(rows, station_ids={"B"})
    assert associations.is_empty()


def test_catalogue_keeps_unknown_pairs_and_projects_coordinates_into_denmark():
    native = station_native_table(
        [station("A"), station("B")], retrieved_at=RetrievedAt(datetime(2026, 11, 9, tzinfo=UTC))
    )
    associations = pl.DataFrame([("A", 27, "Vandføring", "l/s")], schema=ASSOCIATION_SCHEMA, orient="row")
    products, stations, pairs = catalogue_tables(native, associations, checked_on=date(2026, 11, 9))
    assert stations["crs"].unique().to_list() == ["EPSG:4326"]
    lon, lat = stations.filter(pl.col("station_id") == "A").select("longitude", "latitude").row(0)
    assert 7.5 <= lon <= 15.5
    assert 54.4 <= lat <= 57.9
    assert products.select("product_id", "unit", "frequency").rows() == [("discharge", "l/s", "unknown")]
    assert pairs.select("station_id", "product_id", "availability").rows() == [
        ("A", "discharge", "available"),
        ("B", "discharge", "unknown"),
    ]
    assert pairs["published_record_start_date"].null_count() == pairs.height
    assert pairs["published_record_end_date"].null_count() == pairs.height


def test_source_descriptions_preserve_unknown_frequency_and_statistic():
    # discharge (sc27) still has exactly one admitted field (SeriesMapping), unlike
    # stage (sc25), which now emits two (see test_stage_descriptions_* below).
    associations = pl.DataFrame([("A", 27, "Vandføring", "l/s")], schema=ASSOCIATION_SCHEMA, orient="row")
    description = describe_associations(associations).descriptions[0]
    facts = description.facts[0]
    assert facts.source_unit.value == "l/s"
    assert facts.frequency.value is None
    assert facts.statistic.value is None
    assert facts.vertical_reference.value is None


def test_stage_descriptions_keep_raw_and_elevation_corrected_as_distinct_records():
    """Step 3 (#798): raw `result` and `resultElevationCorrected` are separate,
    independently identified source series with distinct vertical-reference facts,
    not collapsed into one assumed "the" stage value."""
    from rivretrieve._internal.source_series import EvidenceState

    associations = pl.DataFrame([("A", 25, "Vandstand", "cm")], schema=ASSOCIATION_SCHEMA, orient="row")
    descriptions = describe_associations(associations).descriptions
    assert len(descriptions) == 2
    by_field = {d.native_coordinate: d for d in descriptions}
    assert set(by_field) == {"result", "resultElevationCorrected"}

    raw = by_field["result"].facts[0]
    assert raw.source_unit.value == "cm"
    assert raw.vertical_reference.value == "gauge_zero"
    assert raw.vertical_reference.state == EvidenceState.KNOWN
    assert raw.vertical_datum.state == EvidenceState.SOURCE_SILENT
    assert raw.vertical_datum.value is None

    corrected = by_field["resultElevationCorrected"].facts[0]
    assert corrected.source_unit.value == "cm"
    assert corrected.vertical_reference.value == "above_sea_level"
    assert corrected.vertical_datum.value == "DVR90"
    assert corrected.vertical_datum.state == EvidenceState.KNOWN

    assert by_field["result"].identity.published_id == "result"
    assert by_field["resultElevationCorrected"].identity.published_id == "resultElevationCorrected"
    assert by_field["result"].identity.namespace == by_field["resultElevationCorrected"].identity.namespace
    assert raw.facts_id != corrected.facts_id


def test_series_mappings_reject_out_of_scope_examination_types():
    from rivretrieve._internal.issues import FatalContractError

    with pytest.raises(FatalContractError):
        series_mappings(24)


def test_catalogue_builder_checks_declared_station_identity():
    # dk_vanda is now enrolled in ORIGIN_GATE_ENROLLED_PROVIDERS (Effort #800, step
    # 5: terms of use are now established, see origins.py and
    # research/dk-vanda-source-access.md's "Terms and attribution: resolved
    # (2026-11-14)" section), so this goes through enforce_catalogue_origins/
    # build_catalogue's real enrollment gate, like every other enrolled provider's
    # equivalent test (e.g. test_no_nve_catalogue_certification.py).
    from rivretrieve._internal.catalogue_origins import Field, NativeColumn, enforce_catalogue_origins
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.dk_vanda.origins import STATION_CATALOGUE_ORIGINS

    native = station_native_table([station("A")], retrieved_at=RetrievedAt(datetime(2026, 11, 9, tzinfo=UTC)))
    _, stations, _ = catalogue_tables(native, pl.DataFrame(schema=ASSOCIATION_SCHEMA), checked_on=date(2026, 11, 9))
    wrong = {**STATION_CATALOGUE_ORIGINS, "station_id": Field(NativeColumn("name"))}
    with pytest.raises(FatalContractError, match="station_id"):
        enforce_catalogue_origins(ProviderId("dk_vanda"), wrong, native, stations)


def test_station_origins_round_trip_the_projected_coordinates():
    from rivretrieve._internal.catalogue_origins import validate_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.dk_vanda.origins import STATION_CATALOGUE_ORIGINS

    native = station_native_table([station("A")], retrieved_at=RetrievedAt(datetime(2026, 11, 9, tzinfo=UTC)))
    _, stations, _ = catalogue_tables(native, pl.DataFrame(schema=ASSOCIATION_SCHEMA), checked_on=date(2026, 11, 9))
    assert validate_catalogue_origins(ProviderId("dk_vanda"), STATION_CATALOGUE_ORIGINS, native, stations) == []


def test_catalogue_enrollment_is_now_declared():
    """dk_vanda joined ORIGIN_GATE_ENROLLED_PROVIDERS once catalogue publication
    was unblocked (Effort #800, step 5: terms of use are now established, see
    origins.py and research/dk-vanda-source-access.md's "Terms and attribution:
    resolved (2026-11-14)" section); enforce_catalogue_origins must accept a
    correctly declared mapping rather than refusing on enrollment alone, the
    way it did before this step (see git history for that prior assertion)."""
    from rivretrieve._internal.catalogue_origins import ORIGIN_GATE_ENROLLED_PROVIDERS, enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.dk_vanda.origins import STATION_CATALOGUE_ORIGINS

    assert ProviderId("dk_vanda") in ORIGIN_GATE_ENROLLED_PROVIDERS
    native = station_native_table([station("A")], retrieved_at=RetrievedAt(datetime(2026, 11, 9, tzinfo=UTC)))
    _, stations, _ = catalogue_tables(native, pl.DataFrame(schema=ASSOCIATION_SCHEMA), checked_on=date(2026, 11, 9))
    enforce_catalogue_origins(ProviderId("dk_vanda"), STATION_CATALOGUE_ORIGINS, native, stations)


@pytest.mark.governing(
    "maintenance/catalogue/dk_vanda/official",
    "maintenance/catalogue/dk_vanda/official/selection.json",
)
def test_selected_inputs_publish_deterministic_catalogue(
    retained_evidence_root, catalogue_input_receipt, catalogue_build_inputs, tmp_path
):
    """Build the real dk_vanda packaged catalogue from verified selected originals
    (Effort #800, step 5), mirroring pe_senamhi's
    `test_selected_inputs_publish_deterministic_catalogue`."""
    import json
    import os
    from pathlib import Path

    import polars.testing as pl_testing

    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.dk_vanda.generate_catalogue import main
    from rivretrieve._internal.providers.dk_vanda.origins import STATION_METADATA_NOTICE

    configured = os.environ.get("RIVRETRIEVE_CATALOGUE_PRODUCT_OUTPUT")
    if not configured:
        pytest.fail("Reviewed catalogue generation requires restricted product output.", pytrace=False)
    product_root = Path(configured).resolve()
    selection = "maintenance/catalogue/dk_vanda/official/selection.json"
    from rivretrieve._internal.providers.dk_vanda.generate_catalogue import read_catalogue_sources

    sources = read_catalogue_sources(
        retained_evidence_root, selection_path=selection, input_receipt=catalogue_input_receipt
    )
    build_inputs = catalogue_build_inputs(sources.provenance)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(catalogue_input_receipt.model_dump_json())
    build_path = tmp_path / "build-inputs.json"
    build_path.write_text(build_inputs.model_dump_json())
    outputs = [product_root / "dk_vanda", product_root / "dk_vanda-repeat"]
    for output in outputs:
        assert (
            main(
                [
                    "--evidence-root",
                    str(retained_evidence_root),
                    "--selection",
                    selection,
                    "--input-receipt",
                    str(receipt_path),
                    "--build-inputs",
                    str(build_path),
                    "--out",
                    str(output),
                ]
            )
            == 0
        )
        load_packaged_catalogue_artifact(output, on_issue="raise")
        stations = pl.read_parquet(output / "stations.parquet")
        assert stations["crs"].unique().to_list() == ["EPSG:4326"]
        products = pl.read_parquet(output / "products.parquet")
        assert set(products["product_id"]) == {"discharge", "stage", "temperature"}
        pairs = pl.read_parquet(output / "station_products.parquet")
        assert pairs["published_record_start_date"].null_count() == pairs.height
        assert pairs["published_record_end_date"].null_count() == pairs.height
        assert "unavailable" not in pairs["availability"].to_list()
        provider = json.loads((output / "provider.json").read_bytes())
        assert provider["license"] == "http://publications.europa.eu/resource/authority/licence/CC0"
        assert "Danmarks Milj" in provider["citation"]
        assert STATION_METADATA_NOTICE in json.dumps(
            json.loads((output / "croissant.json").read_bytes()), ensure_ascii=False
        )
        assert not (output / "native.parquet").exists()
    assert {p.name for p in outputs[0].iterdir()} == {p.name for p in outputs[1].iterdir()}
    for path in outputs[0].iterdir():
        repeated = outputs[1] / path.name
        if path.suffix == ".parquet":
            pl_testing.assert_frame_equal(pl.read_parquet(path), pl.read_parquet(repeated))
