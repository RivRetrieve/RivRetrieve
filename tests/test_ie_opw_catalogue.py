"""Synthetic Ireland OPW (`ie_opw`) station catalogue, origin, and metadata checks."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionRecord,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    RetainedInputReceipt,
    SourceStatement,
)
from rivretrieve._internal.catalogue_origins import (
    Field,
    NativeColumn,
    enforce_catalogue_origins,
    validate_catalogue_origins,
)
from rivretrieve._internal.catalogues.native import RetrievedAt, write_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ie_opw.generate_catalogue import (
    _check_complete_zip_bytes,
    catalogue_tables,
    is_excluded_station,
    read_catalogue_sources,
    station_native_table,
    station_product_associations,
)
from rivretrieve._internal.providers.ie_opw.origins import (
    STATION_CATALOGUE_ORIGINS,
    build_acquisition_provenance,
)
from rivretrieve._internal.providers.ie_opw.series import PRODUCT_SPECS, describe_associations
from rivretrieve._internal.providers.ie_opw.station_metadata import project_station_metadata
from rivretrieve._internal.source_series import admission


def _opw_station(
    sno: str,
    *,
    name: str = "Sandy Mills",
    stn_class: str = "Level & Flow",
    wto: str = "DEELE",
    catchment_size: str = "113.00 km²",
    lat: str = "54.83831806",
    lon: str = "-7.575758056",
) -> dict[str, object]:
    return {
        "station_id": "12211",
        "station_no": sno,
        "site_no": "0",
        "station_name": name,
        "station_latitude": lat,
        "station_longitude": lon,
        "WTO_OBJECT": wto,
        "CATCHMENT_SIZE": catchment_size,
        "Stn_Class": stn_class,
        "station_status": "Active",
        "station_gauge_datum_unit": "Malin Head OSGM15",
        "GAUGE_DATUM": "3.655",
    }


def _geojson(coords_by_ref: dict[str, tuple[float, float]]) -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": [
            {
                "type": "Feature",
                "properties": {"name": f"Station {ref}", "ref": ref},
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
            for ref, (lat, lon) in coords_by_ref.items()
        ],
    }


def _provenance():
    ts = datetime(2026, 11, 23, tzinfo=UTC)
    rec = RecordingReference(
        recording_id="opw-hydro-stations-json",
        repository_path="web/opw-hydro-stations-json.body",
        source_url="https://waterlevel.ie/hydro-data/data/internet/stations/stations.json",
        retrieved_at=ts,
        media_type="application/json",
        sha256="a" * 64,
    )
    return build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path="maintenance/catalogue/ie_opw/official/native.parquet",
            revision="b" * 40,
            sha256="c" * 64,
            byte_size=20,
        ),
        (rec,),
        acquisitions=(
            AcquisitionRecord(
                acquisition_id="opw-hydro-stations-json",
                method="http_request",
                instant_type="retrieval",
                description="OPW Hydro-Data stations.json registry",
                requested_from=("https://waterlevel.ie/hydro-data/data/internet/stations/stations.json",),
                retrieved_at_start=ts,
                recording_ids=("opw-hydro-stations-json",),
            ),
        ),
        source_bindings=(
            FactBinding(
                fact_group="stations",
                source_id="ie_opw",
                acquisition_id="opw-hydro-stations-json",
                facts=(
                    "source.station.registry",
                    "source.station.geojson_crs",
                    "source.station.catchment_size_unit",
                    "source.station_product.associations",
                    "source.station_product.year_json_q_census",
                    "source.station_product.year_json_s_census",
                    "source.station_product.year_json_twater_census",
                    "source.station_product.complete_zip_census",
                    "source.series.fields",
                    "source.product.unit_definitions",
                    "source.series.temporal_semantics",
                    "source.series.stage_vertical_reference",
                    "source.series.annotations",
                    "source.provider.terms",
                    "source.provider.attribution",
                ),
            ),
        ),
        statements=(
            SourceStatement(
                kind="license",
                exact_text="CC BY 4.0",
                recording_id="opw-hydro-stations-json",
                fact="source.provider.terms",
                verification_status="verified_public_recording",
            ),
            SourceStatement(
                kind="citation",
                exact_text="Office of Public Works (http://waterlevel.ie)",
                recording_id="opw-hydro-stations-json",
                fact="source.provider.attribution",
                verification_status="verified_public_recording",
            ),
        ),
    )


def test_exclusion_rules_filter_non_rivers_and_keep_borderline_river_gauges() -> None:
    assert is_excluded_station(_opw_station("80101", stn_class="Rain Gauge", wto=""))
    assert is_excluded_station(_opw_station("18061", stn_class="Tidal", wto="LEE ESTUARY"))
    assert is_excluded_station(_opw_station("06062", stn_class="Inactive", wto="SEA"))
    assert is_excluded_station(_opw_station("27066", stn_class="Level & Flow", wto="FERGUS ESTY."))
    assert is_excluded_station(_opw_station("12002", stn_class="Level & Flow", wto="SLANEY"))
    assert is_excluded_station(_opw_station("34083", stn_class="Level", wto="LOUGH MASK"))
    assert is_excluded_station(_opw_station("30089", stn_class="Level", wto="L     CORRIB", catchment_size="0.00 km²"))
    assert is_excluded_station(_opw_station("29002", stn_class="Level & Flow", wto="RAHASANE TURLOUGH"))
    assert is_excluded_station(_opw_station("30034", stn_class="Inactive", wto="CONG CANAL"))

    for kept in ("01041", "30061", "26075", "35071", "03055", "34018", "30017", "09045", "10047"):
        wto = "CORRIB ESTY." if kept == "30061" else "L.    MELVIN" if kept == "35071" else "RIVER"
        assert not is_excluded_station(_opw_station(kept, wto=wto)), kept


def test_native_table_rejects_bad_coords_bad_units_and_geojson_mismatch() -> None:
    with pytest.raises(FatalContractError, match="Ireland bounds"):
        station_native_table(
            [_opw_station("01041", lat="10.0", lon="-7.5")],
            _geojson({"01041": (10.0, -7.5)}),
            retrieved_at=RetrievedAt(datetime(2026, 11, 23, tzinfo=UTC)),
        )
    with pytest.raises(FatalContractError, match="GeoJSON coordinate mismatch"):
        station_native_table(
            [_opw_station("01041", lat="54.83831806", lon="-7.575758056")],
            _geojson({"01041": (53.0, -7.5)}),
            retrieved_at=RetrievedAt(datetime(2026, 11, 23, tzinfo=UTC)),
        )
    with pytest.raises(FatalContractError, match="CATCHMENT_SIZE"):
        station_native_table(
            [_opw_station("01041", catchment_size="113 ha")],
            _geojson({"01041": (54.83831806, -7.575758056)}),
            retrieved_at=RetrievedAt(datetime(2026, 11, 23, tzinfo=UTC)),
        )


def test_catalogue_projects_metadata_nulls_inline_units_and_witnesses() -> None:
    native = station_native_table(
        [
            _opw_station("01041", lat="54.83831806", lon="-7.575758056"),
            _opw_station("14124", name="Rathstewart", wto="", catchment_size="", lat="52.99423023", lon="-6.98381777"),
            _opw_station("80101", stn_class="Rain Gauge"),
        ],
        _geojson({"01041": (54.83831806, -7.575758056)}),
        retrieved_at=RetrievedAt(datetime(2026, 11, 23, tzinfo=UTC)),
    )
    assert native.data["station_no"].to_list() == ["01041", "14124"]
    assoc = station_product_associations(
        native,
        layer_witnesses={"stage_instantaneous": {"01041": "Layer 10"}},
        station_witnesses={("14124", "discharge_daily_mean"): ("unavailable", "0 rows")},
    )
    products, stations, pairs = catalogue_tables(native, assoc, checked_on=date(2026, 11, 23))
    assert products.height == 12
    assert stations["crs"].to_list() == ["EPSG:4326", "EPSG:4326"]
    assert pairs.height == 24
    assert (
        pairs.filter((pl.col("station_id") == "01041") & (pl.col("product_id") == "stage_instantaneous"))[
            "availability"
        ].item()
        == "available"
    )
    assert (
        pairs.filter((pl.col("station_id") == "14124") & (pl.col("product_id") == "discharge_daily_mean"))[
            "availability"
        ].item()
        == "unavailable"
    )
    assert (
        pairs.filter((pl.col("station_id") == "01041") & (pl.col("product_id") == "discharge_daily_mean"))[
            "availability"
        ].item()
        == "unknown"
    )
    with pytest.raises(FatalContractError, match="Conflicting"):
        station_product_associations(
            native,
            layer_witnesses={"discharge_instantaneous": {"14124": "Layer 30"}},
            station_witnesses={("14124", "discharge_instantaneous"): ("unavailable", "#rows;0")},
        )

    assert validate_catalogue_origins(ProviderId("ie_opw"), STATION_CATALOGUE_ORIGINS, native, stations) == []
    with pytest.raises(FatalContractError, match="station_id"):
        enforce_catalogue_origins(
            ProviderId("ie_opw"),
            {**STATION_CATALOGUE_ORIGINS, "station_id": Field(NativeColumn("station_name"))},
            native,
            stations,
        )

    meta = project_station_metadata(native, stations)
    areas = meta.filter(pl.col("attribute_role") == "drainage_area").sort("station_id")
    assert areas["state"].to_list() == ["value", "source_null"]
    assert areas["source_unit"].to_list() == ["km²", None]
    assert meta.filter(pl.col("attribute_role") == "elevation")["state"].to_list() == ["no_metadata", "no_metadata"]

    desc = describe_associations()
    assert len(desc.descriptions) == 12
    for spec in PRODUCT_SPECS:
        assert admission(spec.series_mapping().physical_facts()).status == "supported"
    _provenance()


def test_complete_zip_parser_distinguishes_empty_and_populated_series() -> None:
    empty_buf = io.BytesIO()
    with zipfile.ZipFile(empty_buf, "w") as zf:
        zf.writestr(
            "tsvalues.csv",
            "#station_no;14124\n#stationparameter_name;Q\n#ts_shortname;WEB.Cmd.Runoff\n"
            "#ts_unitsymbol;cumec\n#rows;0\n#Timestamp;Value;Quality Code\n",
        )
    assert _check_complete_zip_bytes(empty_buf.getvalue(), station_no="14124", parameter="Q")[0] == "unavailable"

    pop_buf = io.BytesIO()
    with zipfile.ZipFile(pop_buf, "w") as zf:
        zf.writestr(
            "tsvalues.csv",
            "#station_no;14124\n#stationparameter_name;TWater\n#ts_shortname;WEB.Cmd.P-Water-Temp\n"
            "#ts_unitsymbol;°C\n#Timestamp;Value;Quality Code\n"
            "2025-10-06T00:00:00.000Z;;-1\n2025-10-06T01:00:00.000Z;11.6;254\n",
        )
    assert _check_complete_zip_bytes(pop_buf.getvalue(), station_no="14124", parameter="TWater")[0] == "available"


def test_read_catalogue_sources_handles_verified_404_receipts_and_partial_year_json(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    web = evidence / "maintenance/catalogue/ie_opw/official/web"
    web.mkdir(parents=True)

    stations_bytes = json.dumps([_opw_station("01041")]).encode("utf-8")
    geojson_bytes = json.dumps(_geojson({"01041": (54.83831806, -7.575758056)})).encode("utf-8")
    partial_year_bytes = json.dumps(
        [
            {
                "station_no": "01041",
                "ts_shortname": "WEB.Day.Mean",
                "ts_unitsymbol": "cumec",
                "data": [["2025-07-15T00:00:00.000Z", 2.5, 31]],
            }
        ]
    ).encode("utf-8")
    not_found_body = b"<html><body>404 Not Found</body></html>"
    not_found_url = "https://waterlevel.ie/hydro-data/data/internet/stations/0/01041/TWater/year.json"
    not_found_receipt = json.dumps(
        {
            "http_status": 404,
            "sha256": hashlib.sha256(not_found_body).hexdigest(),
            "byte_size": len(not_found_body),
            "url": not_found_url,
        }
    ).encode("utf-8")

    files = {
        "maintenance/catalogue/ie_opw/official/web/stations.body": stations_bytes,
        "maintenance/catalogue/ie_opw/official/web/geojson.body": geojson_bytes,
        "maintenance/catalogue/ie_opw/official/web/q-year.body": partial_year_bytes,
        "maintenance/catalogue/ie_opw/official/web/twater-404.body": not_found_body,
        "maintenance/catalogue/ie_opw/official/web/twater-404.receipt.json": not_found_receipt,
    }
    for rel, content in files.items():
        (evidence / rel).write_bytes(content)

    native = station_native_table(
        [_opw_station("01041")],
        _geojson({"01041": (54.83831806, -7.575758056)}),
        retrieved_at=RetrievedAt(datetime(2026, 11, 27, tzinfo=UTC)),
    )
    native_rel = "maintenance/catalogue/ie_opw/official/native.parquet"
    write_native_table(native, evidence / native_rel)
    files[native_rel] = (evidence / native_rel).read_bytes()

    ts = datetime(2026, 11, 27, tzinfo=UTC)
    selection_rel = "maintenance/catalogue/ie_opw/official/selection.json"
    all_facts = (
        "source.station.registry",
        "source.station.catchment_size_unit",
        "source.station.geojson_crs",
        "source.station_product.associations",
        "source.station_product.year_json_q_census",
        "source.station_product.year_json_s_census",
        "source.station_product.year_json_twater_census",
        "source.station_product.complete_zip_census",
        "source.series.fields",
        "source.product.unit_definitions",
        "source.series.temporal_semantics",
        "source.series.stage_vertical_reference",
        "source.series.annotations",
        "source.provider.terms",
        "source.provider.attribution",
    )
    selection_doc = {
        "schema_version": 1,
        "checked_on": "2026-11-27",
        "native_table": native_rel,
        "native_revision": "b" * 40,
        "captures": [
            {
                "kind": "stations_json",
                "body": "maintenance/catalogue/ie_opw/official/web/stations.body",
                "receipt": "maintenance/catalogue/ie_opw/official/web/stations.receipt.json",
                "recording": {
                    "recording_id": "opw-hydro-stations-json",
                    "repository_path": "maintenance/catalogue/ie_opw/official/web/stations.body",
                    "source_url": "https://waterlevel.ie/hydro-data/data/internet/stations/stations.json",
                    "retrieved_at": ts.isoformat(),
                    "media_type": "application/json",
                    "sha256": hashlib.sha256(stations_bytes).hexdigest(),
                },
            },
            {
                "kind": "geojson_crs",
                "body": "maintenance/catalogue/ie_opw/official/web/geojson.body",
                "receipt": "maintenance/catalogue/ie_opw/official/web/geojson.receipt.json",
                "recording": {
                    "recording_id": "opw-geojson-root",
                    "repository_path": "maintenance/catalogue/ie_opw/official/web/geojson.body",
                    "source_url": "https://waterlevel.ie/geojson/",
                    "retrieved_at": ts.isoformat(),
                    "media_type": "application/json",
                    "sha256": hashlib.sha256(geojson_bytes).hexdigest(),
                },
            },
            {
                "kind": "year_json",
                "station_id": "01041",
                "parameter": "Q",
                "body": "maintenance/catalogue/ie_opw/official/web/q-year.body",
                "recording": {
                    "recording_id": "opw-01041-q-year-json",
                    "repository_path": "maintenance/catalogue/ie_opw/official/web/q-year.body",
                    "source_url": "https://waterlevel.ie/hydro-data/data/internet/stations/0/01041/Q/year.json",
                    "retrieved_at": ts.isoformat(),
                    "media_type": "application/json",
                    "sha256": hashlib.sha256(partial_year_bytes).hexdigest(),
                },
            },
            {
                "kind": "year_json",
                "station_id": "01041",
                "parameter": "TWater",
                "http_status": 404,
                "body": "maintenance/catalogue/ie_opw/official/web/twater-404.body",
                "receipt": "maintenance/catalogue/ie_opw/official/web/twater-404.receipt.json",
                "recording": {
                    "recording_id": "opw-01041-twater-year-json",
                    "repository_path": "maintenance/catalogue/ie_opw/official/web/twater-404.body",
                    "source_url": not_found_url,
                    "retrieved_at": ts.isoformat(),
                    "media_type": "text/html",
                    "sha256": hashlib.sha256(not_found_body).hexdigest(),
                },
            },
        ],
        "publication_acquisitions": [
            {
                "acquisition_id": "opw-hydro-stations-json",
                "method": "http_request",
                "instant_type": "retrieval",
                "description": "Synthetic OPW stations registry",
                "requested_from": [
                    "https://waterlevel.ie/hydro-data/data/internet/stations/stations.json",
                ],
                "retrieved_at_start": ts.isoformat(),
                "recording_ids": ["opw-hydro-stations-json"],
            },
            {
                "acquisition_id": "opw-all",
                "method": "http_campaign",
                "instant_type": "retrieval_interval",
                "description": "Synthetic OPW probe batch",
                "requested_from": [
                    "https://waterlevel.ie/geojson/",
                    "https://waterlevel.ie/hydro-data/data/internet/stations/0/01041/Q/year.json",
                    not_found_url,
                ],
                "retrieved_at_start": ts.isoformat(),
                "retrieved_at_end": ts.isoformat(),
                "recording_ids": [
                    "opw-geojson-root",
                    "opw-01041-q-year-json",
                    "opw-01041-twater-year-json",
                ],
            },
        ],
        "source_bindings": [
            {
                "fact_group": "terms_and_registry",
                "facts": [
                    "source.station.registry",
                    "source.station.catchment_size_unit",
                    "source.provider.terms",
                    "source.provider.attribution",
                ],
                "source_id": "ie_opw",
                "acquisition_id": "opw-hydro-stations-json",
            },
            {
                "fact_group": "all",
                "facts": [
                    f
                    for f in all_facts
                    if f
                    not in {
                        "source.station.registry",
                        "source.station.catchment_size_unit",
                        "source.provider.terms",
                        "source.provider.attribution",
                    }
                ],
                "source_id": "ie_opw",
                "acquisition_id": "opw-all",
            },
        ],
        "statements": [
            {
                "kind": "license",
                "exact_text": "CC BY 4.0",
                "recording_id": "opw-hydro-stations-json",
                "fact": "source.provider.terms",
                "verification_status": "verified_public_recording",
            },
            {
                "kind": "citation",
                "exact_text": "Office of Public Works (http://waterlevel.ie)",
                "recording_id": "opw-hydro-stations-json",
                "fact": "source.provider.attribution",
                "verification_status": "verified_public_recording",
            },
        ],
    }
    selection_bytes = json.dumps(selection_doc).encode("utf-8")
    (evidence / selection_rel).write_bytes(selection_bytes)

    input_receipt = RetainedInputReceipt.model_validate(
        {
            "schema_version": 3,
            "code_revision": "d" * 40,
            "declaration_revision": "d" * 40,
            "archive_code_revision": "a" * 40,
            "inputs": [
                {
                    "archive_repository": "https://github.com/RivRetrieve/verification-evidence",
                    "archive_revision": "a" * 40,
                    "consumer_path": rel,
                    "collection_id": "ie_opw-synthetic",
                    "manifest_sha256": "e" * 64,
                    "artifact_id": f"art-{idx}",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "byte_size": len(content),
                    "role": (
                        "derived_input"
                        if rel.endswith(".parquet")
                        else "acquisition_receipt"
                        if rel.endswith(".receipt.json")
                        else "response_recording"
                    ),
                }
                for idx, (rel, content) in enumerate(files.items())
            ],
            "declaration_inputs": [
                {
                    "consumer_path": selection_rel,
                    "declaration": {
                        "repository": "https://github.com/RivRetrieve/verification-evidence",
                        "repository_path": "declarations/ie_opw/catalogue.json",
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

    sources = read_catalogue_sources(evidence, selection_path=selection_rel, input_receipt=input_receipt)
    assoc = dict(sources.associations.select("product_id", "availability").iter_rows())
    assert assoc["discharge_daily_mean"] == "available"
    assert assoc["discharge_daily_min"] == "unavailable"
    assert assoc["discharge_daily_max"] == "unavailable"
    assert assoc["water_temperature_daily_mean"] == "unavailable"
    assert assoc["water_temperature_daily_min"] == "unavailable"
    assert assoc["water_temperature_daily_max"] == "unavailable"
    assert assoc["stage_daily_mean"] == "unknown"

    # Tampered 404 receipt must fail closed.
    bad_receipt = json.dumps({"http_status": 404, "sha256": "0" * 64, "byte_size": 1, "url": not_found_url}).encode(
        "utf-8"
    )
    bad_rel = "maintenance/catalogue/ie_opw/official/web/twater-404.receipt.json"
    (evidence / bad_rel).write_bytes(bad_receipt)
    bad_inputs = tuple(
        item.model_copy(update={"sha256": hashlib.sha256(bad_receipt).hexdigest(), "byte_size": len(bad_receipt)})
        if item.consumer_path == bad_rel
        else item
        for item in input_receipt.inputs
    )
    with pytest.raises(FatalContractError, match="disagrees with body identity"):
        read_catalogue_sources(
            evidence,
            selection_path=selection_rel,
            input_receipt=input_receipt.model_copy(update={"inputs": bad_inputs}),
        )
