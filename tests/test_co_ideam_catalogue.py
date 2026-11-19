"""Synthetic and governing Colombia IDEAM catalogue identity and source-fidelity checks."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.co_ideam.generate_catalogue import (
    ASSOCIATION_SCHEMA,
    CATALOGO_COLUMNS,
    IN_SCOPE_HYDROLOGICAL_LABELS,
    S3_BUCKET_NAME,
    build_catalogue,
    catalogue_tables,
    describe_associations,
    main,
    parse_s3_prefix_listings,
    parse_variables_catalogue,
    read_catalogue_sources,
    read_original,
    s3_list_associations,
    station_native_table,
    write_catalogue,
)


def _catalogo_row(
    codigo: str,
    *,
    nombre: str = "SYNTHETIC GAUGE",
    categoria: str = "Limnimétrica",
    corriente: str = "MAGDALENA",
    altitud: str = "250",
    longitud: str = "-74.5",
    latitud: str = "4.6",
) -> dict[str, str]:
    row = dict.fromkeys(CATALOGO_COLUMNS, "")
    row.update(
        {
            "Codigo": codigo,
            "Nombre": nombre,
            "Descripcion": f"{codigo} - {nombre}",
            "Categoria": categoria,
            "Tecnologia": "Convencional",
            "Estado": "Activa",
            "Departamento": "Cundinamarca",
            "Municipio": "Girardot",
            "Altitud": altitud,
            "Longitud": longitud,
            "Latitud": latitud,
            "Fecha_instalacion": "1980-01-01",
            "Area_Operativa": "Area Operativa 11",
            "Corriente": corriente,
            "Area_Hidrografica": "Magdalena Cauca",
            "Zona_Hidrografica": "Alto Magdalena",
            "Subzona_Hidrografica": "Rio Bogota",
            "Entidad": "INSTITUTO DE HIDROLOGIA METEOROLOGIA Y ESTUDIOS AMBIENTALES",
        }
    )
    return row


def _catalogo_csv_bytes(rows: list[dict[str, str]], *, columns: tuple[str, ...] = CATALOGO_COLUMNS) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _variables_csv_bytes(extra_rows: list[dict[str, str]] | None = None) -> bytes:
    from rivretrieve._internal.providers.co_ideam.series import SERIES_SPECS

    fieldnames = ["etiqueta", "parametro", "unidad", "periodo", "descripcion", "tipo_estadistica"]
    rows = [
        {
            "etiqueta": spec.etiqueta,
            "parametro": "Caudal " if spec.expected_parametro == "Caudal" else "Nivel",
            "unidad": spec.source_unit,
            "periodo": spec.expected_periodo,
            "descripcion": spec.etiqueta,
            "tipo_estadistica": spec.expected_tipo_estadistica,
        }
        for spec in SERIES_SPECS
    ]
    if extra_rows:
        rows.extend(extra_rows)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _s3_xml_page(
    label: str,
    stations: list[tuple[str, int]],
    *,
    is_truncated: bool = False,
    continuation_token: str | None = None,
    next_token: str | None = None,
    bucket: str = S3_BUCKET_NAME,
    prefix: str | None = None,
    key_count: int | None = None,
) -> bytes:
    actual_prefix = f"observaciones/historicos/csv/{label}/" if prefix is None else prefix
    actual_count = len(stations) if key_count is None else key_count
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">',
        f"<Name>{bucket}</Name>",
        f"<Prefix>{actual_prefix}</Prefix>",
        f"<KeyCount>{actual_count}</KeyCount>",
        "<MaxKeys>1000</MaxKeys>",
        f"<IsTruncated>{'true' if is_truncated else 'false'}</IsTruncated>",
    ]
    if continuation_token is not None:
        parts.append(f"<ContinuationToken>{continuation_token}</ContinuationToken>")
    if next_token is not None:
        parts.append(f"<NextContinuationToken>{next_token}</NextContinuationToken>")
    for station_id, size in stations:
        key = f"{actual_prefix}{station_id}-{label}.csv"
        parts.append(f"<Contents><Key>{key}</Key><Size>{size}</Size></Contents>")
    parts.append("</ListBucketResult>")
    return "".join(parts).encode("utf-8")


def _complete_listings(
    by_label: dict[str, frozenset[str]], *, default_station: str = "0021207010"
) -> dict[str, frozenset[str]]:
    return {label: by_label.get(label, frozenset({default_station})) for label in IN_SCOPE_HYDROLOGICAL_LABELS}


def test_station_native_table_enforces_option_a_flowing_watercourse_scope():
    rows = [
        # Canonical river gauge
        _catalogo_row("0021207010", nombre="PUENTE PORTILLO", corriente="BOGOTÁ"),
        # Dead CNE registry row (absent from S3 listings -> excluded)
        _catalogo_row("0021207999", nombre="DEAD REGISTRY ROW", corriente="BOGOTÁ"),
        # Synthetic placeholder -> excluded even if listed
        _catalogo_row("0010000000", nombre="ESTACION FICTICIA", corriente="MAGDALENA"),
        # Marine tide gauges -> excluded by Categoria or Corriente
        _catalogo_row("0014019010", nombre="CARTAGENA MAREOGRAFO", categoria="Meteorológica Marina", corriente="BAHIA"),
        _catalogo_row("0054077210", nombre="BUENAVENTURA", categoria="Limnimétrica", corriente="OCÉANO PACÍFICO"),
        # Groundwater well vs flowing arroyos with POZO in name
        _catalogo_row("0035027110", nombre="LLANITOS", categoria="Limnimétrica", corriente="POZO"),
        _catalogo_row("0015067130", nombre="POZO HONDO", categoria="Limnimétrica", corriente="AY POZO HONDO"),
        _catalogo_row("1506700110", nombre="POZO TIGRE", categoria="Limnigráfica", corriente="AY BRUNO"),
        # Standing-water Corriente: stage-only excluded; Group 2a gauged outflows retained
        _catalogo_row("0024017990", nombre="POOL STAGE ONLY", categoria="Limnimétrica", corriente="LAGUNA DE TOTA"),
        _catalogo_row("0035097040", nombre="DESAGUADERO", categoria="Limnigráfica", corriente="LAGUNA DE TOTA"),
        _catalogo_row("0013067050", nombre="TRES PALMAS", categoria="Limnimétrica", corriente="CIÉNAGA BETANCI"),
        # Group 2b standing pool Nombre on river Corriente excluded; dam outlet 0024017690 retained
        _catalogo_row("0027027240", nombre="EMBALSE MIRAFLORES", categoria="Limnigráfica", corriente="TENCHE"),
        _catalogo_row("0024017690", nombre="SALIDA EMBALSE", categoria="Limnigráfica", corriente="CHUZA"),
        # Non-(Limnimétrica/Limnigráfica) meteorological stations:
        # blank Corriente stage-only excluded; Q_* publisher + named-river stage gauges retained
        _catalogo_row("0023205040", nombre="MET TWIN STAGE ONLY", categoria="Pluviométrica", corriente=""),
        _catalogo_row("0013085010", nombre="LA DOCTRINA", categoria="Climatológica Ordinaria", corriente=""),
        _catalogo_row("0044187020", nombre="PEDRERA LA", categoria="Sinóptica Principal", corriente="CAQUETÁ"),
        _catalogo_row("0047087010", nombre="ARICA - R. PUTUMAYO", categoria="Pluviométrica", corriente="PUTUMAYO"),
    ]
    listings = _complete_listings(
        {
            "Q_MEDIA_D": frozenset({"0021207010", "0035097040", "0013067050", "0024017690", "0013085010"}),
            "NV_MEDIA_D": frozenset(
                {
                    "0010000000",
                    "0014019010",
                    "0054077210",
                    "0035027110",
                    "0015067130",
                    "1506700110",
                    "0024017990",
                    "0035097040",
                    "0013067050",
                    "0027027240",
                    "0024017690",
                    "0023205040",
                    "0013085010",
                    "0044187020",
                    "0047087010",
                    "0021207010",
                }
            ),
        }
    )
    native = station_native_table(
        _catalogo_csv_bytes(rows),
        listings,
        retrieved_at=RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
    )
    assert native.data["Codigo"].to_list() == [
        "0013067050",
        "0013085010",
        "0015067130",
        "0021207010",
        "0024017690",
        "0035097040",
        "0044187020",
        "0047087010",
        "1506700110",
    ]
    # Blank Corriente on retained discharge station 0013085010 becomes None for source_null projection
    doctrina = native.data.filter(pl.col("Codigo") == "0013085010").row(0, named=True)
    assert doctrina["Corriente"] is None


def test_standing_pool_exclusion_fails_closed_if_discharge_ever_appears():
    rows = [
        _catalogo_row("0021207010"),
        _catalogo_row("0027027240", nombre="EMBALSE MIRAFLORES", categoria="Limnigráfica", corriente="TENCHE"),
    ]
    listings = _complete_listings({"Q_MEDIA_D": frozenset({"0021207010", "0027027240"})})
    with pytest.raises(FatalContractError, match="Standing-pool exclusion '0027027240' unexpectedly publishes"):
        station_native_table(
            _catalogo_csv_bytes(rows),
            listings,
            retrieved_at=RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
        )


def test_station_native_table_rejects_unregistered_stations_and_bad_coordinates():
    listings = _complete_listings({"NV_MEDIA_D": frozenset({"0021207010", "9999999999"})})
    with pytest.raises(FatalContractError, match="absent from catalogo.csv"):
        station_native_table(
            _catalogo_csv_bytes([_catalogo_row("0021207010")]),
            listings,
            retrieved_at=RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
        )

    bad_lat = [_catalogo_row("0021207010", latitud="95.0")]
    with pytest.raises(FatalContractError, match="coordinates out of geographic bounds"):
        station_native_table(
            _catalogo_csv_bytes(bad_lat),
            _complete_listings({}),
            retrieved_at=RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
        )


def test_variables_and_s3_prefix_listings_enforce_pagination_and_integrity():
    variables = parse_variables_catalogue(_variables_csv_bytes())
    assert len(variables) == 20
    assert variables["CAUDAL_H"] == ("Caudal", "m3/s")
    assert variables["NV_MEDIA_D"] == ("Nivel", "cm")

    pages = {label: (_s3_xml_page(label, [("0021207010", 512)]),) for label in IN_SCOPE_HYDROLOGICAL_LABELS}
    pages["NV_MEDIA_D"] = (
        _s3_xml_page("NV_MEDIA_D", [("0021207010", 512)], is_truncated=True, next_token="tok-2"),
        _s3_xml_page("NV_MEDIA_D", [("0024017690", 1024)], is_truncated=False, continuation_token="tok-2"),
    )
    parsed = parse_s3_prefix_listings(pages)
    assert parsed["NV_MEDIA_D"] == frozenset({"0021207010", "0024017690"})

    # Token mismatch fails closed
    bad_token = dict(pages)
    bad_token["NV_MEDIA_D"] = (
        _s3_xml_page("NV_MEDIA_D", [("0021207010", 512)], is_truncated=True, next_token="tok-2"),
        _s3_xml_page("NV_MEDIA_D", [("0024017690", 1024)], is_truncated=False, continuation_token="wrong"),
    )
    with pytest.raises(FatalContractError, match="continuation token mismatch"):
        parse_s3_prefix_listings(bad_token)

    # Truncated final page fails closed
    truncated_final = dict(pages)
    truncated_final["CAUDAL_H"] = (_s3_xml_page("CAUDAL_H", [("0021207010", 512)], is_truncated=True, next_token="t"),)
    with pytest.raises(FatalContractError, match="truncated on final page"):
        parse_s3_prefix_listings(truncated_final)

    # Zero-byte CSV object fails closed
    zero_byte = dict(pages)
    zero_byte["CAUDAL_H"] = (_s3_xml_page("CAUDAL_H", [("0021207010", 0)]),)
    with pytest.raises(FatalContractError, match="non-positive byte size"):
        parse_s3_prefix_listings(zero_byte)

    # DTD declaration fails closed
    dtd_pages = dict(pages)
    dtd_pages["CAUDAL_H"] = (b"<!DOCTYPE foo><ListBucketResult/>",)
    with pytest.raises(FatalContractError, match="DTD"):
        parse_s3_prefix_listings(dtd_pages)


def test_metadata_projection_and_source_descriptions_preserve_units_and_null_corriente():
    from rivretrieve._internal.providers.co_ideam.station_metadata import project_station_metadata
    from rivretrieve._internal.source_series import admission

    rows = [
        _catalogo_row(
            "0013085010", nombre="LA DOCTRINA", categoria="Climatológica Ordinaria", corriente="", altitud="7"
        ),
        _catalogo_row("0021207010", nombre="PUENTE PORTILLO", corriente="BOGOTÁ", altitud="320"),
    ]
    listings = _complete_listings({"Q_MEDIA_D": frozenset({"0013085010", "0021207010"})})
    native = station_native_table(
        _catalogo_csv_bytes(rows),
        listings,
        retrieved_at=RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
    )
    variables = parse_variables_catalogue(_variables_csv_bytes())
    associations = s3_list_associations(native, listings, variables)
    products, stations, pairs = catalogue_tables(native, associations, checked_on=date(2026, 11, 6))
    assert stations["crs"].to_list() == ["unknown", "unknown"]
    assert products.height == 20
    assert pairs.height == 40
    assert pairs.filter(pl.col("availability") == "available").height == 21
    assert pairs.filter(pl.col("availability") == "unavailable").height == 19

    metadata = project_station_metadata(native, stations)
    wb_doctrina = metadata.filter(
        (pl.col("station_id") == "0013085010") & (pl.col("attribute_role") == "water_body_name")
    )
    assert wb_doctrina["state"].to_list() == ["source_null"]
    wb_portillo = metadata.filter(
        (pl.col("station_id") == "0021207010") & (pl.col("attribute_role") == "water_body_name")
    )
    assert wb_portillo.select("source_value", "state").row(0) == ('"BOGOTÁ"', "value")

    elev = metadata.filter((pl.col("station_id") == "0021207010") & (pl.col("attribute_role") == "elevation")).row(
        0, named=True
    )
    assert elev["source_value"] == '"320"'
    assert elev["source_unit"] is None
    assert elev["source_datum"] is None
    assert elev["state"] == "value"
    assert metadata.filter(pl.col("attribute_role") == "drainage_area")["state"].unique().to_list() == ["no_metadata"]

    descriptions = {item.product_id: item for item in describe_associations(associations).descriptions}
    q_facts = descriptions["q_media_d"].facts[0]
    assert admission(q_facts).model_dump() == {
        "status": "supported",
        "reason": None,
        "target_unit": "m3/s",
        "factor": 1.0,
    }
    nv_facts = descriptions["nv_media_d"].facts[0]
    assert admission(nv_facts).model_dump() == {
        "status": "supported",
        "reason": None,
        "target_unit": "m",
        "factor": 0.01,
    }
    assert nv_facts.vertical_reference.value == "gauge_zero"
    assert nv_facts.vertical_datum.value is None
    assert nv_facts.frequency.value == "daily"
    assert nv_facts.statistic.value == "mean"
    assert descriptions["caudal_h"].facts[0].frequency.value is None
    assert descriptions["caudal_h"].facts[0].statistic.value is None


def test_provenance_offline_publication_and_cli_checkout_guard(tmp_path: Path):
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
    from rivretrieve._internal.providers.co_ideam.origins import (
        STATION_CATALOGUE_ORIGINS,
        STATION_METADATA_FIELDS,
        STATION_METADATA_NOTICE,
        build_acquisition_provenance,
    )
    from rivretrieve._internal.providers.co_ideam.station_metadata import project_station_metadata

    body = b'{"licenseId":"CC_40_BY_SA"}'
    body_path = tmp_path / "hp9r-jxuu.body"
    body_path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    recording = RecordingReference(
        recording_id="synthetic",
        repository_path="hp9r-jxuu.body",
        source_url="https://www.datos.gov.co/api/views/hp9r-jxuu.json",
        retrieved_at=datetime(2026, 11, 6, tzinfo=UTC),
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
                consumer_path="hp9r-jxuu.body",
                archive_repository="https://github.com/RivRetrieve/verification-evidence",
                archive_revision="b" * 40,
                collection_id="synthetic",
                manifest_sha256="c" * 64,
                artifact_id="hp9r",
                sha256=digest,
                byte_size=len(body),
                role="publisher_original",
            ),
        ),
    )
    assert read_original(tmp_path, recording, input_receipt=receipt) == body

    facts = (
        "source.station.catalogo_registry",
        "source.station.altitud_field_context",
        "source.product.variables_catalogue",
        "source.station_product.s3_prefix_listings",
        "source.product.datosgov_series_definitions",
        "source.product.ideam_hydrological_manuals",
        "source.product.s3_observation_witnesses",
        "source.provider.license",
        "source.provider.citation",
        "source.provider.terms_series",
    )
    native_id = NativeTableIdentity(
        location_kind="retained", repository_path="native.parquet", revision="a" * 40, sha256="b" * 64, byte_size=1
    )
    acquisition = AcquisitionRecord(
        acquisition_id="synthetic",
        method="http_request",
        instant_type="retrieval",
        description="Synthetic IDEAM source",
        requested_from=(recording.source_url,),
        retrieved_at_start=recording.retrieved_at,
        recording_ids=("synthetic",),
    )
    binding = FactBinding(fact_group="synthetic", facts=facts, source_id="co_ideam", acquisition_id="synthetic")
    license_text = "Creative Commons Attribution | Share Alike 4.0 International"
    citation_text = "Instituto de Hidrología, Meteorología y Estudios Ambientales - IDEAM, Bogotá D.C."
    statements = (
        SourceStatement(
            kind="license",
            exact_text=license_text,
            recording_id="synthetic",
            fact="source.provider.license",
            verification_status="verified_public_recording",
        ),
        SourceStatement(
            kind="citation",
            exact_text=citation_text,
            recording_id="synthetic",
            fact="source.provider.citation",
            verification_status="verified_public_recording",
        ),
        SourceStatement(
            kind="terms",
            exact_text=license_text,
            recording_id="synthetic",
            fact="source.provider.terms_series",
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

    native = station_native_table(
        _catalogo_csv_bytes([_catalogo_row("0021207010")]),
        _complete_listings({}),
        retrieved_at=RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
    )
    associations = pl.DataFrame(
        [("0021207010", "Q_MEDIA_D", "m3/s"), ("0021207010", "NV_MEDIA_D", "cm")],
        schema=ASSOCIATION_SCHEMA,
        orient="row",
    )
    catalogue = build_catalogue(
        native,
        STATION_CATALOGUE_ORIGINS,
        associations=associations,
        checked_on=date(2026, 11, 6),
        provenance=provenance,
    )
    catalogue = replace(catalogue, station_metadata=project_station_metadata(native, catalogue.stations))
    assert catalogue.provider_info["license"] == license_text
    assert catalogue.provider_info["citation"] == citation_text

    def code(path: str, symbol: str) -> CodeReference:
        return CodeReference(
            repository="https://github.com/RivRetrieve/RivRetrieve",
            repository_path=path,
            symbol=symbol,
            revision="a" * 40,
        )

    prefix = "src/rivretrieve/_internal/providers/co_ideam/"
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
            code(prefix + "origins.py", "STATION_METADATA_FIELDS"),
            code(prefix + "origins.py", "STATION_METADATA_NOTICE"),
            code(prefix + "generate_catalogue.py", "build_catalogue"),
            code(prefix + "generate_catalogue.py", "read_catalogue_sources"),
            code(prefix + "station_metadata.py", "project_station_metadata"),
            code(prefix + "series.py", "source_series"),
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
    assert loaded.stations["station_id"].to_list() == ["0021207010"]
    assert loaded.stations["crs"].to_list() == ["unknown"]
    assert len(loaded.source_descriptions.descriptions) == 2
    assert STATION_METADATA_NOTICE in (out_dir / "croissant.json").read_text("utf-8")

    # CLI refuses output overlapping retained inputs and output inside a git checkout
    evidence_dir = tmp_path / "inputs"
    evidence_dir.mkdir()
    fake_repo = tmp_path / "repo"
    (fake_repo / ".git").mkdir(parents=True)
    receipt_file = tmp_path / "receipt.json"
    receipt_file.write_text(receipt.model_dump_json())
    with pytest.raises(FatalContractError, match="separate from retained inputs"):
        main(
            [
                "--evidence-root",
                str(evidence_dir),
                "--selection",
                "selection.json",
                "--input-receipt",
                str(receipt_file),
                "--native-only",
                "--out",
                str(evidence_dir / "nested"),
            ]
        )
    with pytest.raises(FatalContractError, match="outside source checkouts"):
        main(
            [
                "--evidence-root",
                str(evidence_dir),
                "--selection",
                "selection.json",
                "--input-receipt",
                str(receipt_file),
                "--native-only",
                "--out",
                str(fake_repo / "out"),
            ]
        )


@pytest.mark.governing(
    "maintenance/catalogue/co_ideam/official",
    "maintenance/catalogue/co_ideam/official/selection.json",
)
def test_selected_inputs_publish_deterministic_catalogue(
    retained_evidence_root, catalogue_input_receipt, catalogue_build_inputs, tmp_path
):
    import os

    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.co_ideam.origins import STATION_METADATA_NOTICE

    configured = os.environ.get("RIVRETRIEVE_CATALOGUE_PRODUCT_OUTPUT")
    if not configured:
        pytest.fail("Reviewed catalogue generation requires restricted product output.", pytrace=False)
    product_root = Path(configured).resolve()
    selection = "maintenance/catalogue/co_ideam/official/selection.json"
    sources = read_catalogue_sources(
        retained_evidence_root, selection_path=selection, input_receipt=catalogue_input_receipt
    )
    build_inputs = catalogue_build_inputs(sources.provenance)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(catalogue_input_receipt.model_dump_json())
    build_path = tmp_path / "build-inputs.json"
    build_path.write_text(build_inputs.model_dump_json())
    outputs = [product_root / "co_ideam", product_root / "co_ideam-repeat"]
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
        assert stations.height == 1_372
        assert stations["crs"].unique().to_list() == ["unknown"]
        products = pl.read_parquet(output / "products.parquet")
        assert products.height == 20
        pairs = pl.read_parquet(output / "station_products.parquet")
        assert pairs.height == 1_372 * 20
        assert pairs.filter(pl.col("availability") == "available").height == 19_690
        assert pairs.filter(pl.col("availability") == "unavailable").height == 7_750
        assert pairs["published_record_start_date"].null_count() == pairs.height
        assert pairs["published_record_end_date"].null_count() == pairs.height
        provider = json.loads((output / "provider.json").read_bytes())
        assert provider["license"] == "Creative Commons Attribution | Share Alike 4.0 International"
        assert (
            provider["citation"] == "Instituto de Hidrología, Meteorología y Estudios Ambientales - IDEAM, Bogotá D.C."
        )
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
