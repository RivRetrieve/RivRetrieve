"""Synthetic and governing Argentina INA Alerta5 catalogue identity and source-fidelity checks."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionRecord,
    ArchiveMemberReference,
    CatalogueBuildInputs,
    CodeReference,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    RetainedInputReceipt,
    RetainedInputUse,
    SourceStatement,
)
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.native import RetrievedAt, write_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ar_ina.generate_catalogue import (
    IN_SCOPE_SERIES_SPECS,
    SPECS_BY_VAR_ID,
    build_catalogue,
    describe_associations,
    main,
    read_catalogue_sources,
    read_native_sources,
    read_original,
    selected_supporting_inputs,
    station_native_table_and_associations,
    write_catalogue,
)
from rivretrieve._internal.providers.ar_ina.origins import (
    STATION_CATALOGUE_ORIGINS,
    STATION_METADATA_FIELDS,
    STATION_METADATA_NOTICE,
    build_acquisition_provenance,
)


def _estacion(
    station_id: int,
    *,
    nombre: str | None = "Timbúes",
    rio: str | None = "Paraná",
    lon: float | None = -60.715,
    lat: float | None = -32.652,
    tabla: str = "alturas_prefe",
    pais: str | None = "ARGENTINA",
    propietario: str | None = "PNA",
    tipo: str | None = "A",
    cero_ign: float | None = 3.19,
    altitud: float | None = 12.0,
    real: bool | None = True,
    has_obs: bool | None = True,
) -> dict[str, object]:
    geom = None if lon is None or lat is None else {"type": "Point", "coordinates": [lon, lat]}
    return {
        "id": station_id,
        "nombre": nombre,
        "rio": rio,
        "geom": geom,
        "tabla": tabla,
        "pais": pais,
        "propietario": propietario,
        "tipo": tipo,
        "cero_ign": cero_ign,
        "altitud": altitud,
        "real": real,
        "has_obs": has_obs,
    }


def _serie(
    series_id: int,
    estacion: dict[str, object],
    *,
    var_id: int,
    proc_id: int | None = None,
    unit_id: int | None = None,
    unit_abrev: str | None = None,
    timestart: str | None = "1990-01-01T00:00:00.000Z",
    timeend: str | None = "2026-11-05T00:00:00.000Z",
) -> dict[str, object]:
    spec = SPECS_BY_VAR_ID[var_id]
    resolved_proc = spec.proc_id if proc_id is None else proc_id
    resolved_unit_id = spec.expected_unit_id if unit_id is None else unit_id
    resolved_abrev = spec.expected_unit_abrev if unit_abrev is None else unit_abrev
    date_range = (
        {"timestart": None, "timeend": None, "count": "0"}
        if timestart is None
        else {"timestart": timestart, "timeend": timeend, "count": "10"}
    )
    return {
        "tipo": "puntual",
        "id": series_id,
        "estacion": estacion,
        "var": {"id": var_id},
        "procedimiento": {"id": resolved_proc},
        "unidades": {"id": resolved_unit_id, "abrev": resolved_abrev},
        "date_range": date_range,
    }


def _empty_series_map() -> dict[int, object]:
    return {spec.var_id: {"rows": []} for spec in IN_SCOPE_SERIES_SPECS}


def test_station_native_table_filters_virtual_mareographic_and_simulated_while_retaining_null_geom():
    gauge_main = _estacion(29, nombre="  Timbúes ", rio="null")
    gauge_uruguay = _estacion(1699, nombre="Nueva Palmira", rio="Uruguay", pais="URUGUAY")
    gauge_null_geom = _estacion(96, nombre="Colorado", rio="BERMEJO", lon=None, lat=None, cero_ign=None)
    virtual_false = _estacion(350, nombre=None, tabla="estaciones_virtuales", real=False, tipo="V")
    virtual_tipo = _estacion(900, nombre="Nodo Modelo", tabla="sat2", real=True, tipo="V")
    mareographic_shn = _estacion(801, nombre="Buenos Aires SHN", tabla="estaciones_shn")
    mareographic_pvn = _estacion(802, nombre="Canal Punta Indio", tabla="estaciones_pvnymm")
    unwitnessed_gauge = _estacion(777, nombre="Sin Series Observadas")

    estaciones = [
        gauge_main,
        gauge_uruguay,
        virtual_false,
        virtual_tipo,
        mareographic_shn,
        mareographic_pvn,
        unwitnessed_gauge,
    ]
    series_map = _empty_series_map()
    series_map[40] = {
        "rows": [
            _serie(1001, gauge_main, var_id=40),
            # Simulated procedure 4 is out of scope even on a physical gauge.
            _serie(1002, unwitnessed_gauge, var_id=40, proc_id=4, unit_id=999, unit_abrev="ignored"),
            # Undated shell (timestart=None) is out of scope.
            _serie(1003, unwitnessed_gauge, var_id=40, timestart=None),
            # Excluded virtual and mareographic stations never enter canonical scope.
            _serie(1004, virtual_false, var_id=40),
            _serie(1005, virtual_tipo, var_id=40),
            _serie(1006, mareographic_shn, var_id=40),
            _serie(1007, mareographic_pvn, var_id=40),
        ]
    }
    series_map[39] = {
        "rows": [
            _serie(2001, gauge_main, var_id=39),
            _serie(2002, gauge_uruguay, var_id=39),
            _serie(2003, gauge_null_geom, var_id=39),
        ]
    }

    retrieved = RetrievedAt(datetime(2026, 11, 6, 12, 0, tzinfo=UTC))
    native, associations = station_native_table_and_associations(
        estaciones,
        series_map,
        retrieved_at=retrieved,
    )

    assert native.data["id"].to_list() == ["1699", "29", "96"]
    row_29 = native.data.filter(pl.col("id") == "29").row(0, named=True)
    assert row_29["nombre"] == "  Timbúes "
    assert row_29["rio"] == "null"
    assert row_29["in_estaciones_endpoint"] is True

    row_96 = native.data.filter(pl.col("id") == "96").row(0, named=True)
    assert row_96["latitude"] is None
    assert row_96["longitude"] is None
    assert row_96["in_estaciones_endpoint"] is False

    assert associations.select("station_id", "product_id", "series_id").rows() == [
        ("1699", "stage_daily_mean", 2002),
        ("29", "discharge_daily_mean", 1001),
        ("29", "stage_daily_mean", 2001),
        ("96", "stage_daily_mean", 2003),
    ]


def test_station_native_table_fails_closed_on_upstream_contract_drift():
    retrieved = RetrievedAt(datetime(2026, 11, 6, 12, 0, tzinfo=UTC))
    gauge = _estacion(29)

    with pytest.raises(FatalContractError, match="13 in-scope variable captures"):
        station_native_table_and_associations([gauge], {40: {"rows": []}}, retrieved_at=retrieved)

    # Attribute drift between estaciones and series.estacion fails closed.
    series_drift = _empty_series_map()
    drifted_embedded = {**gauge, "rio": "Otro Río"}
    series_drift[40] = {"rows": [_serie(1, drifted_embedded, var_id=40)]}
    with pytest.raises(FatalContractError, match="attributes disagree"):
        station_native_table_and_associations([gauge], series_drift, retrieved_at=retrieved)

    # Coordinate-bearing station absent from estaciones endpoint fails closed.
    series_missing_endpoint = _empty_series_map()
    series_missing_endpoint[40] = {"rows": [_serie(1, gauge, var_id=40)]}
    with pytest.raises(FatalContractError, match="absent from estaciones snapshot"):
        station_native_table_and_associations([], series_missing_endpoint, retrieved_at=retrieved)

    # Unexpected observational procedure (e.g. proc_id=2 on var_id=40) fails closed.
    series_bad_proc = _empty_series_map()
    series_bad_proc[40] = {"rows": [_serie(1, gauge, var_id=40, proc_id=2)]}
    with pytest.raises(FatalContractError, match="Unexpected observational procedure"):
        station_native_table_and_associations([gauge], series_bad_proc, retrieved_at=retrieved)

    # Unexpected unit fails closed.
    series_bad_unit = _empty_series_map()
    series_bad_unit[40] = {"rows": [_serie(1, gauge, var_id=40, unit_id=11, unit_abrev="m")]}
    with pytest.raises(FatalContractError, match="Unsupported INA unit"):
        station_native_table_and_associations([gauge], series_bad_unit, retrieved_at=retrieved)

    # Duplicate series for the same (station_id, product_id) fails closed.
    series_dup = _empty_series_map()
    series_dup[40] = {"rows": [_serie(1, gauge, var_id=40), _serie(2, gauge, var_id=40)]}
    with pytest.raises(FatalContractError, match="Conflicting INA series IDs"):
        station_native_table_and_associations([gauge], series_dup, retrieved_at=retrieved)


def test_build_and_write_catalogue_packages_stage_gauge_zero_and_metadata_projection(tmp_path):
    gauge_29 = _estacion(29, nombre="  Timbúes ", rio="null")
    gauge_96 = _estacion(96, nombre="Colorado", rio=None, lon=None, lat=None)
    series_map = _empty_series_map()
    series_map[40] = {"rows": [_serie(1001, gauge_29, var_id=40)]}
    series_map[39] = {"rows": [_serie(2001, gauge_29, var_id=39), _serie(2002, gauge_96, var_id=39)]}

    retrieved = RetrievedAt(datetime(2026, 11, 6, 12, 0, tzinfo=UTC))
    native, associations = station_native_table_and_associations([gauge_29], series_map, retrieved_at=retrieved)

    descriptions = describe_associations(associations)
    by_product = {item.product_id: item for item in descriptions.descriptions}
    assert set(by_product) == {"discharge_daily_mean", "stage_daily_mean"}
    assert by_product["discharge_daily_mean"].facts[0].source_unit.value == "m^3/s"
    assert by_product["discharge_daily_mean"].facts[0].normalized_unit == "m3/s"
    assert by_product["discharge_daily_mean"].facts[0].vertical_reference.state == "not_established"
    assert by_product["stage_daily_mean"].facts[0].vertical_reference.value == "gauge_zero"

    facts = (
        "source.station.estaciones_registry",
        "source.station.series_embedded_estacion",
        "source.station.openapi_estacion_schema",
        "source.station.documented_crs",
        "source.product.variables_unidades_procedimientos",
        "source.station_product.series_associations",
        "source.station.cero_ign_definition",
        "source.provider.license",
    )
    recording = RecordingReference(
        recording_id="rec-1",
        repository_path="maintenance/catalogue/ar_ina/official/web/synthetic.body",
        source_url="https://alerta.ina.gob.ar/a5/obs/puntual/estaciones",
        retrieved_at=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
        media_type="application/json",
        sha256="a" * 64,
    )
    provenance = build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path="maintenance/catalogue/ar_ina/official/native.parquet",
            revision="b" * 40,
            sha256="c" * 64,
            byte_size=128,
        ),
        (recording,),
        acquisitions=(
            AcquisitionRecord(
                acquisition_id="ar-ina-estaciones-snapshot",
                description="Synthetic INA capture",
                method="http_request",
                requested_from=("https://alerta.ina.gob.ar/a5/obs/puntual/estaciones",),
                instant_type="retrieval",
                retrieved_at_start=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
                recording_ids=("rec-1",),
            ),
        ),
        source_bindings=(
            FactBinding(
                fact_group="synthetic_facts",
                facts=facts,
                source_id="ar_ina",
                acquisition_id="ar-ina-estaciones-snapshot",
            ),
        ),
        statements=(
            SourceStatement(
                kind="license",
                exact_text="Creative Commons Atribución 4.0 Internacional",
                recording_id="rec-1",
                fact="source.provider.license",
            ),
        ),
    )

    catalogue = build_catalogue(
        native,
        STATION_CATALOGUE_ORIGINS,
        associations=associations,
        checked_on=date(2026, 11, 6),
        provenance=provenance,
    )
    assert catalogue.provider_info["license"] == "Creative Commons Atribución 4.0 Internacional"
    assert catalogue.provider_info["citation"] is None
    assert catalogue.products.height == 13
    assert catalogue.stations.height == 2
    assert catalogue.station_products.height == 26
    assert catalogue.station_products.filter(pl.col("availability") == "available").height == 3
    assert "unavailable" not in catalogue.station_products["availability"].to_list()

    def code(path: str, symbol: str) -> CodeReference:
        return CodeReference(
            repository="https://github.com/RivRetrieve/RivRetrieve",
            repository_path=path,
            symbol=symbol,
            revision="b" * 40,
        )

    prefix = "src/rivretrieve/_internal/providers/ar_ina/"
    member = ArchiveMemberReference(
        archive_repository="https://github.com/RivRetrieve/verification-evidence",
        archive_revision="d" * 40,
        collection_id="synthetic",
        manifest_sha256="e" * 64,
        artifact_id="native",
        sha256="c" * 64,
        byte_size=128,
        role="derived_input",
    )
    build_inputs = CatalogueBuildInputs(
        build=code(prefix + "generate_catalogue.py", "write_catalogue"),
        declarations=(
            code(prefix + "origins.py", "build_acquisition_provenance"),
            code(prefix + "origins.py", "STATION_METADATA_FIELDS"),
            code(prefix + "origins.py", "STATION_METADATA_NOTICE"),
            code(prefix + "generate_catalogue.py", "build_catalogue"),
        ),
        inputs=(RetainedInputUse(reference=member, usage="native_table", facts=facts),),
    )
    out_dir = tmp_path / "catalogue"
    write_catalogue(
        catalogue,
        out_dir,
        build_inputs=build_inputs,
        native_table=native,
        metadata_fields=STATION_METADATA_FIELDS,
    )

    loaded = load_packaged_catalogue_artifact(out_dir, on_issue="raise")
    assert loaded.stations["station_id"].to_list() == ["29", "96"]
    assert loaded.stations["crs"].to_list() == ["EPSG:4326", "EPSG:4326"]
    assert STATION_METADATA_NOTICE in (out_dir / "croissant.json").read_text("utf-8")

    metadata_df = pl.read_parquet(out_dir / "station_metadata.parquet")
    row_29_rio = metadata_df.filter(
        (pl.col("station_id") == "29") & (pl.col("attribute_role") == "water_body_name")
    ).row(0, named=True)
    assert row_29_rio["state"] == "value"
    assert json.loads(str(row_29_rio["source_value"])) == "null"
    row_96_rio = metadata_df.filter(
        (pl.col("station_id") == "96") & (pl.col("attribute_role") == "water_body_name")
    ).row(0, named=True)
    assert row_96_rio["state"] == "source_null"
    row_96_area = metadata_df.filter(
        (pl.col("station_id") == "96") & (pl.col("attribute_role") == "drainage_area")
    ).row(0, named=True)
    assert row_96_area["state"] == "no_metadata"


def test_read_sources_and_cli_enforce_selection_and_output_boundaries(tmp_path):
    evidence = tmp_path / "evidence"
    web_dir = evidence / "maintenance/catalogue/ar_ina/official/web"
    web_dir.mkdir(parents=True)

    gauge = _estacion(29)
    bodies: dict[str, tuple[bytes, str, str, int | None]] = {
        "estaciones": (json.dumps([gauge]).encode(), "application/json", "estaciones", None),
        "portal": (
            b"<html>projection: 'EPSG:4326' y cero de escala</html>",
            "text/html",
            "portal_map",
            None,
        ),
        "openapi": (
            b"components:\n  schemas:\n    Estacion:\n      enum: [Point]\n",
            "text/yaml",
            "openapi_spec",
            None,
        ),
        "terms": (
            "Licencia Creative Commons Atribución 4.0 Internacional".encode(),
            "text/html",
            "terms_html",
            None,
        ),
    }
    for spec in IN_SCOPE_SERIES_SPECS:
        rows = [_serie(1000 + spec.var_id, gauge, var_id=spec.var_id)] if spec.var_id in {39, 40} else []
        bodies[f"var-{spec.var_id}"] = (
            json.dumps({"rows": rows}).encode(),
            "application/json",
            "series_var",
            spec.var_id,
        )

    captures = []
    input_members = []
    for key, (payload, media_type, kind, var_id) in bodies.items():
        rel_body = f"maintenance/catalogue/ar_ina/official/web/{key}.body"
        rel_receipt = f"maintenance/catalogue/ar_ina/official/web/{key}.receipt.json"
        (evidence / rel_body).write_bytes(payload)
        receipt_bytes = json.dumps({"sha256": hashlib.sha256(payload).hexdigest()}).encode()
        (evidence / rel_receipt).write_bytes(receipt_bytes)
        digest = hashlib.sha256(payload).hexdigest()
        rec_ref = {
            "recording_id": f"rec-{key}",
            "repository_path": rel_body,
            "source_url": f"https://alerta.ina.gob.ar/a5/{key}",
            "retrieved_at": "2026-11-06T12:00:00Z",
            "media_type": media_type,
            "sha256": digest,
        }
        capture_entry: dict[str, object] = {
            "kind": kind,
            "body": rel_body,
            "receipt": rel_receipt,
            "recording": rec_ref,
        }
        if var_id is not None:
            capture_entry["var_id"] = var_id
        captures.append(capture_entry)
        for rel_path, raw_bytes, role, suffix in (
            (rel_body, payload, "publisher_original", "body"),
            (rel_receipt, receipt_bytes, "acquisition_receipt", "receipt"),
        ):
            input_members.append(
                {
                    "consumer_path": rel_path,
                    "archive_repository": "https://github.com/RivRetrieve/verification-evidence",
                    "archive_revision": "a" * 40,
                    "collection_id": "ar_ina-access",
                    "manifest_sha256": "b" * 64,
                    "artifact_id": f"{key}-{suffix}",
                    "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                    "byte_size": len(raw_bytes),
                    "role": role,
                }
            )

    native, _ = station_native_table_and_associations(
        [gauge],
        {spec.var_id: json.loads(bodies[f"var-{spec.var_id}"][0]) for spec in IN_SCOPE_SERIES_SPECS},
        retrieved_at=RetrievedAt(datetime(2026, 11, 6, 12, 0, tzinfo=UTC)),
    )
    rel_native = "maintenance/catalogue/ar_ina/official/native.parquet"
    write_native_table(native, evidence / rel_native)
    native_bytes = (evidence / rel_native).read_bytes()
    input_members.append(
        {
            "consumer_path": rel_native,
            "archive_repository": "https://github.com/RivRetrieve/verification-evidence",
            "archive_revision": "a" * 40,
            "collection_id": "ar_ina-native",
            "manifest_sha256": "c" * 64,
            "artifact_id": "native.parquet",
            "sha256": hashlib.sha256(native_bytes).hexdigest(),
            "byte_size": len(native_bytes),
            "role": "derived_input",
        }
    )

    data_facts = (
        "source.station.estaciones_registry",
        "source.station.series_embedded_estacion",
        "source.station.openapi_estacion_schema",
        "source.station.documented_crs",
        "source.product.variables_unidades_procedimientos",
        "source.station_product.series_associations",
        "source.station.cero_ign_definition",
    )
    selection_doc = {
        "checked_on": "2026-11-06",
        "native_table": rel_native,
        "native_revision": "d" * 40,
        "captures": captures,
        "publication_acquisitions": [
            {
                "acquisition_id": "ar-ina-estaciones-snapshot",
                "description": "Synthetic data campaign",
                "method": "http_campaign",
                "requested_from": ["https://alerta.ina.gob.ar/a5"],
                "instant_type": "retrieval_interval",
                "retrieved_at_start": "2026-11-06T12:00:00Z",
                "retrieved_at_end": "2026-11-06T12:00:00Z",
                "recording_ids": [
                    c["recording"]["recording_id"] for c in captures if c["recording"]["recording_id"] != "rec-terms"
                ],
            },
            {
                "acquisition_id": "ar-ina-argentina-gob-terminos",
                "description": "Synthetic Argentina.gob.ar terms capture",
                "method": "http_request",
                "requested_from": ["https://alerta.ina.gob.ar/a5/terms"],
                "instant_type": "retrieval",
                "retrieved_at_start": "2026-11-06T12:00:00Z",
                "recording_ids": ["rec-terms"],
            },
        ],
        "source_bindings": [
            {
                "fact_group": "data_facts",
                "facts": list(data_facts),
                "source_id": "ar_ina",
                "acquisition_id": "ar-ina-estaciones-snapshot",
            },
            {
                "fact_group": "license_fact",
                "facts": ["source.provider.license"],
                "source_id": "ar_ina",
                "acquisition_id": "ar-ina-argentina-gob-terminos",
            },
        ],
        "statements": [
            {
                "kind": "license",
                "exact_text": "Creative Commons Atribución 4.0 Internacional",
                "recording_id": "rec-terms",
                "fact": "source.provider.license",
            }
        ],
    }
    rel_selection = "maintenance/catalogue/ar_ina/official/selection.json"
    selection_bytes = json.dumps(selection_doc).encode()
    (evidence / rel_selection).write_bytes(selection_bytes)

    receipt = RetainedInputReceipt.model_validate(
        {
            "schema_version": 3,
            "code_revision": "d" * 40,
            "declaration_revision": "d" * 40,
            "archive_code_revision": "a" * 40,
            "inputs": input_members,
            "declaration_inputs": [
                {
                    "consumer_path": rel_selection,
                    "declaration": {
                        "repository": "https://github.com/RivRetrieve/verification-evidence",
                        "repository_path": "declarations/ar_ina/catalogue.json",
                        "symbol": None,
                        "revision": "a" * 40,
                    },
                    "sha256": hashlib.sha256(selection_bytes).hexdigest(),
                    "byte_size": len(selection_bytes),
                }
            ],
            "support_inputs": [],
        }
    )

    recomputed = read_native_sources(evidence, selection_path=rel_selection, input_receipt=receipt)
    assert recomputed.data.equals(native.data)

    loaded_sources = read_catalogue_sources(evidence, selection_path=rel_selection, input_receipt=receipt)
    assert loaded_sources.native_table.data.equals(native.data)
    support_map = selected_supporting_inputs(loaded_sources.provenance, selection_doc)
    assert "maintenance/catalogue/ar_ina/official/web/estaciones.receipt.json" in support_map

    receipt_file = tmp_path / "receipt.json"
    receipt_file.write_text(receipt.model_dump_json())
    native_out = tmp_path / "native-out"
    assert (
        main(
            [
                "--evidence-root",
                str(evidence),
                "--selection",
                rel_selection,
                "--input-receipt",
                str(receipt_file),
                "--native-only",
                "--out",
                str(native_out),
            ]
        )
        == 0
    )
    assert (native_out / "native.parquet").is_file()

    # Output inside evidence_root or already-existing output directory fails closed.
    with pytest.raises(FatalContractError, match="new path separate from retained inputs"):
        main(
            [
                "--evidence-root",
                str(evidence),
                "--input-receipt",
                str(receipt_file),
                "--native-only",
                "--out",
                str(native_out),
            ]
        )
    git_checkout = tmp_path / "checkout"
    (git_checkout / ".git").mkdir(parents=True)
    with pytest.raises(FatalContractError, match="outside source checkouts"):
        main(
            [
                "--evidence-root",
                str(evidence),
                "--input-receipt",
                str(receipt_file),
                "--native-only",
                "--out",
                str(git_checkout / "out"),
            ]
        )

    # Unselected original fails closed in read_original.
    unselected = RecordingReference.model_validate(
        {
            **captures[0]["recording"],
            "repository_path": "maintenance/catalogue/ar_ina/official/web/unselected.body",
        }
    )
    with pytest.raises(FatalContractError, match="absent from selected retained inputs"):
        read_original(evidence, unselected, input_receipt=receipt)


@pytest.mark.governing(
    "maintenance/catalogue/ar_ina/official",
    "maintenance/catalogue/ar_ina/official/selection.json",
)
def test_selected_inputs_publish_deterministic_catalogue(
    retained_evidence_root, catalogue_input_receipt, catalogue_build_inputs, tmp_path
):
    configured = os.environ.get("RIVRETRIEVE_CATALOGUE_PRODUCT_OUTPUT")
    if not configured:
        pytest.fail("Reviewed catalogue generation requires restricted product output.", pytrace=False)
    product_root = Path(configured).resolve()
    selection = "maintenance/catalogue/ar_ina/official/selection.json"
    sources = read_catalogue_sources(
        retained_evidence_root, selection_path=selection, input_receipt=catalogue_input_receipt
    )
    build_inputs = catalogue_build_inputs(sources.provenance)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(catalogue_input_receipt.model_dump_json())
    build_path = tmp_path / "build-inputs.json"
    build_path.write_text(build_inputs.model_dump_json())
    outputs = [product_root / "ar_ina", product_root / "ar_ina-repeat"]
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
        assert stations.height == 829
        assert stations["crs"].unique().to_list() == ["EPSG:4326"]
        assert stations.filter(pl.col("station_id") == "96")["latitude"].to_list() == [None]
        products = pl.read_parquet(output / "products.parquet")
        assert products.height == 13
        pairs = pl.read_parquet(output / "station_products.parquet")
        assert pairs.height == 829 * 13
        assert pairs.filter(pl.col("availability") == "available").height == 2611
        assert pairs.filter(pl.col("availability") == "unknown").height == 8166
        assert pairs["published_record_start_date"].null_count() == pairs.height
        assert pairs["published_record_end_date"].null_count() == pairs.height
        assert "unavailable" not in pairs["availability"].to_list()
        provider = json.loads((output / "provider.json").read_bytes())
        assert provider["license"] == "Creative Commons Atribución 4.0 Internacional"
        assert provider["citation"] is None
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
