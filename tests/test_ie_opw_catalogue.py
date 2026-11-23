"""Synthetic Ireland OPW (`ie_opw`) station catalogue, origin, and metadata checks."""

from __future__ import annotations

import io
import zipfile
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
from rivretrieve._internal.providers.ie_opw.generate_catalogue import (
    _check_complete_zip_bytes,
    catalogue_tables,
    is_excluded_station,
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
