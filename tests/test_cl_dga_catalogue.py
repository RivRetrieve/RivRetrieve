"""Synthetic unit and catalogue-contract tests for Chile DGA (cl_dga)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rivretrieve._internal.acquisition_provenance import (
    AbsenceMarkerValue,
    AcquisitionRecord,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    SourceStatement,
)
from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Field,
    NativeColumn,
    Withheld,
)


def test_chile_unsigned_dms_conversion_and_bounds() -> None:
    from rivretrieve._internal.providers.cl_dga.origins import (
        ChileUnsignedDmsConversion,
        unsigned_dms_coordinate,
    )

    assert unsigned_dms_coordinate("0175952", "latitude") == pytest.approx(-(17.0 + 59.0 / 60.0 + 52.0 / 3600.0))
    assert unsigned_dms_coordinate("0691525", "longitude") == pytest.approx(-(69.0 + 15.0 / 60.0 + 25.0 / 3600.0))
    # DGA publishes seconds == 60 on seven verified gauges (equivalent to a 1-minute carry).
    assert unsigned_dms_coordinate("0693360", "longitude") == pytest.approx(-(69.0 + 34.0 / 60.0))

    conv = ChileUnsignedDmsConversion()
    assert conv.name == "cl_dga.unsigned_dms"
    row = {"LAT": "0354216", "LONG": "0710618"}
    assert conv.apply("latitude", NativeColumn("LAT"), row) == pytest.approx(-(35.0 + 42.0 / 60.0 + 16.0 / 3600.0))
    assert conv.apply("longitude", NativeColumn("LONG"), row) == pytest.approx(-(71.0 + 6.0 / 60.0 + 18.0 / 3600.0))

    for bad_col, native_col in (("latitude", "LONG"), ("longitude", "LAT"), ("station_id", "LAT")):
        with pytest.raises(ValueError):
            conv.apply(bad_col, NativeColumn(native_col), row)

    for bad_val, axis in (
        ("175952", "latitude"),
        ("0176000", "latitude"),
        ("0175961", "latitude"),
        ("0145959", "latitude"),
        ("0580000", "latitude"),
        ("0640000", "longitude"),
        ("1110000", "longitude"),
        (175952, "latitude"),
    ):
        with pytest.raises(ValueError):
            unsigned_dms_coordinate(bad_val, axis)


def test_cl_dga_origins_and_provenance_preserve_withheld_crs_and_unlicensed_terms() -> None:
    from rivretrieve._internal.providers.cl_dga.origins import (
        MOP_TERMS_TEXT,
        STATION_CATALOGUE_ORIGINS,
        STATION_METADATA_FIELDS,
        STATION_METADATA_NOTICE,
        ChileUnsignedDmsConversion,
        build_acquisition_provenance,
    )

    expected_origins = {
        "provider_id": Authored(AuthoredValue("cl_dga")),
        "station_id": Field(NativeColumn("CODIGO ESTACION")),
        "latitude": Field(NativeColumn("LAT"), ChileUnsignedDmsConversion()),
        "longitude": Field(NativeColumn("LONG"), ChileUnsignedDmsConversion()),
        "crs": Withheld(),
    }
    assert expected_origins == STATION_CATALOGUE_ORIGINS
    assert [
        (f.attribute_role, f.source_field, f.source_unit, f.datum_field, f.datum) for f in STATION_METADATA_FIELDS
    ] == [
        ("station_name", "NOMBRE ESTACION", None, None, None),
        ("elevation", "ALTITUD", "m", None, None),
    ]
    assert "mapas2.mop.gob.cl" in STATION_METADATA_NOTICE
    assert "condiciones-de-uso" in STATION_METADATA_NOTICE
    assert "MIT" in STATION_METADATA_NOTICE

    ts = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
    native_identity = NativeTableIdentity(
        location_kind="retained",
        repository_path="maintenance/catalogue/cl_dga/official/native.parquet",
        revision="a" * 40,
        sha256="b" * 64,
        byte_size=1234,
    )
    recordings = (
        RecordingReference(
            recording_id="rec-zip",
            repository_path="maintenance/catalogue/cl_dga/official/web/daily.zip",
            source_url="https://mapas2.mop.gob.cl/caudal_diario_historico.zip",
            retrieved_at=ts,
            media_type="application/zip",
            sha256="c" * 64,
        ),
        RecordingReference(
            recording_id="rec-terms",
            repository_path="maintenance/catalogue/cl_dga/official/web/terms.body",
            source_url="https://www.mop.gob.cl/condiciones-de-uso/",
            retrieved_at=ts,
            media_type="text/html; charset=UTF-8",
            sha256="d" * 64,
        ),
    )
    acquisitions = (
        AcquisitionRecord(
            acquisition_id="acq-zip",
            method="http_request",
            instant_type="retrieval",
            description="Historical ZIP",
            requested_from=("https://mapas2.mop.gob.cl/caudal_diario_historico.zip",),
            retrieved_at_start=ts,
            recording_ids=("rec-zip",),
        ),
        AcquisitionRecord(
            acquisition_id="acq-terms",
            method="http_request",
            instant_type="retrieval",
            description="MOP terms",
            requested_from=("https://www.mop.gob.cl/condiciones-de-uso/",),
            retrieved_at_start=ts,
            recording_ids=("rec-terms",),
        ),
    )
    bindings = (
        FactBinding(
            fact_group="zip_meta",
            facts=(
                "source.station.zip_metadata",
                "source.station.supporting_reconciliation",
                "source.station.altitud_unit",
                "source.product.daily_discharge_zip",
                "source.product.monthly_discharge_zip",
            ),
            source_id="cl_dga",
            acquisition_id="acq-zip",
        ),
        FactBinding(
            fact_group="terms",
            facts=("source.provider.terms", "source.provider.attribution"),
            source_id="cl_dga",
            acquisition_id="acq-terms",
        ),
    )
    statements = (
        SourceStatement(
            kind="terms",
            exact_text=MOP_TERMS_TEXT,
            recording_id="rec-terms",
            fact="source.provider.terms",
        ),
    )
    prov = build_acquisition_provenance(
        native_identity,
        recordings,
        acquisitions=acquisitions,
        source_bindings=bindings,
        statements=statements,
    )
    assert prov.provider_id == "cl_dga"
    assert [w.facts for w in prov.withheld_facts] == [("source.station.crs",)]
    crs_binding = next(b for b in prov.fact_bindings if "station.crs" in b.facts)
    assert crs_binding.transformation is not None
    assert crs_binding.transformation.kind == "absence_marker"
    assert crs_binding.transformation.marker_value == AbsenceMarkerValue.UNKNOWN

    with pytest.raises(ValueError, match="terms"):
        build_acquisition_provenance(
            native_identity,
            recordings,
            acquisitions=acquisitions,
            source_bindings=bindings,
            statements=(),
        )
    with pytest.raises(ValueError, match="license"):
        build_acquisition_provenance(
            native_identity,
            recordings,
            acquisitions=acquisitions,
            source_bindings=bindings,
            statements=(
                *statements,
                SourceStatement(
                    kind="license",
                    exact_text="MIT",
                    recording_id="rec-terms",
                    fact="source.provider.terms",
                ),
            ),
        )


def test_cl_dga_series_mappings_and_catalogue_descriptions() -> None:
    import polars as pl

    from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
    from rivretrieve._internal.providers.cl_dga.catalogue_series import describe_catalogue
    from rivretrieve._internal.providers.cl_dga.series import SERIES_MAPPINGS
    from rivretrieve._internal.source_series import ClippingAxis, EvidenceState

    daily = SERIES_MAPPINGS["discharge_daily"]
    daily_facts = daily.physical_facts()
    assert daily_facts.quantity.value == "discharge"
    assert daily_facts.source_unit.value == "m3/s"
    assert daily_facts.normalized_unit == "m3/s"
    assert daily_facts.frequency.value == "daily"
    assert daily_facts.statistic.state is EvidenceState.NOT_ESTABLISHED
    assert daily_facts.statistic.value is None
    assert daily_facts.temporal_support.state is EvidenceState.NOT_ESTABLISHED
    assert daily_facts.day_definition.state is EvidenceState.NOT_ESTABLISHED
    assert daily_facts.timestamp_anchor.state is EvidenceState.NOT_ESTABLISHED
    assert daily_facts.time_zone.state is EvidenceState.NOT_ESTABLISHED
    assert daily_facts.clipping_axis is ClippingAxis.CALENDAR_DATE
    assert daily.published_id == "Caudal_diario"

    monthly = SERIES_MAPPINGS["discharge_monthly_mean"]
    monthly_facts = monthly.physical_facts()
    assert monthly_facts.quantity.value == "discharge"
    assert monthly_facts.source_unit.value == "m3/s"
    assert monthly_facts.normalized_unit == "m3/s"
    assert monthly_facts.frequency.value == "monthly"
    assert monthly_facts.statistic.state is EvidenceState.KNOWN
    assert monthly_facts.statistic.value == "mean"
    assert monthly_facts.temporal_support.state is EvidenceState.NOT_ESTABLISHED
    assert monthly_facts.time_zone.state is EvidenceState.NOT_ESTABLISHED
    assert monthly.published_id == "Caudal_Medio_mensual"

    artifact = PackagedCatalogArtifact(
        provider_info={"provider_id": "cl_dga"},
        products=pl.DataFrame(
            [
                {"product_id": "discharge_daily", "native_id": "Caudal_diario"},
                {"product_id": "discharge_monthly_mean", "native_id": "Caudal_Medio_mensual"},
            ]
        ),
        stations=pl.DataFrame({"provider_id": ["cl_dga"], "station_id": ["01001002"]}),
        station_products=pl.DataFrame(),
    )
    described = describe_catalogue(artifact)
    assert described.provider_id == "cl_dga"
    assert [item.product_id for item in described.descriptions] == ["discharge_daily", "discharge_monthly_mean"]
    assert [item.native_coordinate for item in described.descriptions] == ["Caudal_diario", "Caudal_Medio_mensual"]


def test_cl_dga_series_admission_and_physical_filters() -> None:
    from pathlib import Path

    import rivretrieve as rr
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.cl_dga.series import SERIES_MAPPINGS
    from rivretrieve._internal.source_series import (
        ClippingAxis,
        EvidenceState,
        PhysicalPredicate,
        SeriesScope,
        admission,
    )

    daily = SERIES_MAPPINGS["discharge_daily"].physical_facts()
    monthly = SERIES_MAPPINGS["discharge_monthly_mean"].physical_facts()

    for facts, expected_axis in (
        (daily, ClippingAxis.CALENDAR_DATE),
        (monthly, ClippingAxis.SOURCE_TIMESTAMP),
    ):
        decision = admission(facts)
        assert decision.status == "supported"
        assert decision.factor == 1.0
        assert decision.target_unit == "m3/s"
        assert facts.clipping_axis is expected_axis
        assert facts.label_time is None
        for field_name in (
            "temporal_support",
            "day_definition",
            "timestamp_anchor",
            "time_zone",
            "vertical_reference",
            "vertical_datum",
        ):
            assert getattr(facts, field_name).state is EvidenceState.NOT_ESTABLISHED

    catalogue_dir = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/cl_dga/catalogue"
    packaged = load_packaged_catalogue_artifact(catalogue_dir, on_issue="raise")
    products = {row["product_id"]: row for row in packaged.products.iter_rows(named=True)}
    assert products["discharge_daily"]["statistic"] == "unknown"
    assert products["discharge_monthly_mean"]["statistic"] == "mean"
    assert all(row["period_anchor"] == "unknown" and row["period_type"] == "unknown" for row in products.values())

    broad = rr.find(provider="cl_dga", station="01001001", quantity="discharge")
    assert {item.product_id for item in broad.series} == {"discharge_daily", "discharge_monthly_mean"}

    means = rr.find(provider="cl_dga", station="01001001", quantity="discharge", statistic="mean")
    assert {item.product_id for item in means.series} == {"discharge_monthly_mean"}

    daily_found = rr.find(provider="cl_dga", station="01001001", frequency="daily")
    assert {item.product_id for item in daily_found.series} == {"discharge_daily"}

    monthly_found = rr.find(provider="cl_dga", station="01001001", frequency="monthly")
    assert {item.product_id for item in monthly_found.series} == {"discharge_monthly_mean"}

    for field_name, probe_value in (
        ("temporal_support", "calendar_day"),
        ("temporal_support", "calendar_month"),
        ("day_definition", "UTC-04:00"),
        ("timestamp_anchor", "start"),
        ("time_zone", "America/Santiago"),
    ):
        scope = SeriesScope(predicates=(PhysicalPredicate(field=field_name, value=probe_value),))
        assert not any(scope.matches(item) for item in broad.series)


def test_cl_dga_station_metadata_projection_withholds_altitud_zero() -> None:
    from datetime import UTC, datetime

    import polars as pl

    from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
    from rivretrieve._internal.providers.cl_dga.station_metadata import project_station_metadata

    native = stamp_native_table(
        pl.DataFrame(
            {
                "CODIGO ESTACION": ["01001002", "01001005"],
                "NOMBRE ESTACION": ["RIO CAQUENA EN VERTEDERO", "RIO LAUCA EN CHUCUYO"],
                "ALTITUD_RAW": ["0", "4400"],
                "ALTITUD": [None, 4400],
            },
            schema={
                "CODIGO ESTACION": pl.String,
                "NOMBRE ESTACION": pl.String,
                "ALTITUD_RAW": pl.String,
                "ALTITUD": pl.Int64,
            },
        ),
        RetrievedAt(datetime(2026, 11, 18, 12, 0, tzinfo=UTC)),
    )
    stations = pl.DataFrame({"provider_id": ["cl_dga", "cl_dga"], "station_id": ["01001002", "01001005"]})
    projected = project_station_metadata(native, stations)
    rows = {(row["station_id"], row["attribute_role"]): row for row in projected.iter_rows(named=True)}
    assert rows[("01001002", "elevation")]["state"] == "source_null"
    assert rows[("01001002", "elevation")]["source_value"] is None
    assert rows[("01001002", "elevation")]["source_unit"] == "m"
    assert rows[("01001002", "elevation")]["source_datum"] is None
    assert rows[("01001005", "elevation")]["state"] == "value"
    assert rows[("01001005", "elevation")]["source_value"] == "4400"
    assert rows[("01001002", "station_name")]["state"] == "value"
    assert rows[("01001002", "station_name")]["source_value"] == '"RIO CAQUENA EN VERTEDERO"'
    assert rows[("01001002", "water_body_name")]["state"] == "no_metadata"
    assert rows[("01001002", "drainage_area")]["state"] == "no_metadata"


def _make_zip_bytes(filename: str, fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    import csv
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        s = io.StringIO()
        writer = csv.DictWriter(s, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        zf.writestr(filename, s.getvalue().encode("utf-8-sig"))
    return buf.getvalue()


def _make_informe_xlsx_bytes(rows: list[list[object]]) -> bytes:
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Nacional"
    for _ in range(16):
        ws.append([])
    ws.append(
        [
            None,
            "Código",
            "Estación",
            "Fecha Instalación",
            "Región",
            "Provincia",
            "Comuna",
            "Cuenca",
            "SubCuenca",
            "SubSubCuenca",
            "UTM WGS84 Norte(m)",
            "UTM WGS84 Este(m)",
            "Datum",
            "Latitud",
            "Longitud",
            "Altitud m.s.n.m",
            "Tipo de Estación",
        ]
    )
    for row in rows:
        ws.append([None, *row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_mapas2_html(entries: list[dict[str, object]]) -> bytes:
    import json

    embedded = json.dumps(json.dumps(entries))
    return f"<html><script>var json = JSON.parse({embedded});</script></html>".encode()


def test_reconcile_station_code_and_check_digit_inventory() -> None:
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.cl_dga.generate_catalogue import (
        reconcile_check_digit_inventory,
        reconcile_station_code,
    )

    assert reconcile_station_code("01001002") == "01001002"
    assert reconcile_station_code("01001002-0") == "01001002"
    assert reconcile_station_code("01000005-k") == "01000005"
    assert reconcile_check_digit_inventory(["01001002-0", "01000005-K"]) == {
        "01001002": "01001002-0",
        "01000005": "01000005-K",
    }

    for bad in ("", "1001002", "01001002-A", "01001002-12", "abc12345"):
        with pytest.raises(FatalContractError):
            reconcile_station_code(bad)

    with pytest.raises(FatalContractError, match="duplicate"):
        reconcile_check_digit_inventory(["01001002-0", "01001002-1"])


def test_generate_catalogue_excludes_non_zip_stations_and_enforces_conflicts() -> None:
    from datetime import UTC, date, datetime

    import polars as pl

    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        RecordingReference,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.cl_dga.generate_catalogue import (
        DAILY_HEADER,
        MONTHLY_HEADER,
        build_catalogue,
        parse_historical_zip_metadata,
        parse_informe_nacional_xlsx,
        parse_mapas2_html_stations,
        station_native_table,
    )
    from rivretrieve._internal.providers.cl_dga.origins import (
        MOP_TERMS_TEXT,
        STATION_CATALOGUE_ORIGINS,
        build_acquisition_provenance,
    )
    from rivretrieve._internal.providers.cl_dga.station_metadata import project_station_metadata

    daily_bytes = _make_zip_bytes(
        "caudal_diario_historico.txt",
        list(DAILY_HEADER),
        [
            {
                "CODIGO ESTACION": "01001002",
                "NOMBRE ESTACION": "RIO CAQUENA EN VERTEDERO",
                "COD_REGION": "1",
                "REGION": "DE TARAPACA",
                "COMUNA": "PUTRE",
                "LAT": "0175952",
                "LONG": "0691525",
                "UTM_ESTE": "472792",
                "UTM_NORTE": "8010036",
                "ALTITUD": "0",
                "FECHA": "01/01/2020",
                "Caudal_diario": "0.5",
                "Unidad": "m3/s",
            },
            {
                "CODIGO ESTACION": "02112007",
                "NOMBRE ESTACION": "RIO LOA D. J. SAN SALVADOR-(M. ELENA)",
                "COD_REGION": "2",
                "REGION": "DE ANTOFAGASTA",
                "COMUNA": "MARIA ELENA",
                "LAT": "0222047",
                "LONG": "0693360",
                "UTM_ESTE": "441660",
                "UTM_NORTE": "7528722",
                "ALTITUD": "1240",
                "FECHA": "01/01/2020",
                "Caudal_diario": "1.2",
                "Unidad": "m3/s",
            },
        ],
    )
    monthly_bytes = _make_zip_bytes(
        "caudal_medio_mensual_historico.txt",
        list(MONTHLY_HEADER),
        [
            {
                "CODIGO ESTACION": "01001002",
                "NOMBRE ESTACION": "RIO CAQUENA EN VERTEDERO",
                "COD_REGION": "1",
                "REGION": "DE TARAPACA",
                "COMUNA": "PUTRE",
                "LAT": "0175952",
                "LONG": "0691525",
                "UTM_ESTE": "472792",
                "UTM_NORTE": "8010036",
                "ALTITUD": "0",
                "Año": "2020",
                "Mes": "1",
                "Caudal_Medio_mensual": "0.5",
                "Unidad": "m3/s",
            },
        ],
    )
    mapas2_html = _make_mapas2_html(
        [
            {
                "cod_estacion": "01001002",
                "estado_estacion": "Activa",
                "glosa_comuna": "Putre",
                "glosa_region": "De Tarapaca",
                "glosa_tipo": "Fluviometricas",
                "glosa_tipo_inac": "",
                "gls_estacion": "Rio Caquena En Vertedero",
                "id": 1,
                "val_altitud": 0,
                "val_latitud": -17.9978,
                "val_longitud": -69.2569,
            },
            {
                "cod_estacion": "09999999",
                "estado_estacion": "Activa",
                "glosa_comuna": "Putre",
                "glosa_region": "De Tarapaca",
                "glosa_tipo": "Fluviometricas",
                "glosa_tipo_inac": "",
                "gls_estacion": "No Zip Station",
                "id": 2,
                "val_altitud": 100,
                "val_latitud": -18.0,
                "val_longitud": -69.0,
            },
        ]
    )
    informe_xlsx = _make_informe_xlsx_bytes(
        [
            [
                "01001002",
                "RIO CAQUENA EN VERTEDERO",
                "01/01/1970",
                "DE TARAPACA",
                "PARINACOTA",
                "PUTRE",
                "ALTIPLANICAS",
                "Sub",
                "SubSub",
                8010036,
                472792,
                19,
                "17°59'52''",
                "69°15'25''",
                0,
                "*FLUVIOMETRICA\n",
            ],
            [
                "08888888",
                "WORKBOOK ONLY ACTIVE",
                "01/01/1970",
                "DE TARAPACA",
                "PARINACOTA",
                "PUTRE",
                "ALTIPLANICAS",
                "Sub",
                "SubSub",
                8010036,
                472792,
                19,
                "18°00'00''",
                "69°00'00''",
                100,
                "*FLUVIOMETRICA\n",
            ],
        ]
    )

    daily_meta = parse_historical_zip_metadata(daily_bytes, kind="daily")
    monthly_meta = parse_historical_zip_metadata(monthly_bytes, kind="monthly")
    mapas2_meta = parse_mapas2_html_stations(mapas2_html)
    informe_meta = parse_informe_nacional_xlsx(informe_xlsx)

    ts = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
    native = station_native_table(
        daily_meta,
        monthly_meta,
        mapas2_meta,
        informe_meta,
        retrieved_at=RetrievedAt(ts),
    )
    assert native.data["CODIGO ESTACION"].to_list() == ["01001002", "02112007"]
    assert native.data["ALTITUD"].to_list() == [None, 1240]
    assert native.data["ALTITUD_RAW"].to_list() == ["0", "1240"]
    assert native.data["in_daily_zip"].to_list() == [True, True]
    assert native.data["in_monthly_zip"].to_list() == [True, False]
    assert native.data["in_mapas2_json"].to_list() == [True, False]
    assert native.data["in_informe_nacional"].to_list() == [True, False]

    native_identity = NativeTableIdentity(
        location_kind="retained",
        repository_path="maintenance/catalogue/cl_dga/official/native.parquet",
        revision="a" * 40,
        sha256="b" * 64,
        byte_size=1234,
    )
    recordings = (
        RecordingReference(
            recording_id="rec-zip",
            repository_path="maintenance/catalogue/cl_dga/official/web/daily.zip",
            source_url="https://mapas2.mop.gob.cl/caudal_diario_historico.zip",
            retrieved_at=ts,
            media_type="application/zip",
            sha256="c" * 64,
        ),
        RecordingReference(
            recording_id="rec-terms",
            repository_path="maintenance/catalogue/cl_dga/official/web/terms.body",
            source_url="https://www.mop.gob.cl/condiciones-de-uso/",
            retrieved_at=ts,
            media_type="text/html; charset=UTF-8",
            sha256="d" * 64,
        ),
    )
    acquisitions = (
        AcquisitionRecord(
            acquisition_id="acq-zip",
            method="http_request",
            instant_type="retrieval",
            description="Historical ZIP",
            requested_from=("https://mapas2.mop.gob.cl/caudal_diario_historico.zip",),
            retrieved_at_start=ts,
            recording_ids=("rec-zip",),
        ),
        AcquisitionRecord(
            acquisition_id="acq-terms",
            method="http_request",
            instant_type="retrieval",
            description="MOP terms",
            requested_from=("https://www.mop.gob.cl/condiciones-de-uso/",),
            retrieved_at_start=ts,
            recording_ids=("rec-terms",),
        ),
    )
    bindings = (
        FactBinding(
            fact_group="zip_meta",
            facts=(
                "source.station.zip_metadata",
                "source.station.supporting_reconciliation",
                "source.station.altitud_unit",
                "source.product.daily_discharge_zip",
                "source.product.monthly_discharge_zip",
            ),
            source_id="cl_dga",
            acquisition_id="acq-zip",
        ),
        FactBinding(
            fact_group="terms",
            facts=("source.provider.terms", "source.provider.attribution"),
            source_id="cl_dga",
            acquisition_id="acq-terms",
        ),
    )
    prov = build_acquisition_provenance(
        native_identity,
        recordings,
        acquisitions=acquisitions,
        source_bindings=bindings,
        statements=(
            SourceStatement(
                kind="terms",
                exact_text=MOP_TERMS_TEXT,
                recording_id="rec-terms",
                fact="source.provider.terms",
            ),
        ),
    )
    cat = build_catalogue(
        native,
        STATION_CATALOGUE_ORIGINS,
        checked_on=date(2026, 11, 18),
        provenance=prov,
        station_metadata=project_station_metadata(
            native,
            pl.DataFrame({"provider_id": ["cl_dga", "cl_dga"], "station_id": ["01001002", "02112007"]}),
        ),
    )
    assert cat.provider_info["license"] is None
    assert cat.provider_info["bulk_observations"] == "none"
    assert "condiciones-de-uso" in str(cat.provider_info["citation"])
    assert cat.stations["station_id"].to_list() == ["01001002", "02112007"]
    assert cat.stations["crs"].to_list() == ["unknown", "unknown"]
    assert cat.products["product_id"].to_list() == ["discharge_daily", "discharge_monthly_mean"]
    avail = {(r["station_id"], r["product_id"]): r["availability"] for r in cat.station_products.iter_rows(named=True)}
    assert avail == {
        ("01001002", "discharge_daily"): "available",
        ("01001002", "discharge_monthly_mean"): "available",
        ("02112007", "discharge_daily"): "available",
        ("02112007", "discharge_monthly_mean"): "unavailable",
    }
    assert cat.station_products["published_record_start_date"].null_count() == 4
    assert cat.station_products["published_record_end_date"].null_count() == 4

    # Cross-ZIP coordinate disagreement must fail loudly rather than picking silently.
    conflicting_monthly = _make_zip_bytes(
        "caudal_medio_mensual_historico.txt",
        list(MONTHLY_HEADER),
        [
            {
                "CODIGO ESTACION": "01001002",
                "NOMBRE ESTACION": "RIO CAQUENA EN VERTEDERO",
                "COD_REGION": "1",
                "REGION": "DE TARAPACA",
                "COMUNA": "PUTRE",
                "LAT": "0180000",
                "LONG": "0691525",
                "UTM_ESTE": "472792",
                "UTM_NORTE": "8010036",
                "ALTITUD": "0",
                "Año": "2020",
                "Mes": "1",
                "Caudal_Medio_mensual": "0.5",
                "Unidad": "m3/s",
            },
        ],
    )
    with pytest.raises(FatalContractError, match="disagree"):
        station_native_table(
            daily_meta,
            parse_historical_zip_metadata(conflicting_monthly, kind="monthly"),
            mapas2_meta,
            informe_meta,
            retrieved_at=RetrievedAt(ts),
        )


def test_cl_dga_end_to_end_read_write_and_load_artifact(tmp_path) -> None:
    import hashlib
    import json
    from datetime import UTC, datetime

    from rivretrieve._internal.acquisition_provenance import (
        AuthoredDeclarationInput,
        CodeReference,
        RetainedInputReceipt,
        RetainedInputReference,
    )
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.catalogues.inputs import select_catalogue_build_inputs
    from rivretrieve._internal.catalogues.native import write_native_table
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.cl_dga.generate_catalogue import (
        DAILY_HEADER,
        MONTHLY_HEADER,
        main,
        read_native_sources,
        selected_supporting_inputs,
    )
    from rivretrieve._internal.providers.cl_dga.origins import (
        CATALOGUE_BUILD_DECLARATIONS,
        MOP_TERMS_TEXT,
        NATIVE_TABLE_ACQUISITION_IDS,
    )

    ev_root = tmp_path / "evidence"
    web = ev_root / "maintenance/catalogue/cl_dga/official/web"
    web.mkdir(parents=True)

    daily_bytes = _make_zip_bytes(
        "caudal_diario_historico.txt",
        list(DAILY_HEADER),
        [
            {
                "CODIGO ESTACION": "01001002",
                "NOMBRE ESTACION": "RIO CAQUENA EN VERTEDERO",
                "COD_REGION": "1",
                "REGION": "DE TARAPACA",
                "COMUNA": "PUTRE",
                "LAT": "0175952",
                "LONG": "0691525",
                "UTM_ESTE": "472792",
                "UTM_NORTE": "8010036",
                "ALTITUD": "0",
                "FECHA": "01/01/2020",
                "Caudal_diario": "0.5",
                "Unidad": "m3/s",
            }
        ],
    )
    monthly_bytes = _make_zip_bytes(
        "caudal_medio_mensual_historico.txt",
        list(MONTHLY_HEADER),
        [
            {
                "CODIGO ESTACION": "01001002",
                "NOMBRE ESTACION": "RIO CAQUENA EN VERTEDERO",
                "COD_REGION": "1",
                "REGION": "DE TARAPACA",
                "COMUNA": "PUTRE",
                "LAT": "0175952",
                "LONG": "0691525",
                "UTM_ESTE": "472792",
                "UTM_NORTE": "8010036",
                "ALTITUD": "0",
                "Año": "2020",
                "Mes": "1",
                "Caudal_Medio_mensual": "0.5",
                "Unidad": "m3/s",
            }
        ],
    )
    mapas2_bytes = _make_mapas2_html(
        [
            {
                "cod_estacion": "01001002",
                "estado_estacion": "Activa",
                "glosa_comuna": "Putre",
                "glosa_region": "De Tarapaca",
                "glosa_tipo": "Fluviometricas",
                "glosa_tipo_inac": "",
                "gls_estacion": "Rio Caquena En Vertedero",
                "id": 1,
                "val_altitud": 0,
                "val_latitud": -17.9978,
                "val_longitud": -69.2569,
            }
        ]
    )
    informe_bytes = _make_informe_xlsx_bytes(
        [
            [
                "01001002",
                "RIO CAQUENA EN VERTEDERO",
                "01/01/1970",
                "DE TARAPACA",
                "PARINACOTA",
                "PUTRE",
                "ALTIPLANICAS",
                "Sub",
                "SubSub",
                8010036,
                472792,
                19,
                "17°59'52''",
                "69°15'25''",
                0,
                "*FLUVIOMETRICA\n",
            ]
        ]
    )
    hidrolinea_bytes = b"<html>01001002-0</html>"
    terms_bytes = MOP_TERMS_TEXT.encode("utf-8")

    ts = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
    specs = [
        (
            "daily_zip",
            "daily.zip",
            daily_bytes,
            "https://mapas2.mop.gob.cl/caudal_diario_historico.zip",
            "application/zip",
        ),
        (
            "monthly_zip",
            "monthly.zip",
            monthly_bytes,
            "https://mapas2.mop.gob.cl/caudal_medio_mensual_historico.zip",
            "application/zip",
        ),
        ("mapas2_home", "mapas2.html", mapas2_bytes, "https://mapas2.mop.gob.cl/", "text/html"),
        (
            "informe_nacional",
            "informe.xlsx",
            informe_bytes,
            "https://dga.mop.gob.cl/informe.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        ("hidrolinea_home", "hidrolinea.html", hidrolinea_bytes, "https://snia.mop.gob.cl/sat/", "text/html"),
        ("mop_terms", "terms.html", terms_bytes, "https://www.mop.gob.cl/condiciones-de-uso/", "text/html"),
    ]
    captures = []
    input_refs = []
    acq_records = []
    bindings = []
    for kind, fname, payload, url, mtype in specs:
        fpath = web / fname
        fpath.write_bytes(payload)
        rpath = web / f"{fname}.receipt.json"
        rpath.write_text("{}")
        rel_body = f"maintenance/catalogue/cl_dga/official/web/{fname}"
        rel_receipt = f"maintenance/catalogue/cl_dga/official/web/{fname}.receipt.json"
        sha = hashlib.sha256(payload).hexdigest()
        rsha = hashlib.sha256(b"{}").hexdigest()
        captures.append(
            {
                "kind": kind,
                "body": rel_body,
                "receipt": rel_receipt,
                "recording": {
                    "recording_id": f"rec-{kind}",
                    "repository_path": rel_body,
                    "source_url": url,
                    "retrieved_at": ts.isoformat(),
                    "media_type": mtype,
                    "sha256": sha,
                },
            }
        )
        for rel, d, sz, role in (
            (rel_body, sha, len(payload), "publisher_original"),
            (rel_receipt, rsha, 2, "acquisition_receipt"),
        ):
            input_refs.append(
                RetainedInputReference(
                    archive_repository="https://github.com/RivRetrieve/verification-evidence",
                    archive_revision="e" * 40,
                    collection_id="cl_dga-catalogue-sources-2026-11-18-v1",
                    manifest_sha256="f" * 64,
                    artifact_id=f"art-{fname}-{role}",
                    sha256=d,
                    byte_size=sz,
                    role=role,
                    consumer_path=rel,
                )
            )
    acq_map = {
        "cl-dga-mapas2-caudal-diario-nacional": (
            "rec-daily_zip",
            "https://mapas2.mop.gob.cl/caudal_diario_historico.zip",
        ),
        "cl-dga-mapas2-caudal-medio-mensual-nacional": (
            "rec-monthly_zip",
            "https://mapas2.mop.gob.cl/caudal_medio_mensual_historico.zip",
        ),
        "cl-dga-mapas2-home": ("rec-mapas2_home", "https://mapas2.mop.gob.cl/"),
        "cl-dga-informe-nacional-2026-09": ("rec-informe_nacional", "https://dga.mop.gob.cl/informe.xlsx"),
        "cl-dga-snia-hidrolinea-home": ("rec-hidrolinea_home", "https://snia.mop.gob.cl/sat/"),
        "cl-dga-mop-terms": ("rec-mop_terms", "https://www.mop.gob.cl/condiciones-de-uso/"),
    }
    for aid, (rid, url) in acq_map.items():
        acq_records.append(
            {
                "acquisition_id": aid,
                "method": "http_request",
                "instant_type": "retrieval",
                "description": aid,
                "requested_from": [url],
                "retrieved_at_start": ts.isoformat(),
                "recording_ids": [rid],
            }
        )
    bindings = [
        {
            "fact_group": "daily_zip",
            "facts": ["source.product.daily_discharge_zip", "source.station.zip_metadata"],
            "source_id": "cl_dga",
            "acquisition_id": "cl-dga-mapas2-caudal-diario-nacional",
        },
        {
            "fact_group": "monthly_zip",
            "facts": ["source.product.monthly_discharge_zip"],
            "source_id": "cl_dga",
            "acquisition_id": "cl-dga-mapas2-caudal-medio-mensual-nacional",
        },
        {
            "fact_group": "supporting",
            "facts": ["source.station.supporting_reconciliation", "source.station.altitud_unit"],
            "source_id": "cl_dga",
            "acquisition_id": "cl-dga-informe-nacional-2026-09",
        },
        {
            "fact_group": "mapas2",
            "facts": ["source.station.mapas2_json"],
            "source_id": "cl_dga",
            "acquisition_id": "cl-dga-mapas2-home",
        },
        {
            "fact_group": "hidrolinea",
            "facts": ["source.station.check_digit_inventory"],
            "source_id": "cl_dga",
            "acquisition_id": "cl-dga-snia-hidrolinea-home",
        },
        {
            "fact_group": "terms",
            "facts": ["source.provider.terms", "source.provider.attribution"],
            "source_id": "cl_dga",
            "acquisition_id": "cl-dga-mop-terms",
        },
    ]

    sel_path = ev_root / "maintenance/catalogue/cl_dga/official/selection.json"
    review_path = ev_root / "maintenance/catalogue/station_metadata/review.json"
    review_path.parent.mkdir(parents=True)
    review_path.write_text("{}")

    native_out_dir = tmp_path / "native_out"
    native_out_dir.mkdir()
    pre_sel = {
        "schema_version": 1,
        "checked_on": "2026-11-18",
        "captures": captures,
    }
    sel_path.write_text(json.dumps(pre_sel))
    decl_inputs = (
        AuthoredDeclarationInput(
            consumer_path="maintenance/catalogue/cl_dga/official/selection.json",
            declaration=CodeReference(
                repository="https://github.com/RivRetrieve/verification-evidence",
                revision="e" * 40,
                repository_path="declarations/cl_dga/catalogue.json",
            ),
            sha256=hashlib.sha256(sel_path.read_bytes()).hexdigest(),
            byte_size=sel_path.stat().st_size,
        ),
        AuthoredDeclarationInput(
            consumer_path="maintenance/catalogue/station_metadata/review.json",
            declaration=CodeReference(
                repository="https://github.com/RivRetrieve/verification-evidence",
                revision="e" * 40,
                repository_path="declarations/station_metadata/review.json",
            ),
            sha256=hashlib.sha256(review_path.read_bytes()).hexdigest(),
            byte_size=review_path.stat().st_size,
        ),
    )
    receipt = RetainedInputReceipt(
        schema_version=3,
        code_revision="1" * 40,
        declaration_revision="1" * 40,
        archive_code_revision="e" * 40,
        inputs=tuple(input_refs),
        declaration_inputs=decl_inputs,
    )
    native = read_native_sources(
        ev_root,
        selection_path="maintenance/catalogue/cl_dga/official/selection.json",
        input_receipt=receipt,
    )
    native_file = ev_root / "maintenance/catalogue/cl_dga/official/native.parquet"
    write_native_table(native, native_file)
    nbytes = native_file.read_bytes()
    nsha = hashlib.sha256(nbytes).hexdigest()

    full_sel = {
        **pre_sel,
        "native_table": "maintenance/catalogue/cl_dga/official/native.parquet",
        "native_revision": "1" * 40,
        "publication_acquisitions": acq_records,
        "source_bindings": bindings,
        "statements": [
            {
                "kind": "terms",
                "exact_text": MOP_TERMS_TEXT,
                "recording_id": "rec-mop_terms",
                "fact": "source.provider.terms",
                "verification_status": "verified_public_recording",
            }
        ],
    }
    sel_path.write_text(json.dumps(full_sel))
    full_decl = (
        AuthoredDeclarationInput(
            consumer_path="maintenance/catalogue/cl_dga/official/selection.json",
            declaration=CodeReference(
                repository="https://github.com/RivRetrieve/verification-evidence",
                revision="e" * 40,
                repository_path="declarations/cl_dga/catalogue.json",
            ),
            sha256=hashlib.sha256(sel_path.read_bytes()).hexdigest(),
            byte_size=sel_path.stat().st_size,
        ),
        decl_inputs[1],
    )
    full_receipt = RetainedInputReceipt(
        schema_version=3,
        code_revision="1" * 40,
        declaration_revision="1" * 40,
        archive_code_revision="e" * 40,
        inputs=(
            *input_refs,
            RetainedInputReference(
                archive_repository="https://github.com/RivRetrieve/verification-evidence",
                archive_revision="e" * 40,
                collection_id="cl_dga-catalogue-native-2026-11-18-v1",
                manifest_sha256="f" * 64,
                artifact_id="official-native",
                sha256=nsha,
                byte_size=len(nbytes),
                role="derived_input",
                consumer_path="maintenance/catalogue/cl_dga/official/native.parquet",
            ),
        ),
        declaration_inputs=full_decl,
    )
    from rivretrieve._internal.providers.cl_dga.generate_catalogue import read_catalogue_sources

    sources = read_catalogue_sources(
        ev_root,
        selection_path="maintenance/catalogue/cl_dga/official/selection.json",
        input_receipt=full_receipt,
    )
    support = selected_supporting_inputs(sources.provenance, full_sel)
    assert len(support) == len(specs)
    build_inputs = select_catalogue_build_inputs(
        sources.provenance,
        full_receipt,
        NATIVE_TABLE_ACQUISITION_IDS,
        CATALOGUE_BUILD_DECLARATIONS,
        supporting_inputs=support,
    )
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(full_receipt.model_dump_json())
    build_inputs_path = tmp_path / "build_inputs.json"
    build_inputs_path.write_text(build_inputs.model_dump_json())
    cat_out = tmp_path / "catalogue_out"
    assert (
        main(
            [
                "--evidence-root",
                str(ev_root),
                "--selection",
                "maintenance/catalogue/cl_dga/official/selection.json",
                "--input-receipt",
                str(receipt_path),
                "--build-inputs",
                str(build_inputs_path),
                "--out",
                str(cat_out),
            ]
        )
        == 0
    )
    artifact = load_packaged_catalogue_artifact(cat_out, on_issue="raise")
    assert artifact.provider_info["license"] is None
    assert artifact.stations["station_id"].to_list() == ["01001002"]
    assert artifact.stations["crs"].to_list() == ["unknown"]
    with pytest.raises(FatalContractError, match="new path"):
        main(
            [
                "--evidence-root",
                str(ev_root),
                "--input-receipt",
                str(receipt_path),
                "--build-inputs",
                str(build_inputs_path),
                "--out",
                str(cat_out),
            ]
        )
