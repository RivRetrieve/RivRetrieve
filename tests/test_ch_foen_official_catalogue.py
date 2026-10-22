"""Synthetic official API catalogue inputs, independent of retained source bodies."""

from datetime import UTC, datetime

import polars as pl
import pytest

from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ch_foen.generate_catalogue import station_native_table


def test_station_snapshot_preserves_source_identity_unknown_geometry_and_status():
    payload = {
        "data": {
            "water": {
                "observations": {
                    "stations": [
                        {
                            "no": "0085",
                            "name": "",
                            "status": "withdrawn",
                            "latitude": None,
                            "longitude": None,
                            "elevation": None,
                            "coverageFrom": "1900-01-01",
                        },
                        {"no": "1234", "name": "A station", "status": "active", "latitude": 46.0, "longitude": 7.0},
                    ]
                }
            }
        }
    }
    result = station_native_table(payload, retrieved_at=RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC))).data
    assert result["no"].to_list() == ["0085", "1234"]
    assert result["latitude"].to_list() == [None, 46.0]
    assert result["longitude"].to_list() == [None, 7.0]
    assert result["name"].to_list() == ["", "A station"]
    assert result["status"].to_list() == ["withdrawn", "active"]
    assert result.schema["elevation"] == pl.Float64
    assert result["coverageFrom"].to_list() == ["1900-01-01", None]


@pytest.mark.parametrize("numbers", [[85], ["0085", "0085"], [""]])
def test_station_snapshot_rejects_nonstring_or_duplicate_numbers(numbers):
    payload = {"data": {"water": {"observations": {"stations": [{"no": no} for no in numbers]}}}}
    with pytest.raises(FatalContractError, match="station number"):
        station_native_table(payload, retrieved_at=RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)))


def test_observed_associations_keep_null_only_variants_and_separate_routes():
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import archive_associations

    rows = [
        {
            "station": {"no": "0085", "id": "embedded-1"},
            "parameterName": "Discharge",
            "tsName": name,
            "unitName": "Cubic metres per second",
            "unitSymbol": "m³/s",
            "timestamp": "2026-01-01T00:00:00Z",
            "value": None,
        }
        for name in ("Variant", "Variant.1", "Variant")
    ]
    payload = {"data": {"water": {"observations": {"archive_route": rows}}}}
    associations = archive_associations(payload, route="archive_route", station_numbers={"0085"})
    assert associations.select("station_no", "route", "parameterName", "tsName", "unitSymbol").rows() == [
        ("0085", "archive_route", "Discharge", "Variant", "m³/s"),
        ("0085", "archive_route", "Discharge", "Variant.1", "m³/s"),
    ]
    assert associations["station_id"].to_list() == ["embedded-1", "embedded-1"]
    with pytest.raises(FatalContractError, match="station snapshot"):
        archive_associations(payload, route="archive_route", station_numbers={"85"})


def test_empty_archive_sample_does_not_create_negative_associations():
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import archive_associations

    payload = {"data": {"water": {"observations": {"archive_route": []}}}}
    assert archive_associations(payload, route="archive_route", station_numbers={"0085"}).is_empty()
    payload["errors"] = [{"message": "Source query failed"}]
    with pytest.raises(FatalContractError, match="GraphQL errors"):
        archive_associations(payload, route="archive_route", station_numbers={"0085"})


def test_descriptions_scope_variants_and_unit_segments_without_temporal_inference():
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import ASSOCIATION_SCHEMA, describe_associations

    associations = pl.DataFrame(
        [
            {
                "station_no": "0085",
                "station_id": "embedded",
                "route": "data_1day_mean",
                "parameterName": "Q",
                "tsName": name,
                "unitName": "source unit",
                "unitSymbol": unit,
            }
            for name, unit in [("Unresolved", "m³/s"), ("Unresolved", "l/s"), ("Unresolved.1", "m³/s")]
        ],
        schema=ASSOCIATION_SCHEMA,
    )
    result = describe_associations(associations, evidence="synthetic:observations")
    assert len(result.descriptions) == 2
    first, variant = result.descriptions
    assert first.station_id == variant.station_id == "0085"
    assert first.product_id == "discharge_1day_mean"
    assert first.identity_key == ("data_1day_mean", "Q", "Unresolved")
    assert variant.identity_key == ("data_1day_mean", "Q", "Unresolved.1")
    assert {fact.source_unit.value for fact in first.facts} == {"m³/s", "l/s"}
    assert all(fact.frequency.value is None and fact.temporal_support.value is None for fact in first.facts)
    assert all(fact.quantity.value == "discharge" for fact in first.facts)


def test_catalogue_tables_record_only_observed_pairs_without_sample_record_bounds():
    from datetime import date

    from rivretrieve._internal.providers.ch_foen.generate_catalogue import ASSOCIATION_SCHEMA, catalogue_tables

    native = station_native_table(
        {
            "data": {
                "water": {
                    "observations": {
                        "stations": [
                            {"no": "0085", "latitude": None, "longitude": None},
                            {"no": "1234", "latitude": 46.0, "longitude": 7.0},
                        ]
                    }
                }
            }
        },
        retrieved_at=RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    associations = pl.DataFrame(
        [
            {
                "station_no": "0085",
                "station_id": "embedded",
                "route": "data_1day_mean",
                "parameterName": "Q",
                "tsName": "Unresolved",
                "unitName": "source unit",
                "unitSymbol": "m³/s",
            }
        ],
        schema=ASSOCIATION_SCHEMA,
    )
    products, stations, pairs = catalogue_tables(native, associations, checked_on=date(2026, 1, 2))
    assert stations["station_id"].to_list() == ["0085", "1234"]
    assert stations["crs"].to_list() == ["EPSG:4326", "EPSG:4326"]
    assert pairs.filter(pl.col("availability") == "available").select(
        "station_id", "product_id", "availability"
    ).rows() == [("0085", "discharge_1day_mean", "available")]
    assert pairs["published_record_start_date"].null_count() == pairs.height
    assert pairs["published_record_end_date"].null_count() == pairs.height
    assert set(products["frequency"]) == {"unknown"}
    assert set(products["statistic"]) == {"unknown"}
    assert products.filter(pl.col("product_id") == "discharge_1year_max")["native_id"].item() == "data_1year_max:Q"


def test_public_discovery_keeps_unknown_route_facts_and_unobserved_intent(monkeypatch):
    from datetime import date

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import (
        ASSOCIATION_SCHEMA,
        catalogue_tables,
        describe_associations,
    )
    from rivretrieve._internal.registry import ProviderRegistry
    from rivretrieve._internal.source_series import InventoryCompleteness, RestrictionKind

    native = station_native_table(
        {
            "data": {
                "water": {
                    "observations": {
                        "stations": [
                            {"no": "0085", "latitude": None, "longitude": None},
                            {"no": "1234", "latitude": 46.0, "longitude": 7.0},
                        ]
                    }
                }
            }
        },
        retrieved_at=RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    associations = pl.DataFrame(
        [
            {
                "station_no": "0085",
                "station_id": "embedded",
                "route": "data_1day_mean",
                "parameterName": "Q",
                "tsName": "Unresolved",
                "unitName": "source unit",
                "unitSymbol": "m³/s",
            }
        ],
        schema=ASSOCIATION_SCHEMA,
    )
    products, stations, pairs = catalogue_tables(native, associations, checked_on=date(2026, 1, 2))
    artifact = PackagedCatalogArtifact(
        {
            "provider_id": "ch_foen",
            "name": "Synthetic",
            "live_stations": False,
            "live_products": False,
            "live_station_products": False,
            "bulk_observations": "none",
            "catalogue_version": "2026-01-02",
            "license": None,
            "citation": None,
        },
        products,
        stations,
        pairs,
        source_descriptions=describe_associations(associations, evidence="synthetic:observations"),
    )
    registry = ProviderRegistry()
    registry.register("ch_foen", artifact)
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)
    broad = rr.find(provider="ch_foen", station="0085", quantity="discharge", on_issue="ignore")
    assert len(broad.series) == 1
    assert not rr.find(provider="ch_foen", station="0085", frequency="daily", on_issue="ignore").series
    assert not rr.find(provider="ch_foen", station="0085", statistic="mean", on_issue="ignore").series
    unresolved = rr.find(provider="ch_foen", station="1234", on_issue="ignore")
    assert not unresolved.known_series
    assert unresolved.scope.restriction is RestrictionKind.ALL
    assert unresolved.empty_reason.code == "unresolved_inventory"
    assert len(unresolved.inventories) == len(products)
    assert all(
        item.completeness is InventoryCompleteness.INCOMPLETE and not item.members for item in unresolved.inventories
    )


@pytest.mark.parametrize("unit,route", [("m ü.M.", "data_1day_mean"), ("m a.s.l.", "data_live")])
def test_stage_reference_labels_allow_discovery_without_inventing_a_datum(monkeypatch, unit, route):
    from datetime import date

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import (
        ASSOCIATION_SCHEMA,
        catalogue_tables,
        describe_associations,
    )
    from rivretrieve._internal.registry import ProviderRegistry
    from rivretrieve._internal.source_series import EvidenceState, admission

    native = station_native_table(
        {"data": {"water": {"observations": {"stations": [{"no": "0085"}]}}}},
        retrieved_at=RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    associations = pl.DataFrame(
        [
            {
                "station_no": "0085",
                "station_id": None,
                "route": route,
                "parameterName": "W",
                "tsName": "Level",
                "unitName": unit,
                "unitSymbol": unit,
            },
        ],
        schema=ASSOCIATION_SCHEMA,
    )
    products, stations, pairs = catalogue_tables(native, associations, checked_on=date(2026, 1, 2))
    artifact = PackagedCatalogArtifact(
        {
            "provider_id": "ch_foen",
            "name": "Synthetic",
            "live_stations": False,
            "live_products": False,
            "live_station_products": False,
            "bulk_observations": "none",
            "catalogue_version": "2026-01-02",
            "license": None,
            "citation": None,
        },
        products,
        stations,
        pairs,
        source_descriptions=describe_associations(associations, evidence="synthetic:published-label"),
    )
    registry = ProviderRegistry()
    registry.register("ch_foen", artifact)
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)
    selected = rr.find(provider="ch_foen", station="0085", quantity="stage", on_issue="ignore")
    assert len(selected.series) == 1
    fact = selected.series[0].facts[0]
    assert fact.source_unit.value == unit
    assert fact.normalized_unit == "m"
    assert admission(fact).factor == 1.0
    assert fact.vertical_reference.value == "above_sea_level"
    assert fact.vertical_reference.evidence == ("synthetic:published-label",)
    assert fact.vertical_datum.state is EvidenceState.NOT_ESTABLISHED
    assert len(rr.find(provider="ch_foen", quantity="stage", vertical_reference="above_sea_level").series) == 1
    assert not rr.find(provider="ch_foen", quantity="stage", vertical_datum="LN02").series
    assert fact.frequency.value is None and fact.temporal_support.value is None


def test_recent_associations_bind_only_station_page_units_without_archive_fallback():
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import recent_associations

    payload = {
        "data": {
            "water": {
                "observations": {
                    "data_live": [
                        {"stationNo": "0085", "parameterName": "Q", "timestamp": "2026-01-01T00:00:00Z", "value": None},
                        {"stationNo": "1234", "parameterName": "Q", "timestamp": "2026-01-01T00:00:00Z", "value": 2.0},
                    ]
                }
            }
        }
    }
    result = recent_associations(
        payload,
        station_numbers={"0085", "1234"},
        station_units={"0085": {"Discharge": "l/s"}, "1234": {"Discharge": "m³/s"}},
    )
    assert result.select("station_no", "route", "parameterName", "unitSymbol").rows() == [
        ("0085", "data_live", "Q", "l/s"),
        ("1234", "data_live", "Q", "m³/s"),
    ]
    unresolved = recent_associations(payload, station_numbers={"0085", "1234"}, station_units={})
    assert unresolved["unitSymbol"].to_list() == [None, None]


@pytest.mark.parametrize("field,value", [("name", 123), ("latitude", True), ("coverageFrom", 1900)])
def test_station_metadata_does_not_coerce_source_scalar_types(field, value):
    payload = {"data": {"water": {"observations": {"stations": [{"no": "0085", field: value}]}}}}
    with pytest.raises(FatalContractError, match="scalar types"):
        station_native_table(payload, retrieved_at=RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)))


def test_recent_temperature_uses_published_temperature_header():
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import recent_associations

    payload = {
        "data": {
            "water": {"observations": {"data_live": [{"stationNo": "0085", "parameterName": "WT", "value": None}]}}
        }
    }
    result = recent_associations(payload, station_numbers={"0085"}, station_units={"0085": {"Temperature": "°C"}})
    assert result["unitSymbol"].item() == "°C"


def test_original_reader_requires_selected_bytes_before_json_parsing(tmp_path):
    import hashlib

    from rivretrieve._internal.acquisition_provenance import (
        RecordingReference,
        RetainedInputReceipt,
        RetainedInputReference,
    )
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import read_original

    body = b'{"data": {}}'
    path = tmp_path / "stations.body"
    path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    reference = RecordingReference(
        recording_id="station-snapshot",
        repository_path="stations.body",
        source_url="https://data.bafu.admin.ch/api",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
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
                consumer_path="stations.body",
                archive_repository="https://github.com/RivRetrieve/verification-evidence",
                archive_revision="b" * 40,
                collection_id="synthetic",
                manifest_sha256="c" * 64,
                artifact_id="stations",
                sha256=digest,
                byte_size=len(body),
                role="publisher_original",
            ),
        ),
    )
    assert read_original(tmp_path, reference, input_receipt=receipt) == body
    path.write_bytes(b"changed")
    with pytest.raises(FatalContractError, match="archive identity"):
        read_original(tmp_path, reference, input_receipt=receipt)
    with pytest.raises(FatalContractError, match="selected"):
        read_original(tmp_path, reference, input_receipt=receipt.model_copy(update={"inputs": ()}))


def test_station_origins_accept_source_null_geometry():
    from datetime import date

    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import ASSOCIATION_SCHEMA, catalogue_tables
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    native = station_native_table(
        {"data": {"water": {"observations": {"stations": [{"no": "0085", "latitude": None, "longitude": None}]}}}},
        retrieved_at=RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    _, stations, _ = catalogue_tables(native, pl.DataFrame(schema=ASSOCIATION_SCHEMA), checked_on=date(2026, 1, 1))
    enforce_catalogue_origins(ProviderId("ch_foen"), STATION_CATALOGUE_ORIGINS, native, stations)


def test_catalogue_build_enforces_origins_before_publication():
    from datetime import date

    from rivretrieve._internal.catalogue_origins import Field, NativeColumn
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import ASSOCIATION_SCHEMA, build_catalogue
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    native = station_native_table(
        {"data": {"water": {"observations": {"stations": [{"no": "0085", "latitude": None, "longitude": None}]}}}},
        retrieved_at=RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    wrong = {**STATION_CATALOGUE_ORIGINS, "station_id": Field(NativeColumn("name"))}
    with pytest.raises(FatalContractError, match="station_id"):
        build_catalogue(
            native,
            wrong,
            associations=pl.DataFrame(schema=ASSOCIATION_SCHEMA),
            checked_on=date(2026, 1, 1),
            provenance=None,
        )


@pytest.mark.governing(
    "maintenance/catalogue/ch_foen/official",
    "maintenance/catalogue/ch_foen/official/selection.json",
)
def test_retained_station_snapshot_preserves_source_fields(retained_evidence_root, catalogue_input_receipt):
    """Compare native station fields directly with the selected original response."""
    import json

    from rivretrieve._internal.acquisition_provenance import RecordingReference
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import read_original

    declaration_path = "maintenance/catalogue/ch_foen/official/selection.json"
    assert declaration_path in {item.consumer_path for item in catalogue_input_receipt.declaration_inputs}
    selection = json.loads((retained_evidence_root / declaration_path).read_bytes())
    station_captures = [capture for capture in selection["captures"] if capture["kind"] == "stations"]
    assert len(station_captures) == 1
    capture = station_captures[0]
    reference = RecordingReference.model_validate(capture["recording"])
    assert reference.repository_path == capture["body"]
    body = read_original(retained_evidence_root, reference, input_receipt=catalogue_input_receipt)
    payload = json.loads(body)
    native = station_native_table(payload, retrieved_at=RetrievedAt(reference.retrieved_at))
    rows = payload["data"]["water"]["observations"]["stations"]
    assert native.data["no"].to_list() == sorted(row["no"] for row in rows)
    assert native.data.height == len(rows)
    for row in rows:
        actual = native.data.filter(pl.col("no") == row["no"]).row(0, named=True)
        for field in ("name", "latitude", "longitude", "status", "coverageFrom", "coverageTo"):
            assert actual[field] == row.get(field)
    assert (retained_evidence_root / reference.repository_path).read_bytes() == body


def test_source_selection_requires_verified_authored_declaration(tmp_path):
    from rivretrieve._internal.acquisition_provenance import RetainedInputReceipt
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import read_catalogue_sources

    receipt = RetainedInputReceipt(
        schema_version=3,
        code_revision="a" * 40,
        declaration_revision="a" * 40,
        archive_code_revision="b" * 40,
        inputs=(),
    )
    with pytest.raises(FatalContractError, match="selected authored declaration"):
        read_catalogue_sources(tmp_path, selection_path="selection.json", input_receipt=receipt)
