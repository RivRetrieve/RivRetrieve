"""Synthetic and governing Austria eHYD catalogue identity and source-fidelity checks."""

import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.at_ehyd.generate_catalogue import (
    ASSOCIATION_SCHEMA,
    build_catalogue,
    describe_associations,
    main,
    owf_associations,
    pegel_aktuell_associations,
    read_catalogue_sources,
    read_original,
    station_native_table,
    write_catalogue,
)


def _lfrz_feature(
    hzbnr: str,
    *,
    lon: float = 15.0,
    lat: float = 48.0,
    name: str = "Synthetic Gauge",
    gewaesser: str = "Synthetic River",
    messstellenart: str = "Oberflächengewässer-Messstelle Durchfluss",
    dienststelle: str | None = "HD-Niederösterreich",
    errichtet: int = 1980,
    aufgelassen: int | None = None,
) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "hzbnr": hzbnr,
            "name": name,
            "gewaesser": gewaesser,
            "messstellenart": messstellenart,
            "dienststelle": dienststelle,
            "errichtet": errichtet,
            "aufgelassen": aufgelassen,
            "symbol": 6,
        },
    }


def _ehyd_owf_feature(hzbnr: str, fentries: list[dict[str, object]]) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [1600000.0, 6100000.0]},
        "properties": {"hzbnr01": hzbnr, "fjson": json.dumps(fentries)},
    }


def _pa_feature(
    hzbnr: int,
    *,
    lon: float = 15.1,
    lat: float = 48.1,
    messstelle: str = "Synthetic PA",
    gewasser: str = "Synthetic River",
    hd: str = "Niederösterreich",
) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "hzbnr": hzbnr,
            "messstelle": messstelle,
            "gewasser": gewasser,
            "hd": hd,
            "parameter": "Q",
            "wert": "1.2",
            "einheit": "m³/s",
        },
    }


def _stammdaten_bytes(hzbnr: str, ezg: str = "55,3", *, seeflaeche: str | None = None) -> bytes:
    lines = [
        "Messstelle:                ;Synthetic",
        f"HZB-Nummer:                ;{hzbnr}",
        f"orogr.Einzugsgebiet [km²]: ;{ezg}",
    ]
    if seeflaeche is not None:
        lines.append(f"Seefläche [km²]:           ;{seeflaeche}")
    return ("\r\n".join(lines) + "\r\n").encode("cp1252")


def _series_bytes(unit_field: str) -> bytes:
    return f"Messstelle:;Synthetic\r\nEinheit:;{unit_field}\r\nWerte:\r\n".encode("cp1252")


def _zip_archive(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_station_native_table_filters_lakes_preserves_seebach_and_owf_coordinates():
    lfrz = {
        "features": [
            _lfrz_feature("201533", lon=11.5, lat=47.0, name="Vinaders", gewaesser="Obernberger Seebach"),
            _lfrz_feature("200337", lon=9.7, lat=47.5, name="Bregenz (Seepegel)", gewaesser="Bodensee"),
            _lfrz_feature("207217", lon=16.4, lat=48.2, name="Wien (Kagraner Brücke)", gewaesser="Alte Donau"),
            _lfrz_feature("208306", lon=15.5, lat=48.3, name="Closed Gauge", gewaesser="Kamp", aufgelassen=2024),
        ]
    }
    ehyd_owf = {
        "features": [
            _ehyd_owf_feature(
                "201533",
                [{"hzbnr": "201533", "file": "Q-Tagesmittel-201533.csv", "ftyp": "owf_abfl_tagesmittel"}],
            ),
            _ehyd_owf_feature(
                "200337",
                [{"hzbnr": "200337", "file": "W-Tagesmittel-200337.csv", "ftyp": "owf_wasserst_tagesmittel"}],
            ),
            _ehyd_owf_feature(
                "207217",
                [{"hzbnr": "207217", "file": "W-Tagesmittel-207217.csv", "ftyp": "owf_wasserst_tagesmittel"}],
            ),
            _ehyd_owf_feature("208306", [{"hzbnr": "208306", "file": "Stammdaten-208306.csv", "ftyp": None}]),
        ]
    }
    ehyd_pa = {
        "features": [
            _pa_feature(201533, lon=99.0, lat=88.0, messstelle="Vinaders PA", gewasser="Obernberger Seebach"),
            _pa_feature(200337, lon=9.7, lat=47.5, messstelle="Bregenz", gewasser="Bodensee"),
            _pa_feature(200675, lon=10.1, lat=47.2, messstelle="Telemetry Only", gewasser="Ill"),
        ]
    }
    zip_bytes = _zip_archive(
        {
            "Stammdaten/Stammdaten-201533.csv": _stammdaten_bytes("201533", "18,4", seeflaeche="0,2"),
            "Stammdaten/Stammdaten-200337.csv": _stammdaten_bytes("200337", "10907", seeflaeche="536"),
            "Stammdaten/Stammdaten-207217.csv": _stammdaten_bytes("207217", "12,0"),
            "Stammdaten/Stammdaten-208306.csv": _stammdaten_bytes("208306", "140,2"),
        }
    )
    native = station_native_table(
        lfrz,
        ehyd_owf,
        ehyd_pa,
        zip_bytes,
        retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC)),
    )
    assert native.data["hzbnr"].to_list() == ["200675", "201533", "208306"]
    # Overlapping gauge 201533 retains LFRZ owf coordinates rather than Pegel Aktuell icon coordinates
    row_201533 = native.data.filter(pl.col("hzbnr") == "201533").row(0, named=True)
    assert (row_201533["longitude"], row_201533["latitude"]) == (11.5, 47.0)
    assert row_201533["in_owf"] is True and row_201533["in_pegel_aktuell"] is True
    # Telemetry-only gauge 200675 uses Pegel Aktuell coordinates and null owf fields
    row_200675 = native.data.filter(pl.col("hzbnr") == "200675").row(0, named=True)
    assert (row_200675["longitude"], row_200675["latitude"]) == (10.1, 47.2)
    assert row_200675["in_owf"] is False and row_200675["orogr.Einzugsgebiet [km²]"] is None


def test_owf_and_pegel_aktuell_associations_handle_empty_units_outages_and_lake_exclusions():
    ehyd_owf = {
        "features": [
            _ehyd_owf_feature(
                "209486",
                [
                    {"hzbnr": "209486", "file": "Q-Tagesmittel-209486.csv", "ftyp": "owf_abfl_tagesmittel"},
                    {"hzbnr": "209486", "file": "W-Tagesmittel-209486.csv", "ftyp": "owf_wasserst_tagesmittel"},
                    {"hzbnr": "209486", "file": "WT-Monatsmittel-209486.csv", "ftyp": "owf_wassertemp_monatsmittel"},
                    {"hzbnr": "209486", "file": "S-Tagesmittel-209486.csv", "ftyp": "owf_schwebst_tagesmittel"},
                ],
            ),
            _ehyd_owf_feature(
                "204388",
                [{"hzbnr": "204388", "file": "W-Tagesmittel-204388.csv", "ftyp": "owf_wasserst_tagesmittel"}],
            ),
        ]
    }
    zip_bytes = _zip_archive(
        {
            "Q-Tagesmittel/Q-Tagesmittel-209486.csv": _series_bytes(" m³/s"),
            "W-Tagesmittel/W-Tagesmittel-209486.csv": _series_bytes(" [cm]"),
            "WT-Monatsmittel/WT-Monatsmittel-209486.csv": _series_bytes(" [ [°C]]"),
            "W-Tagesmittel/W-Tagesmittel-204388.csv": _series_bytes(" []"),
        }
    )
    owf = owf_associations(ehyd_owf, zip_bytes, station_ids={"209486", "204388"})
    assert owf.rows() == [
        ("209486", "owf", "owf_abfl_tagesmittel", "m³/s"),
        ("209486", "owf", "owf_wasserst_tagesmittel", "cm"),
        ("209486", "owf", "owf_wassertemp_monatsmittel", "°C"),
    ]

    # 0-byte pegel_bgis outage and empty pegel_longterm array envelope return empty associations
    assert pegel_aktuell_associations(b"", kind="pegel_bgis", station="201087", station_ids={"201087"}).is_empty()
    empty_lt = json.dumps(
        dict.fromkeys(
            (
                "points_in_time",
                "current_value",
                "min_data",
                "min_year",
                "max_data",
                "max_year",
                "mit_data",
                "p5_data",
                "p95_data",
                "last_year_value",
            ),
            [],
        )
    ).encode()
    assert pegel_aktuell_associations(
        empty_lt, kind="pegel_longterm", station="213801", station_ids={"209486"}
    ).is_empty()
    with pytest.raises(FatalContractError, match="empty"):
        pegel_aktuell_associations(b"", kind="pegel_longterm", station="201087", station_ids={"201087"})

    # Excluded lake with m ü.A is validated and ignored; river gauge with m ü.A raises
    lake_payload = json.dumps({"hzbnr": 200337, "parameter": "Wasserstand", "einheit": "m ü.A"}).encode()
    assert pegel_aktuell_associations(
        lake_payload, kind="pegel_bgis", station="200337", station_ids={"209486"}
    ).is_empty()
    with pytest.raises(FatalContractError, match="unsupported unit"):
        pegel_aktuell_associations(lake_payload, kind="pegel_bgis", station="200337", station_ids={"200337"})


def test_endpoint_scoped_metadata_distinguishes_telemetry_only_absence_from_owf_values():
    from rivretrieve._internal.providers.at_ehyd.station_metadata import project_station_metadata

    lfrz = {"features": [_lfrz_feature("209486", name="Böheimkirchen", gewaesser="Perschling")]}
    ehyd_owf = {"features": [_ehyd_owf_feature("209486", [])]}
    ehyd_pa = {
        "features": [
            _pa_feature(209486, messstelle="Böheimkirchen", gewasser="Perschling"),
            _pa_feature(200675, messstelle="Gargellen", gewasser="Suggiturenbach"),
        ]
    }
    zip_bytes = _zip_archive({"Stammdaten/Stammdaten-209486.csv": _stammdaten_bytes("209486", "55,3")})
    native = station_native_table(
        lfrz, ehyd_owf, ehyd_pa, zip_bytes, retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC))
    )
    stations = pl.DataFrame({"provider_id": ["at_ehyd", "at_ehyd"], "station_id": ["200675", "209486"]})
    metadata = project_station_metadata(native, stations)

    area_telemetry = metadata.filter((pl.col("station_id") == "200675") & (pl.col("attribute_role") == "drainage_area"))
    assert area_telemetry["state"].to_list() == ["no_metadata"]

    area_owf = metadata.filter((pl.col("station_id") == "209486") & (pl.col("attribute_role") == "drainage_area"))
    assert area_owf.select("source_value", "source_dtype", "source_unit", "state").row(0) == (
        '"55,3"',
        "String",
        "km²",
        "value",
    )
    assert metadata.filter(pl.col("attribute_role") == "elevation")["state"].unique().to_list() == ["no_metadata"]


def test_source_descriptions_admit_cm_with_gauge_zero_and_group_stations():
    from rivretrieve._internal.source_series import admission

    associations = pl.DataFrame(
        [
            ("209486", "owf", "owf_wasserst_tagesmittel", "cm"),
            ("200014", "owf", "owf_wasserst_tagesmittel", "cm"),
            ("209486", "owf", "owf_wasserst_tagesmittel", "cm"),
        ],
        schema=ASSOCIATION_SCHEMA,
        orient="row",
    )
    descriptions = describe_associations(associations).descriptions
    assert len(descriptions) == 1
    desc = descriptions[0]
    assert desc.station_ids == ("200014", "209486")
    facts = desc.facts[0]
    assert facts.source_unit.value == "cm"
    assert facts.normalized_unit == "cm"
    assert facts.vertical_reference.value == "gauge_zero"
    assert facts.frequency.value is None
    decision = admission(facts)
    assert decision.status == "supported"
    assert decision.target_unit == "m"
    assert decision.factor == 0.01


def test_provenance_and_offline_catalogue_publication_round_trip(tmp_path: Path):
    from dataclasses import replace

    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        ArchiveMemberReference,
        CatalogueBuildInputs,
        CodeReference,
        FactBinding,
        NativeTableIdentity,
        RecordingReference,
        RetainedInputReceipt,
        RetainedInputReference,
        RetainedInputUse,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.at_ehyd.origins import (
        STATION_CATALOGUE_ORIGINS,
        STATION_METADATA_FIELDS,
        STATION_METADATA_NOTICE,
        build_acquisition_provenance,
    )
    from rivretrieve._internal.providers.at_ehyd.station_metadata import project_station_metadata

    body = b'{"features": []}'
    body_path = tmp_path / "sample.body"
    body_path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    recording = RecordingReference(
        recording_id="synthetic",
        repository_path="sample.body",
        source_url="https://ehyd.gv.at/services/PegelAktuell/json",
        retrieved_at=datetime(2026, 10, 31, tzinfo=UTC),
        media_type="application/json",
        sha256=digest,
    )
    receipt = RetainedInputReceipt(
        schema_version=3,
        code_revision="a" * 40,
        declaration_revision="a" * 40,
        archive_code_revision="b" * 40,
        inputs=(
            RetainedInputReference(
                consumer_path="sample.body",
                archive_repository="https://github.com/RivRetrieve/verification-evidence",
                archive_revision="b" * 40,
                collection_id="synthetic",
                manifest_sha256="c" * 64,
                artifact_id="sample",
                sha256=digest,
                byte_size=len(body),
                role="publisher_original",
            ),
        ),
    )
    assert read_original(tmp_path, recording, input_receipt=receipt) == body

    facts = (
        "source.station.owf_registry",
        "source.station.owf_stammdaten",
        "source.station.pegel_aktuell_registry",
        "source.station.documented_crs",
        "source.station.pegelnullpunkt_definition",
        "source.station_product.owf_associations",
        "source.station_product.pegel_aktuell_associations",
        "source.provider.license",
        "source.provider.citation",
    )
    native_id = NativeTableIdentity(
        location_kind="retained", repository_path="native.parquet", revision="a" * 40, sha256="b" * 64, byte_size=1
    )
    acquisition = AcquisitionRecord(
        acquisition_id="synthetic",
        method="http_request",
        instant_type="retrieval",
        description="Synthetic eHYD source",
        requested_from=(recording.source_url,),
        retrieved_at_start=recording.retrieved_at,
        recording_ids=("synthetic",),
    )
    binding = FactBinding(fact_group="synthetic", facts=facts, source_id="at_ehyd", acquisition_id="synthetic")
    statements = (
        SourceStatement(
            kind="license",
            exact_text="CC BY 4.0",
            recording_id="synthetic",
            fact="source.provider.license",
            verification_status="verified_public_recording",
        ),
        SourceStatement(
            kind="citation",
            exact_text="Datenquelle: ehyd.gv.at",
            recording_id="synthetic",
            fact="source.provider.citation",
            verification_status="verified_public_recording",
        ),
    )
    provenance = build_acquisition_provenance(
        native_id,
        (recording,),
        acquisitions=(acquisition,),
        source_bindings=(binding,),
        statements=statements,
    )

    lfrz = {"features": [_lfrz_feature("209486", name="Böheimkirchen", gewaesser="Perschling")]}
    ehyd_owf = {"features": [_ehyd_owf_feature("209486", [])]}
    ehyd_pa = {"features": [_pa_feature(209486, messstelle="Böheimkirchen", gewasser="Perschling")]}
    zip_bytes = _zip_archive({"Stammdaten/Stammdaten-209486.csv": _stammdaten_bytes("209486", "55,3")})
    rows = station_native_table(
        lfrz, ehyd_owf, ehyd_pa, zip_bytes, retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC))
    )
    associations = pl.DataFrame(
        [("209486", "owf", "owf_abfl_tagesmittel", "m³/s"), ("209486", "pegel_bgis", "Wasserstand", "cm")],
        schema=ASSOCIATION_SCHEMA,
        orient="row",
    )
    catalogue = build_catalogue(
        rows,
        STATION_CATALOGUE_ORIGINS,
        associations=associations,
        checked_on=date(2026, 10, 31),
        provenance=provenance,
    )
    catalogue = replace(catalogue, station_metadata=project_station_metadata(rows, catalogue.stations))
    assert catalogue.provider_info["license"] == "CC BY 4.0"
    assert catalogue.provider_info["citation"] == "Datenquelle: ehyd.gv.at"

    def code(path: str, symbol: str) -> CodeReference:
        return CodeReference(
            repository="https://github.com/RivRetrieve/RivRetrieve",
            repository_path=path,
            symbol=symbol,
            revision="a" * 40,
        )

    prefix = "src/rivretrieve/_internal/providers/at_ehyd/"
    member = ArchiveMemberReference(
        archive_repository="https://github.com/RivRetrieve/verification-evidence",
        archive_revision="a" * 40,
        collection_id="synthetic",
        manifest_sha256="d" * 64,
        artifact_id="native",
        sha256="b" * 64,
        byte_size=1,
        role="derived_input",
    )
    build_inputs = CatalogueBuildInputs(
        build=code(prefix + "generate_catalogue.py", "main"),
        declarations=(
            code(prefix + "origins.py", "build_acquisition_provenance"),
            code(prefix + "generate_catalogue.py", "build_catalogue"),
            code(prefix + "origins.py", "STATION_METADATA_FIELDS"),
            code(prefix + "station_metadata.py", "project_station_metadata"),
        ),
        inputs=(RetainedInputUse(reference=member, usage="native_table", facts=facts),),
    )
    out_dir = tmp_path / "catalogue"
    write_catalogue(
        catalogue,
        out_dir,
        build_inputs=build_inputs,
        native_table=rows,
        metadata_fields=STATION_METADATA_FIELDS,
    )
    loaded = load_packaged_catalogue_artifact(out_dir, on_issue="raise")
    assert loaded.stations["station_id"].to_list() == ["209486"]
    assert loaded.stations["crs"].to_list() == ["EPSG:4326"]
    assert len(loaded.source_descriptions.descriptions) == 2
    assert STATION_METADATA_NOTICE in (out_dir / "croissant.json").read_text("utf-8")


@pytest.mark.governing(
    "maintenance/catalogue/at_ehyd/official",
    "maintenance/catalogue/at_ehyd/official/selection.json",
)
def test_selected_inputs_publish_deterministic_catalogue(
    retained_evidence_root, catalogue_input_receipt, catalogue_build_inputs, tmp_path
):
    import os

    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.at_ehyd.origins import STATION_METADATA_NOTICE

    configured = os.environ.get("RIVRETRIEVE_CATALOGUE_PRODUCT_OUTPUT")
    if not configured:
        pytest.fail("Reviewed catalogue generation requires restricted product output.", pytrace=False)
    product_root = Path(configured).resolve()
    selection = "maintenance/catalogue/at_ehyd/official/selection.json"
    sources = read_catalogue_sources(
        retained_evidence_root, selection_path=selection, input_receipt=catalogue_input_receipt
    )
    build_inputs = catalogue_build_inputs(sources.provenance)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(catalogue_input_receipt.model_dump_json())
    build_path = tmp_path / "build-inputs.json"
    build_path.write_text(build_inputs.model_dump_json())
    outputs = [product_root / "at_ehyd", product_root / "at_ehyd-repeat"]
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
        assert stations.height == 746
        assert stations["crs"].unique().to_list() == ["EPSG:4326"]
        products = pl.read_parquet(output / "products.parquet")
        assert products.height == 11
        pairs = pl.read_parquet(output / "station_products.parquet")
        assert pairs.height == 746 * 11
        assert pairs.filter(pl.col("availability") == "available").height == 4837
        assert pairs["published_record_start_date"].null_count() == pairs.height
        assert pairs["published_record_end_date"].null_count() == pairs.height
        assert "unavailable" not in pairs["availability"].to_list()
        provider = json.loads((output / "provider.json").read_bytes())
        assert provider["license"] == "CC BY 4.0"
        assert provider["citation"] == "Datenquelle: ehyd.gv.at"
        assert STATION_METADATA_NOTICE in json.dumps(
            json.loads((output / "croissant.json").read_bytes()), ensure_ascii=False
        )
        assert not (output / "native.parquet").exists()
    assert {p.name for p in outputs[0].iterdir()} == {p.name for p in outputs[1].iterdir()}
    for path in outputs[0].iterdir():
        repeated = outputs[1] / path.name
        if path.suffix == ".parquet":
            assert_frame_equal(pl.read_parquet(path), pl.read_parquet(repeated))
        assert path.read_bytes() == repeated.read_bytes()
