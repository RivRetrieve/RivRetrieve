"""Synthetic Estonia (`ee_est`) station catalogue, origin, and metadata checks."""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionRecord,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    SourceStatement,
)
from rivretrieve._internal.catalogue_origins import (
    Field,
    NativeColumn,
    enforce_catalogue_origins,
    validate_catalogue_origins,
)
from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ee_est.generate_catalogue import (
    catalogue_tables,
    parse_jaam_kood,
    station_native_table,
    station_product_associations,
)
from rivretrieve._internal.providers.ee_est.origins import (
    STATION_CATALOGUE_ORIGINS,
    build_acquisition_provenance,
)
from rivretrieve._internal.providers.ee_est.series import PRODUCT_SPECS, describe_associations
from rivretrieve._internal.providers.ee_est.station_metadata import project_station_metadata


def _em_station(code: str, *, name: str = "Ahja jõgi: Ahja", area: float = 896.51, stype: str = "HYDROLOGICAL") -> dict:
    return {"code": code, "name": name, "area": area, "type": stype}


def _sj_station(
    kkr_kood: str,
    *,
    kood: str | None = "41061",
    nimi: str = "Ahja HJ",
    veekogu_nimi: str = "Ahja jõgi",
    wb_type: str = "Jõgi",
    x: float = 681450.0,
    y: float = 6456890.0,
    seiretyyp: str = "HJ",
) -> dict:
    return {
        "kkr_kood": kkr_kood,
        "kood": kood,
        "nimi": nimi,
        "veekogu_nimi": veekogu_nimi,
        "veekogu_tyyp_selg": wb_type,
        "kesk_x": x,
        "kesk_y": y,
        "seiretyyp": seiretyyp,
        "merepinnast": None,
    }


def _provenance():
    ts = datetime(2026, 11, 23, tzinfo=UTC)
    rec = RecordingReference(
        recording_id="estmodel-stations-500",
        repository_path="web/estmodel-stations-500.body",
        source_url="https://estmodel.envir.ee/stations?limit=500",
        retrieved_at=ts,
        media_type="application/json",
        sha256="a" * 64,
    )
    return build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path="maintenance/catalogue/ee_est/official/native.parquet",
            revision="b" * 40,
            sha256="c" * 64,
            byte_size=20,
        ),
        (rec,),
        acquisitions=(
            AcquisitionRecord(
                acquisition_id="estmodel-stations-500",
                method="http_request",
                instant_type="retrieval",
                description="EstModel stations list",
                requested_from=("https://estmodel.envir.ee/stations?limit=500",),
                retrieved_at_start=ts,
                recording_ids=("estmodel-stations-500",),
            ),
        ),
        source_bindings=(
            FactBinding(
                fact_group="stations",
                source_id="ee_est",
                acquisition_id="estmodel-stations-500",
                facts=(
                    "source.station.registry",
                    "source.station.estmodel_registry",
                    "source.station.drainage_area",
                    "source.station.drainage_area_unit",
                    "source.station_product.associations",
                    "source.series.fields",
                    "source.series.hourly_fields",
                    "source.provider.terms",
                    "source.provider.attribution",
                ),
            ),
        ),
        statements=(
            SourceStatement(
                kind="license",
                exact_text="CC BY 4.0",
                recording_id="estmodel-stations-500",
                fact="source.provider.terms",
                verification_status="verified_public_recording",
            ),
            SourceStatement(
                kind="citation",
                exact_text="Estonian Environment Agency (Keskkonnaagentuur)",
                recording_id="estmodel-stations-500",
                fact="source.provider.attribution",
                verification_status="verified_public_recording",
            ),
        ),
    )


def test_parse_jaam_kood_handles_semicolons_and_null() -> None:
    assert parse_jaam_kood(None) == ()
    assert parse_jaam_kood("41061") == (41061,)
    assert parse_jaam_kood("41022; 41960") == (41022, 41960)
    with pytest.raises(FatalContractError, match="non-numeric"):
        parse_jaam_kood("41022; abc")


def test_native_table_filters_lakes_and_hydrochemical_and_resolves_crosswalk() -> None:
    native = station_native_table(
        [
            _em_station("SJA8821000"),
            _em_station("SJA5524000", name="Emajõgi: Rannu-Jõesuu", area=3364.0),
            _em_station("SJA5000000", name="Peipsi järv: Mustvee", area=42900.0),
            _em_station("SJA0664000", stype="HYDROCHEMICAL"),
            _em_station("SJB4433000", name="Keila jõgi: Ardi", area=496.0),
        ],
        [
            _sj_station("SJA8821000", kood="41061"),
            _sj_station("SJA5524000", kood="41022; 41960", nimi="Rannu-Jõesuu HJ", veekogu_nimi="Emajõgi"),
            _sj_station("SJA5000000", kood="41925", wb_type="Looduslik järv"),
            _sj_station("SJA0664000", kood="41066", seiretyyp="HJ"),
            _sj_station("SJB4433000", kood="41106", nimi="Ardi HJ", veekogu_nimi="Keila jõgi"),
        ],
        active_fh_codes={41061, 41022},
        retrieved_at=RetrievedAt(datetime(2026, 11, 23, tzinfo=UTC)),
    )
    assert native.data["kkr_kood"].to_list() == ["SJA5524000", "SJA8821000", "SJB4433000"]
    assert native.data["jaam_kood"].to_list() == [41022, 41061, None]


def test_native_table_rejects_out_of_estonia_coordinates() -> None:
    with pytest.raises(FatalContractError, match="L-EST97 bounds"):
        station_native_table(
            [_em_station("SJA8821000")],
            [_sj_station("SJA8821000", x=10.0, y=58.0)],
            active_fh_codes={41061},
            retrieved_at=RetrievedAt(datetime(2026, 11, 23, tzinfo=UTC)),
        )


def test_catalogue_projects_wgs84_and_covers_all_18_products() -> None:
    native = station_native_table(
        [_em_station("SJA8821000")],
        [_sj_station("SJA8821000", kood="41061")],
        active_fh_codes={41061},
        retrieved_at=RetrievedAt(datetime(2026, 11, 23, tzinfo=UTC)),
    )
    em_avail = {("SJA8821000", s.product_id): "em" for s in PRODUCT_SPECS if s.source_api == "estmodel"}
    fh_avail = {("SJA8821000", s.product_id): "fh" for s in PRODUCT_SPECS if s.source_api == "f_hydroseire"}
    associations = station_product_associations(
        native,
        em_available=em_avail,
        em_unavailable={},
        fh_available=fh_avail,
        fh_unavailable={},
    )
    products, stations, pairs = catalogue_tables(native, associations, checked_on=date(2026, 11, 23))
    assert products.height == 18
    assert set(products.filter(pl.col("observed_property") == "stage")["unit"]) == {"m"}
    assert stations["crs"].to_list() == ["EPSG:4326"]
    lon, lat = stations.select("longitude", "latitude").row(0)
    assert 21.5 <= lon <= 28.5 and 57.5 <= lat <= 59.8
    assert pairs.height == 18
    assert set(pairs["availability"]) == {"available"}
    assert validate_catalogue_origins(ProviderId("ee_est"), STATION_CATALOGUE_ORIGINS, native, stations) == []
    with pytest.raises(FatalContractError, match="station_id"):
        enforce_catalogue_origins(
            ProviderId("ee_est"),
            {**STATION_CATALOGUE_ORIGINS, "station_id": Field(NativeColumn("nimi"))},
            native,
            stations,
        )
    descriptions = describe_associations(associations)
    assert len(descriptions.descriptions) == 18
    metadata = project_station_metadata(native, stations)
    roles = dict(metadata.select("attribute_role", "state").iter_rows())
    assert roles == {
        "station_name": "value",
        "water_body_name": "value",
        "drainage_area": "value",
        "elevation": "no_metadata",
    }
    prov = _provenance()
    assert prov.provider_id == "ee_est"


@pytest.mark.governing(
    "maintenance/catalogue/ee_est/official",
    "maintenance/catalogue/ee_est/official/selection.json",
)
def test_selected_inputs_publish_deterministic_catalogue(
    retained_evidence_root, catalogue_input_receipt, catalogue_build_inputs, tmp_path
) -> None:
    """Build the real ee_est packaged catalogue deterministically from verified originals."""
    import json
    import os
    from pathlib import Path

    import polars.testing as pl_testing

    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.ee_est.generate_catalogue import main, read_catalogue_sources
    from rivretrieve._internal.providers.ee_est.origins import STATION_METADATA_NOTICE

    configured = os.environ.get("RIVRETRIEVE_CATALOGUE_PRODUCT_OUTPUT")
    if not configured:
        pytest.fail("Reviewed catalogue generation requires restricted product output.", pytrace=False)
    product_root = Path(configured).resolve()
    selection = "maintenance/catalogue/ee_est/official/selection.json"
    sources = read_catalogue_sources(
        retained_evidence_root, selection_path=selection, input_receipt=catalogue_input_receipt
    )
    build_inputs = catalogue_build_inputs(sources.provenance)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(catalogue_input_receipt.model_dump_json())
    build_path = tmp_path / "build-inputs.json"
    build_path.write_text(build_inputs.model_dump_json())
    outputs = [product_root / "ee_est", product_root / "ee_est-repeat"]
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
        assert stations.height == 60
        assert stations["crs"].unique().to_list() == ["EPSG:4326"]
        products = pl.read_parquet(output / "products.parquet")
        assert products.height == 18
        pairs = pl.read_parquet(output / "station_products.parquet")
        assert pairs.height == 1080
        assert pairs.filter(pl.col("availability") == "available").height == 1032
        assert pairs.filter(pl.col("availability") == "unavailable").height == 48
        assert pairs.filter(pl.col("availability") == "unknown").height == 0
        provider = json.loads((output / "provider.json").read_bytes())
        assert provider["license"] == "CC BY 4.0"
        assert provider["citation"] == "Estonian Environment Agency (Keskkonnaagentuur)"
        assert STATION_METADATA_NOTICE in json.dumps(
            json.loads((output / "croissant.json").read_bytes()), ensure_ascii=False
        )
        assert not (output / "native.parquet").exists()
    assert {p.name for p in outputs[0].iterdir()} == {p.name for p in outputs[1].iterdir()}
    for path in outputs[0].iterdir():
        repeated = outputs[1] / path.name
        if path.suffix == ".parquet":
            pl_testing.assert_frame_equal(pl.read_parquet(path), pl.read_parquet(repeated))
