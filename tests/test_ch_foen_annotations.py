"""Source-independent tests for ch_foen official source annotations (#816)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationDataSchema
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ch_foen.official_config import OfficialRoute, config
from rivretrieve._internal.providers.ch_foen.official_parse import parse
from rivretrieve._internal.providers.ch_foen.official_series import ARCHIVE_ROUTES, product_id, source_series
from rivretrieve._internal.source_annotations import CATALOG_SCHEMA, AnnotationScope
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _origin() -> SourceCallOrigin:
    return SourceCallOrigin(
        "https://data.bafu.admin.ch/api",
        {},
        200,
        datetime(2026, 1, 1, tzinfo=UTC),
        "application/json",
        UnknownOriginFact(),
        UnknownOriginFact(),
    )


def _archive_payload(
    route: str,
    records: list[dict[str, object]],
    *,
    station: str = "2018",
    parameter: str = "Q",
) -> Payload:
    return Payload(
        SourceCoordinates(OfficialRoute(route, parameter)),
        ((station, ProductId(product_id(route, parameter))),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 2)),
        ),
        json.dumps({"data": {"water": {"observations": {route: records}}}}).encode(),
        _origin(),
        (),
    )


def _recent_payload(records: list[dict[str, object]], *, station: str = "2018", unit: str = "l/s") -> Payload:
    definition = source_series(
        station,
        "data_live",
        "Q",
        None,
        units=(unit,),
        evidence="synthetic:station-unit",
        temporal_evidence="synthetic:time",
        origin="catalogue",
    )
    return Payload(
        SourceCoordinates(OfficialRoute("data_live", "Q")),
        ((station, ProductId("discharge_recent")),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 2)),
        ),
        json.dumps({"data": {"water": {"observations": {"data_live": records}}}}).encode(),
        _origin(),
        (),
        known_series=(definition,),
    )


def test_ch_foen_archive_and_recent_annotation_schemas() -> None:
    from rivretrieve._internal.providers.ch_foen.annotations import (
        CH_FOEN_ARCHIVE_SCHEMA,
        CH_FOEN_RECENT_SCHEMA,
    )

    assert CH_FOEN_ARCHIVE_SCHEMA.schema_id == "ch_foen.archive"
    assert CH_FOEN_ARCHIVE_SCHEMA.provider_id == "ch_foen"
    assert CH_FOEN_ARCHIVE_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [field.name for field in CH_FOEN_ARCHIVE_SCHEMA.fields] == ["releaseState"]
    assert [field.dtype for field in CH_FOEN_ARCHIVE_SCHEMA.fields] == ["String"]
    archive_field = CH_FOEN_ARCHIVE_SCHEMA.fields[0]
    assert archive_field.description
    assert archive_field.reference_url == "https://data.bafu.admin.ch/en/dataproduct-water-observations"

    assert CH_FOEN_RECENT_SCHEMA.schema_id == "ch_foen.recent"
    assert CH_FOEN_RECENT_SCHEMA.provider_id == "ch_foen"
    assert CH_FOEN_RECENT_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [field.name for field in CH_FOEN_RECENT_SCHEMA.fields] == ["releaseStatus"]
    assert [field.dtype for field in CH_FOEN_RECENT_SCHEMA.fields] == ["Int64"]
    recent_field = CH_FOEN_RECENT_SCHEMA.fields[0]
    assert recent_field.description
    assert recent_field.reference_url == "https://data.bafu.admin.ch/en/dataproduct-water-observations"


@pytest.mark.parametrize("route", ARCHIVE_ROUTES)
def test_all_archive_routes_emit_release_state_and_preserve_null_and_codes(route: str) -> None:
    codes = [None, "0", "1", "2", "3"]
    records = [
        {
            "station": {"no": "2018"},
            "parameterName": "Q",
            "tsName": "TestSeries",
            "unitSymbol": "m3/s",
            "timestamp": f"2025-01-01T0{idx}:00:00Z",
            "value": None if idx == 0 else float(idx),
            "releaseState": code,
        }
        for idx, code in enumerate(codes)
    ]
    parsed = parse(_archive_payload(route, records), config())
    assert set(parsed.annotations.observation_tables) == {"ch_foen.archive"}
    assert not parsed.annotations.series_tables
    table = parsed.annotations.observation_tables["ch_foen.archive"]
    assert table.row_count == len(codes)
    assert table.unmeasured_count == 0
    assert table.measurement_indices == tuple(range(len(codes)))
    assert table.rows["measured"].to_list() == [True] * len(codes)
    assert table.rows["releaseState"].to_list() == codes
    assert parsed.rows["value"].to_list() == [None, 1.0, 2.0, 3.0, 4.0]


def test_archive_multi_variant_and_multi_unit_annotations_stay_aligned() -> None:
    records = [
        {
            "station": {"no": "2018"},
            "parameterName": "Q",
            "tsName": "TagMittel",
            "unitSymbol": "m3/s",
            "timestamp": "2025-01-01T00:00:00Z",
            "value": 10.0,
            "releaseState": "3",
        },
        {
            "station": {"no": "2018"},
            "parameterName": "Q",
            "tsName": "TagMittel_01",
            "unitSymbol": "l/s",
            "timestamp": "2025-01-01T00:00:00Z",
            "value": None,
            "releaseState": None,
        },
        {
            "station": {"no": "2018"},
            "parameterName": "Q",
            "tsName": "TagMittel_01",
            "unitSymbol": "m3/s",
            "timestamp": "2025-01-01T01:00:00Z",
            "value": 11.0,
            "releaseState": "2",
        },
    ]
    parsed = parse(_archive_payload("data_1hour_mean", records), config())
    table = parsed.annotations.observation_tables["ch_foen.archive"]
    assert table.measurement_indices == tuple(range(parsed.rows.height))
    series_variants = {item.series_id: item.variant for item in parsed.series}
    paired = [
        (series_variants[row["series_id"]], row["time"], row["source_unit"], row["value"], ann["releaseState"])
        for row, ann in zip(
            parsed.rows.iter_rows(named=True),
            table.rows.iter_rows(named=True),
            strict=True,
        )
    ]
    assert set(paired) == {
        ("TagMittel", datetime(2025, 1, 1, 0, 0), "m3/s", 10.0, "3"),
        ("TagMittel_01", datetime(2025, 1, 1, 0, 0), "l/s", None, None),
        ("TagMittel_01", datetime(2025, 1, 1, 1, 0), "m3/s", 11.0, "2"),
    }


def test_recent_route_emits_release_status_int_preserving_zero_and_null() -> None:
    records = [
        {
            "stationNo": "2018",
            "parameterName": "Q",
            "timestamp": "2025-01-01T00:00:00Z",
            "value": 1200.0,
            "releaseStatus": 0,
        },
        {
            "stationNo": "2018",
            "parameterName": "Q",
            "timestamp": "2025-01-01T00:10:00Z",
            "value": None,
            "releaseStatus": None,
        },
    ]
    parsed = parse(_recent_payload(records), config())
    assert set(parsed.annotations.observation_tables) == {"ch_foen.recent"}
    assert not parsed.annotations.series_tables
    table = parsed.annotations.observation_tables["ch_foen.recent"]
    assert table.row_count == 2
    assert table.unmeasured_count == 0
    assert table.measurement_indices == (0, 1)
    assert table.rows["releaseStatus"].to_list() == [0, None]
    assert parsed.rows["value"].to_list() == [1200.0, None]


def test_unprojected_archive_payload_omits_annotation_table_instead_of_fabricating_nulls() -> None:
    records = [
        {
            "station": {"no": "2018"},
            "parameterName": "Q",
            "tsName": "TagMittel",
            "unitSymbol": "m3/s",
            "timestamp": "2025-01-01T00:00:00Z",
            "value": 10.0,
        }
    ]
    parsed = parse(_archive_payload("data_1day_mean", records), config())
    assert parsed.rows.height == 1
    assert parsed.annotations.is_empty


def test_mixed_present_and_missing_annotation_key_fails_boundedly() -> None:
    records = [
        {
            "station": {"no": "2018"},
            "parameterName": "Q",
            "tsName": "TagMittel",
            "unitSymbol": "m3/s",
            "timestamp": "2025-01-01T00:00:00Z",
            "value": 10.0,
            "releaseState": "3",
        },
        {
            "station": {"no": "2018"},
            "parameterName": "Q",
            "tsName": "TagMittel",
            "unitSymbol": "m3/s",
            "timestamp": "2025-01-02T00:00:00Z",
            "value": 11.0,
        },
    ]
    parsed = parse(_archive_payload("data_1day_mean", records), config())
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty
    assert len(parsed.outcomes) == 1
    assert parsed.outcomes[0].status is OutcomeStatus.FAILED
    assert "releaseState" in (parsed.outcomes[0].reason or "")


@pytest.mark.parametrize("bad_state", [3, True, ["3"]])
def test_invalid_archive_release_state_type_fails_boundedly(bad_state: object) -> None:
    records = [
        {
            "station": {"no": "2018"},
            "parameterName": "Q",
            "tsName": "TagMittel",
            "unitSymbol": "m3/s",
            "timestamp": "2025-01-01T00:00:00Z",
            "value": 10.0,
            "releaseState": bad_state,
        }
    ]
    parsed = parse(_archive_payload("data_1day_mean", records), config())
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty
    assert parsed.outcomes[0].status is OutcomeStatus.FAILED
    assert "releaseState" in (parsed.outcomes[0].reason or "")


@pytest.mark.parametrize("bad_status", ["0", True, 0.5, [0]])
def test_invalid_recent_release_status_type_fails_boundedly(bad_status: object) -> None:
    records = [
        {
            "stationNo": "2018",
            "parameterName": "Q",
            "timestamp": "2025-01-01T00:00:00Z",
            "value": 1200.0,
            "releaseStatus": bad_status,
        }
    ]
    parsed = parse(_recent_payload(records), config())
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty
    assert parsed.outcomes[0].status is OutcomeStatus.FAILED
    assert "releaseStatus" in (parsed.outcomes[0].reason or "")


def test_public_mixed_archive_and_recent_annotations_clipping_pick_utc_and_bundle(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    all_q = rr.find(provider="ch_foen", station="2018", quantity="discharge")
    series_df = rr.series(all_q)
    daily_id = series_df.filter((pl.col("product_id") == "discharge_1day_mean") & (pl.col("variant") == "TagMittel"))[
        "series_id"
    ].item()
    monthly_id = series_df.filter(
        (pl.col("product_id") == "discharge_1month_mean") & (pl.col("variant") == "MonatMittel")
    )["series_id"].item()
    recent_id = series_df.filter(pl.col("product_id") == "discharge_recent")["series_id"].item()
    selection = rr.pick(all_q, series_id=(daily_id, monthly_id, recent_id))

    class MixedTransport:
        def send(self, request):
            query = json.loads(request.body)["query"]
            if "data_live(" in query:
                body = {
                    "data": {
                        "water": {
                            "observations": {
                                "data_live": [
                                    {
                                        "stationNo": "2018",
                                        "parameterName": "Q",
                                        "timestamp": "2025-07-01T00:00:00Z",
                                        "value": 120.0,
                                        "releaseStatus": 0,
                                    },
                                    {
                                        "stationNo": "2018",
                                        "parameterName": "Q",
                                        "timestamp": "2025-07-01T00:10:00Z",
                                        "value": None,
                                        "releaseStatus": None,
                                    },
                                ]
                            }
                        }
                    }
                }
            elif "data_1day_mean(" in query:
                body = {
                    "data": {
                        "water": {
                            "observations": {
                                "data_1day_mean": [
                                    {
                                        "station": {"no": "2018"},
                                        "parameterName": "Q",
                                        "tsName": "TagMittel",
                                        "unitSymbol": "m3/s",
                                        "timestamp": "2025-06-30T23:00:00Z",
                                        "value": 95.0,
                                        "releaseState": "3",
                                    },
                                    {
                                        "station": {"no": "2018"},
                                        "parameterName": "Q",
                                        "tsName": "TagMittel",
                                        "unitSymbol": "m3/s",
                                        "timestamp": "2025-07-01T23:00:00Z",
                                        "value": None,
                                        "releaseState": None,
                                    },
                                ]
                            }
                        }
                    }
                }
            elif "data_1month_mean(" in query:
                body = {
                    "data": {
                        "water": {
                            "observations": {
                                "data_1month_mean": [
                                    {
                                        "station": {"no": "2018"},
                                        "parameterName": "Q",
                                        "tsName": "MonatMittel",
                                        "unitSymbol": "m3/s",
                                        "timestamp": "2025-06-30T23:00:00Z",
                                        "value": 110.0,
                                        "releaseState": "2",
                                    },
                                    {
                                        "station": {"no": "2018"},
                                        "parameterName": "Q",
                                        "tsName": "MonatMittel",
                                        "unitSymbol": "m3/s",
                                        "timestamp": "2025-07-31T23:00:00Z",
                                        "value": 130.0,
                                        "releaseState": "3",
                                    },
                                ]
                            }
                        }
                    }
                }
            else:
                raise AssertionError(f"Unexpected route query: {query}")
            return TransportResponse(
                json.dumps(body).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    monkeypatch.setattr(discovery, "HttpClient", MixedTransport)
    result = rr.fetch(selection, start="2025-07-01", end="2025-07-31", cache="bypass", on_issue="ignore")

    # Default observation schemas, series identities, and issue policy stay unchanged.
    canonical_cols = tuple(ObservationDataSchema.polars_schema)
    assert tuple(result.data.columns) == canonical_cols
    assert tuple(result.to_polars().columns) == canonical_cols
    assert list(result.to_pandas().columns) == list(canonical_cols)
    assert [(item.code, item.severity) for item in result.issues] == [("provenance.citation_not_established", "info")]
    assert rr.series(result)["variant"].to_list() == rr.series(selection)["variant"].to_list()

    catalog = rr.annotations(result)
    assert catalog.schema == pl.Schema(CATALOG_SCHEMA)
    assert catalog.select("scope", "schema", "name", "dtype", "row_count", "unmeasured_count").sort(
        "schema"
    ).rows() == [
        ("observation", "ch_foen.archive", "releaseState", "String", 3, 0),
        ("observation", "ch_foen.recent", "releaseStatus", "Int64", 2, 0),
    ]
    assert catalog["description"].to_list() == [item for item in catalog["description"].to_list() if item]
    assert set(catalog["reference_url"].to_list()) == {"https://data.bafu.admin.ch/en/dataproduct-water-observations"}

    # Separate schema access isolates route applicability without cross-route null padding.
    archive_ann = rr.annotations(result, schema="ch_foen.archive").sort("product_id", "time")
    assert set(archive_ann["product_id"].to_list()) == {"discharge_1day_mean", "discharge_1month_mean"}
    assert "releaseStatus" not in archive_ann.columns
    assert archive_ann["releaseState"].to_list() == ["3", None, "2"]

    recent_ann = rr.annotations(result, schema="ch_foen.recent").sort("time")
    assert set(recent_ann["product_id"].to_list()) == {"discharge_recent"}
    assert "releaseState" not in recent_ann.columns
    assert recent_ann["releaseStatus"].to_list() == [0, None]

    # Explicit projection adds requested columns and refuses unknown names.
    proj_all = result.to_polars(annotations=True).sort("product_id", "time")
    assert set(proj_all.columns) == {*canonical_cols, "releaseState", "releaseStatus"}
    assert proj_all.filter(pl.col("product_id") == "discharge_1day_mean").select("value", "releaseState").rows() == [
        (95.0, "3"),
        (None, None),
    ]
    assert proj_all.filter(pl.col("product_id") == "discharge_recent").select("value", "releaseStatus").rows() == [
        (120.0, 0),
        (None, None),
    ]
    assert list(result.to_polars(annotations="releaseState").columns) == [*canonical_cols, "releaseState"]
    pd_df = result.to_pandas(annotations=["releaseState", "releaseStatus"])
    assert isinstance(pd_df, pd.DataFrame)
    assert set(pd_df.columns) == {*canonical_cols, "releaseState", "releaseStatus"}
    with pytest.raises(ValueError):
        result.to_polars(annotations="unknown_annotation_field")

    # Pick, UTC conversion, and bundle round-trip preserve annotations cleanly.
    picked_recent = rr.pick(result, series_id=recent_id, on_issue="ignore")
    assert rr.annotations(picked_recent)["schema"].to_list() == ["ch_foen.recent"]
    pl_testing.assert_frame_equal(rr.annotations(picked_recent, schema="ch_foen.recent").sort("time"), recent_ann)

    picked_monthly = rr.pick(result, variant="MonatMittel", on_issue="ignore")
    assert rr.annotations(picked_monthly, schema="ch_foen.archive")["releaseState"].to_list() == ["2"]

    utc_result = rr.to_utc(result)
    pl_testing.assert_frame_equal(
        utc_result.to_polars(annotations=True).sort("product_id", "time"),
        proj_all,
    )

    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(restored.data, result.data)
    pl_testing.assert_frame_equal(rr.annotations(restored), rr.annotations(result))
    pl_testing.assert_frame_equal(
        rr.annotations(restored, schema="ch_foen.archive"),
        rr.annotations(result, schema="ch_foen.archive"),
    )
    pl_testing.assert_frame_equal(
        rr.annotations(restored, schema="ch_foen.recent"),
        rr.annotations(result, schema="ch_foen.recent"),
    )
    pl_testing.assert_frame_equal(restored.to_polars(annotations=True), result.to_polars(annotations=True))


def test_public_cache_reuse_status_only_refresh_and_failed_refresh_preserve_annotations(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    all_q = rr.find(provider="ch_foen", station="2018", quantity="discharge")
    series_df = rr.series(all_q)
    archive_id = series_df.filter((pl.col("product_id") == "discharge_1day_mean") & (pl.col("variant") == "TagMittel"))[
        "series_id"
    ].item()
    recent_id = series_df.filter(pl.col("product_id") == "discharge_recent")["series_id"].item()
    selection = rr.pick(all_q, series_id=(archive_id, recent_id))

    state: dict[str, object] = {
        "releaseState": None,
        "releaseStatus": 0,
        "fail": False,
        "forbid": False,
        "calls": 0,
    }

    class MutableTransport:
        def send(self, request):
            assert not state["forbid"], "Offline cache reuse must not access transport"
            state["calls"] = int(state["calls"]) + 1
            if state["fail"]:
                document = {"data": None, "errors": [{"message": "temporary outage"}]}
            else:
                query = json.loads(request.body)["query"]
                if "data_live(" in query:
                    document = {
                        "data": {
                            "water": {
                                "observations": {
                                    "data_live": [
                                        {
                                            "stationNo": "2018",
                                            "parameterName": "Q",
                                            "timestamp": "2025-07-01T12:00:00Z",
                                            "value": 100.0,
                                            "releaseStatus": state["releaseStatus"],
                                        }
                                    ]
                                }
                            }
                        }
                    }
                else:
                    document = {
                        "data": {
                            "water": {
                                "observations": {
                                    "data_1day_mean": [
                                        {
                                            "station": {"no": "2018"},
                                            "parameterName": "Q",
                                            "tsName": "TagMittel",
                                            "unitSymbol": "m3/s",
                                            "timestamp": "2025-06-30T23:00:00Z",
                                            "value": 99.5,
                                            "releaseState": state["releaseState"],
                                        }
                                    ]
                                }
                            }
                        }
                    }
            return TransportResponse(
                json.dumps(document).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    monkeypatch.setattr(discovery, "HttpClient", MutableTransport)

    initial = rr.fetch(selection, start="2025-07-01", end="2025-07-01", cache="refresh", on_issue="ignore")
    assert initial.to_polars(annotations=True).filter(pl.col("product_id") == "discharge_1day_mean")[
        "releaseState"
    ].to_list() == [None]
    assert initial.to_polars(annotations=True).filter(pl.col("product_id") == "discharge_recent")[
        "releaseStatus"
    ].to_list() == [0]

    archive_only = rr.pick(all_q, series_id=archive_id)

    # Offline reuse serves stored archive annotations without contacting the source.
    state["forbid"] = True
    calls_before_reuse = state["calls"]
    reused = rr.fetch(archive_only, start="2025-07-01", end="2025-07-01", cache="reuse", on_issue="ignore")
    assert state["calls"] == calls_before_reuse
    assert reused.to_polars(annotations=True)["releaseState"].to_list() == [None]

    # Status-only refresh replaces releaseState and releaseStatus even with identical numeric values,
    # including updating back to explicit null.
    state["forbid"] = False
    state["releaseState"] = "3"
    state["releaseStatus"] = 1
    refreshed = rr.fetch(selection, start="2025-07-01", end="2025-07-01", cache="refresh", on_issue="ignore")
    pl_testing.assert_frame_equal(refreshed.data.sort("product_id", "time"), initial.data.sort("product_id", "time"))
    assert refreshed.to_polars(annotations=True).filter(pl.col("product_id") == "discharge_1day_mean")[
        "releaseState"
    ].to_list() == ["3"]
    assert refreshed.to_polars(annotations=True).filter(pl.col("product_id") == "discharge_recent")[
        "releaseStatus"
    ].to_list() == [1]

    state["releaseStatus"] = None
    refreshed_null = rr.fetch(selection, start="2025-07-01", end="2025-07-01", cache="refresh", on_issue="ignore")
    assert refreshed_null.to_polars(annotations=True).filter(pl.col("product_id") == "discharge_recent")[
        "releaseStatus"
    ].to_list() == [None]

    # Subsequent offline archive reuse reflects replaced annotations without contacting transport.
    state["forbid"] = True
    reused_updated = rr.fetch(archive_only, start="2025-07-01", end="2025-07-01", cache="reuse", on_issue="ignore")
    assert reused_updated.to_polars(annotations=True)["releaseState"].to_list() == ["3"]

    # Failed refresh preserves held archive and recent observations and annotations alongside failure outcomes.
    state["forbid"] = False
    state["fail"] = True
    failed = rr.fetch(selection, start="2025-07-01", end="2025-07-01", cache="refresh", on_issue="ignore")
    assert sum(item.status is OutcomeStatus.FAILED for item in failed.outcomes) == 2
    pl_testing.assert_frame_equal(
        failed.to_polars(annotations=True).sort("product_id", "time"),
        refreshed_null.to_polars(annotations=True).sort("product_id", "time"),
    )


def test_public_calendar_clipping_and_sibling_isolation_preserve_annotations(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    all_q = rr.find(provider="ch_foen", station="2018", quantity="discharge")
    series_df = rr.series(all_q)
    monthly_id = series_df.filter(
        (pl.col("product_id") == "discharge_1month_mean") & (pl.col("variant") == "MonatMittel")
    )["series_id"].item()
    recent_id = series_df.filter(pl.col("product_id") == "discharge_recent")["series_id"].item()
    selection = rr.pick(all_q, series_id=(monthly_id, recent_id))

    class PartialMalformedTransport:
        def send(self, request):
            query = json.loads(request.body)["query"]
            if "data_1month_mean(" in query:
                body = {
                    "data": {
                        "water": {
                            "observations": {
                                "data_1month_mean": [
                                    {
                                        "station": {"no": "2018"},
                                        "parameterName": "Q",
                                        "tsName": "MonatMittel",
                                        "unitSymbol": "m3/s",
                                        "timestamp": "2025-06-30T23:00:00Z",
                                        "value": 100.0,
                                        "releaseState": "2",
                                    },
                                    {
                                        "station": {"no": "2018"},
                                        "parameterName": "Q",
                                        "tsName": "MonatMittel",
                                        "unitSymbol": "m3/s",
                                        "timestamp": "2025-07-31T23:00:00Z",
                                        "value": 110.0,
                                        "releaseState": "3",
                                    },
                                ]
                            }
                        }
                    }
                }
            else:
                body = {
                    "data": {
                        "water": {
                            "observations": {
                                "data_live": [
                                    {
                                        "stationNo": "2018",
                                        "parameterName": "Q",
                                        "timestamp": "2025-07-01T00:00:00Z",
                                        "value": 90.0,
                                        "releaseStatus": "bad-string",
                                    }
                                ]
                            }
                        }
                    }
                }
            return TransportResponse(
                json.dumps(body).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    monkeypatch.setattr(discovery, "HttpClient", PartialMalformedTransport)
    whole = rr.fetch(selection, start="2025-07-01", end="2025-08-31", cache="refresh", on_issue="ignore")
    assert whole.data["product_id"].unique().to_list() == ["discharge_1month_mean"]
    assert whole.to_polars(annotations=True).sort("time")["releaseState"].to_list() == ["2", "3"]
    assert any(
        item.status is OutcomeStatus.FAILED and "releaseStatus" in (item.reason or "")
        for item in whole.outcomes
        if item.product_id == "discharge_recent"
    )

    # Fixed UTC+1 calendar clipping keeps July's releaseState ("2") and August's ("3") separated.
    monthly_only = rr.pick(all_q, series_id=monthly_id)
    july = rr.fetch(monthly_only, start="2025-07-01", end="2025-07-31", cache="reuse", on_issue="ignore")
    august = rr.fetch(monthly_only, start="2025-08-01", end="2025-08-31", cache="reuse", on_issue="ignore")
    assert july.to_polars(annotations=True).select("time", "value", "releaseState").rows() == [
        (datetime(2025, 6, 30, 23), 100.0, "2")
    ]
    assert august.to_polars(annotations=True).select("time", "value", "releaseState").rows() == [
        (datetime(2025, 7, 31, 23), 110.0, "3")
    ]
