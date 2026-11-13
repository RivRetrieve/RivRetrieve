"""Source-independent tests for USGS NWIS modern OGC annotations (#813)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.observations import ObservationDataSchema
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis.config import config
from rivretrieve._internal.source_annotations import CATALOG_SCHEMA
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportResponse
from tests.test_usgs_modern_parse import decode, feature

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_DAILY_PRODUCTS = ("discharge_daily_mean", "stage_daily_mean", "stage_daily_max", "stage_daily_min")
_CONTINUOUS_PRODUCTS = ("discharge_instantaneous", "stage_instantaneous")


@pytest.mark.parametrize("product", _DAILY_PRODUCTS)
def test_daily_routes_emit_usgs_nwis_daily_schema(product: str) -> None:
    parsed = decode(
        [
            {
                **feature(product, qualifier="Ice", approval_status="Approved", last_modified="2024-02-01T00:00:00Z"),
                "id": "volatile-feature-id-1",
            }
        ],
        product,
    )
    assert parsed.rows.height == 1
    assert set(parsed.annotations.observation_tables) == {"usgs_nwis.daily"}
    assert not parsed.annotations.series_tables
    table = parsed.annotations.observation_tables["usgs_nwis.daily"]
    assert table.schema.provider_id == "usgs_nwis"
    assert [field.name for field in table.schema.fields] == ["approval_status", "qualifier"]
    assert [field.dtype for field in table.schema.fields] == ["String", "List(String)"]
    for field in table.schema.fields:
        assert field.description and "meaining" not in field.description.lower()
        assert field.reference_url.startswith("https://api.waterdata.usgs.gov/")
    assert "id" not in table.rows.columns
    assert "last_modified" not in table.rows.columns
    assert table.rows["approval_status"].to_list() == ["Approved"]
    assert table.rows["qualifier"].to_list() == [["Ice"]]
    assert table.rows["measured"].to_list() == [True]
    assert table.measurement_indices == (0,)


@pytest.mark.parametrize("product", _CONTINUOUS_PRODUCTS)
def test_continuous_routes_emit_usgs_nwis_continuous_schema(product: str) -> None:
    parsed = decode(
        [
            {
                **feature(
                    product,
                    qualifier=["P", "e"],
                    approval_status="Provisional",
                    method_category="Sensor",
                    last_modified="2024-02-01T00:00:00Z",
                ),
                "id": "volatile-feature-id-2",
            }
        ],
        product,
    )
    assert parsed.rows.height == 1
    assert set(parsed.annotations.observation_tables) == {"usgs_nwis.continuous"}
    table = parsed.annotations.observation_tables["usgs_nwis.continuous"]
    assert table.schema.provider_id == "usgs_nwis"
    assert [field.name for field in table.schema.fields] == ["approval_status", "qualifier", "method_category"]
    assert [field.dtype for field in table.schema.fields] == ["String", "List(String)", "String"]
    for field in table.schema.fields:
        assert field.description and "meaining" not in field.description.lower()
        assert field.reference_url.startswith("https://api.waterdata.usgs.gov/")
    assert "id" not in table.rows.columns
    assert "last_modified" not in table.rows.columns
    assert table.rows["approval_status"].to_list() == ["Provisional"]
    assert table.rows["qualifier"].to_list() == [["P", "e"]]
    assert table.rows["method_category"].to_list() == ["Sensor"]
    assert table.measurement_indices == (0,)


def test_shared_fields_identical_across_daily_and_continuous_schemas() -> None:
    daily = decode([feature("discharge_daily_mean")], "discharge_daily_mean").annotations.observation_tables[
        "usgs_nwis.daily"
    ]
    cont = decode(
        [feature("discharge_instantaneous", method_category=None)], "discharge_instantaneous"
    ).annotations.observation_tables["usgs_nwis.continuous"]
    daily_fields = {f.name: f for f in daily.schema.fields}
    cont_fields = {f.name: f for f in cont.schema.fields}
    assert daily_fields["approval_status"] == cont_fields["approval_status"]
    assert daily_fields["qualifier"] == cont_fields["qualifier"]


@pytest.mark.parametrize(
    ("raw_qualifier", "expected"),
    [
        (None, None),
        ("Ice", ["Ice"]),
        (["P", "e"], ["P", "e"]),
        ([], []),
    ],
)
def test_qualifier_normalization_shapes(raw_qualifier: object, expected: list[str] | None) -> None:
    parsed = decode([feature(qualifier=raw_qualifier)])
    table = parsed.annotations.observation_tables["usgs_nwis.daily"]
    assert table.rows["qualifier"].to_list() == [expected]


def test_null_value_feature_preserves_measured_annotation_and_stable_identity() -> None:
    f_prov = feature(value=None, qualifier=["DISCONTINUED"], approval_status="Provisional", time="2024-01-01")
    f_prov["id"] = "rev-1"
    f_prov["properties"]["last_modified"] = "2024-01-02T00:00:00Z"

    f_appr = feature(value=None, qualifier=None, approval_status="Approved", time="2024-01-01")
    f_appr["id"] = "rev-2"
    f_appr["properties"]["last_modified"] = "2024-06-02T00:00:00Z"

    parsed_prov = decode([f_prov])
    parsed_appr = decode([f_appr])
    pl_testing.assert_frame_equal(parsed_prov.rows, parsed_appr.rows)
    assert parsed_prov.rows["value"].to_list() == [None]
    assert parsed_prov.series == parsed_appr.series
    table_prov = parsed_prov.annotations.observation_tables["usgs_nwis.daily"]
    assert table_prov.rows["measured"].to_list() == [True]
    assert table_prov.measurement_indices == (0,)
    assert table_prov.rows["qualifier"].to_list() == [["DISCONTINUED"]]
    assert table_prov.rows["approval_status"].to_list() == ["Provisional"]


def test_exact_duplicate_feature_deduplicates_cleanly() -> None:
    item = feature(approval_status="Approved", qualifier="Ice")
    single = decode([item])
    dup = decode([item, {**item, "id": "different-record-revision"}])
    pl_testing.assert_frame_equal(dup.rows, single.rows)
    pl_testing.assert_frame_equal(
        dup.annotations.observation_tables["usgs_nwis.daily"].rows,
        single.annotations.observation_tables["usgs_nwis.daily"].rows,
    )
    assert not dup.issues


@pytest.mark.parametrize(
    ("product", "override"),
    [
        ("discharge_daily_mean", {"approval_status": "Provisional"}),
        ("discharge_daily_mean", {"qualifier": ["ESTIMATED", "ICE"]}),
        ("discharge_instantaneous", {"method_category": "Acoustic"}),
    ],
)
def test_conflicting_annotation_for_same_series_and_time_isolates_only_offending_series(
    product: str, override: dict[str, object]
) -> None:
    good = feature(product, time_series_id="opaque-series-b", approval_status="Approved", qualifier=None)
    bad_1 = feature(product, time_series_id="opaque-series-a")
    bad_2 = feature(product, time_series_id="opaque-series-a", **override)
    parsed = decode([bad_1, bad_2, good], product)
    baseline = decode([good], product)
    pl_testing.assert_frame_equal(parsed.rows, baseline.rows)
    pl_testing.assert_frame_equal(
        parsed.annotations.observation_tables[
            f"usgs_nwis.{config().products[ProductId(product)].coordinates.value.endpoint}"
        ].rows,
        baseline.annotations.observation_tables[
            f"usgs_nwis.{config().products[ProductId(product)].coordinates.value.endpoint}"
        ].rows,
    )
    assert any(item.status is OutcomeStatus.UNSUPPORTED for item in parsed.outcomes)
    assert any(item.code == "unsupported_source_series" and item.severity == "warning" for item in parsed.issues)


@pytest.mark.parametrize("bad_method", [123, True, [], {}])
def test_malformed_method_category_isolates_only_offending_series(bad_method: object) -> None:
    good = feature("discharge_instantaneous", time_series_id="opaque-series-b", method_category="Sensor")
    bad = feature("discharge_instantaneous", time_series_id="opaque-series-a", method_category=bad_method)
    parsed = decode([bad, good], "discharge_instantaneous")
    baseline = decode([good], "discharge_instantaneous")
    pl_testing.assert_frame_equal(parsed.rows, baseline.rows)
    assert parsed.annotations.observation_tables["usgs_nwis.continuous"].rows["method_category"].to_list() == ["Sensor"]
    assert any(item.status is OutcomeStatus.UNSUPPORTED for item in parsed.outcomes)
    assert any(item.code == "unsupported_source_series" for item in parsed.issues)


def _usgs_feature(
    *,
    location: str,
    ts_id: str,
    parameter_code: str,
    statistic_id: str | None,
    unit: str,
    time_str: str,
    value: str | None,
    approval_status: str | None,
    qualifier: str | list[str] | None,
    method_category: str | None = None,
) -> dict[str, object]:
    props: dict[str, object] = {
        "time_series_id": ts_id,
        "monitoring_location_id": location,
        "parameter_code": parameter_code,
        "statistic_id": statistic_id,
        "unit_of_measure": unit,
        "time": time_str,
        "value": value,
        "approval_status": approval_status,
        "qualifier": qualifier,
    }
    if "T" in time_str:
        props["method_category"] = method_category
    return {"type": "Feature", "id": f"rec-{ts_id}-{time_str}", "properties": props}


def test_public_usgs_annotations_workflows_utc_pick_mixed_bundle_and_store(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    sel_all = rr.find(provider="usgs_nwis", station="02196000", quantity="discharge")
    daily_series = next(item for item in sel_all.series if item.product_id == "discharge_daily_mean")
    daily_sel = rr.pick(sel_all, series_id=daily_series.series_id)

    cont_series = next(item for item in sel_all.series if item.product_id == "discharge_instantaneous")
    cont_sel = rr.pick(sel_all, series_id=cont_series.series_id)

    state = {"approval": "Provisional"}

    class MutableTransport:
        def __init__(self) -> None:
            self.forbid = False
            self.calls: list[object] = []

        def send(self, request):
            assert not self.forbid, "offline reuse must not call transport"
            self.calls.append(request)
            if "/daily/" in request.url:
                features = [
                    _usgs_feature(
                        location="USGS-02196000",
                        ts_id=daily_series.identity.published_id or "",
                        parameter_code="00060",
                        statistic_id="00003",
                        unit="ft^3/s",
                        time_str="2024-01-02",
                        value="100.0",
                        approval_status=state["approval"],
                        qualifier="Ice",
                    ),
                    _usgs_feature(
                        location="USGS-02196000",
                        ts_id=daily_series.identity.published_id or "",
                        parameter_code="00060",
                        statistic_id="00003",
                        unit="ft^3/s",
                        time_str="2024-01-03",
                        value=None,
                        approval_status="Provisional",
                        qualifier=["DISCONTINUED"],
                    ),
                ]
            else:
                features = [
                    _usgs_feature(
                        location="USGS-02196000",
                        ts_id=cont_series.identity.published_id or "",
                        parameter_code="00060",
                        statistic_id="00011",
                        unit="ft^3/s",
                        time_str="2024-01-02T05:00:00-05:00",
                        value="200.0",
                        approval_status="Approved",
                        qualifier=None,
                        method_category="Sensor",
                    )
                ]
            body = json.dumps({"type": "FeatureCollection", "features": features, "links": []}).encode("utf-8")
            return TransportResponse(
                body, 200, datetime(2026, 9, 28, tzinfo=UTC), "application/geo+json", request.url, request.params or {}
            )

    transport = MutableTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    canonical_cols = tuple(ObservationDataSchema.polars_schema)
    # 1. Fetch continuous + verify UTC projection vs native annotation frame
    cont_res = rr.fetch(cont_sel, start="2024-01-02", end="2024-01-03", cache="bypass", on_issue="raise")
    assert tuple(cont_res.data.columns) == canonical_cols
    assert tuple(cont_res.to_polars().columns) == canonical_cols
    utc_cont = rr.to_utc(cont_res)
    utc_projected = utc_cont.to_polars(annotations=True)
    assert utc_projected["time"].to_list() == [datetime(2024, 1, 2, 10, 0)]
    assert utc_projected["method_category"].to_list() == ["Sensor"]
    native_ann = rr.annotations(cont_res, schema="usgs_nwis.continuous")
    assert native_ann["time"].to_list() == [datetime(2024, 1, 2, 5, 0)]
    assert native_ann["time_zone"].to_list() == ["-05:00"]
    utc_ann = rr.annotations(utc_cont, schema="usgs_nwis.continuous")
    assert utc_ann["time"].to_list() == [datetime(2024, 1, 2, 10, 0)]
    assert utc_ann["time_zone"].to_list() == ["+00:00"]

    # 2. Fetch daily into cache store, inspect catalog, projection, pandas, and pick
    daily_res = rr.fetch(daily_sel, start="2024-01-01", end="2024-01-04", cache="refresh", on_issue="raise")
    catalog = rr.annotations(daily_res)
    assert catalog.schema == pl.Schema(CATALOG_SCHEMA)
    assert catalog["schema"].to_list() == ["usgs_nwis.daily", "usgs_nwis.daily"]
    assert catalog["name"].to_list() == ["approval_status", "qualifier"]
    assert catalog["row_count"].to_list() == [2, 2]
    assert catalog["unmeasured_count"].to_list() == [0, 0]

    proj_one = daily_res.to_polars(annotations="approval_status")
    assert list(proj_one.columns) == [*canonical_cols, "approval_status"]
    assert proj_one["approval_status"].to_list() == ["Provisional", "Provisional"]

    pd_df = daily_res.to_pandas(annotations=["approval_status", "qualifier"])
    assert isinstance(pd_df, pd.DataFrame)
    assert list(pd_df.columns) == [*canonical_cols, "approval_status", "qualifier"]

    picked_res = rr.pick(daily_res, series_id=daily_series.series_id)
    pl_testing.assert_frame_equal(
        rr.annotations(picked_res, schema="usgs_nwis.daily"),
        rr.annotations(daily_res, schema="usgs_nwis.daily"),
    )

    # 3. Offline cache reuse & annotation-only refresh
    transport.forbid = True
    reused = rr.fetch(daily_sel, start="2024-01-01", end="2024-01-04", cache="reuse", on_issue="raise")
    pl_testing.assert_frame_equal(reused.data, daily_res.data)
    pl_testing.assert_frame_equal(reused.to_polars(annotations=True), daily_res.to_polars(annotations=True))

    transport.forbid = False
    state["approval"] = "Approved"
    refreshed = rr.fetch(daily_sel, start="2024-01-01", end="2024-01-04", cache="refresh", on_issue="raise")
    pl_testing.assert_frame_equal(refreshed.data, daily_res.data)
    assert refreshed.to_polars(annotations="approval_status")["approval_status"].to_list() == [
        "Approved",
        "Provisional",
    ]

    # 4. Mixed daily + continuous result projects shared + continuous-only fields with nulls on daily
    mixed_sel = rr.pick(sel_all, series_id=(daily_series.series_id, cont_series.series_id))
    mixed_res = rr.fetch(mixed_sel, start="2024-01-01", end="2024-01-04", cache="bypass", on_issue="raise")
    mixed_proj = mixed_res.to_polars(annotations=True).sort("product_id", "time")
    assert set(mixed_proj.columns) == {
        *canonical_cols,
        "approval_status",
        "qualifier",
        "method_category",
    }
    daily_part = mixed_proj.filter(pl.col("product_id") == "discharge_daily_mean")
    cont_part = mixed_proj.filter(pl.col("product_id") == "discharge_instantaneous")
    assert daily_part["method_category"].to_list() == [None, None]
    assert cont_part["method_category"].to_list() == ["Sensor"]

    # 5. Bundle v4 round-trip preserves annotations
    restored = rr.from_bundle(rr.to_bundle(mixed_res))
    pl_testing.assert_frame_equal(restored.data, mixed_res.data)
    pl_testing.assert_frame_equal(rr.annotations(restored), rr.annotations(mixed_res))
    pl_testing.assert_frame_equal(
        rr.annotations(restored, schema="usgs_nwis.daily"),
        rr.annotations(mixed_res, schema="usgs_nwis.daily"),
    )
    pl_testing.assert_frame_equal(
        rr.annotations(restored, schema="usgs_nwis.continuous"),
        rr.annotations(mixed_res, schema="usgs_nwis.continuous"),
    )
    pl_testing.assert_frame_equal(restored.to_polars(annotations=True), mixed_res.to_polars(annotations=True))


def test_rr_fetch_single_page_exact_duplicate_feature_deduplicates_cleanly(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    sel = rr.find(provider="usgs_nwis", station="02196000", quantity="discharge", statistic="mean")
    daily_series = sel.series[0]
    daily_sel = rr.pick(sel, series_id=daily_series.series_id)

    base = _usgs_feature(
        location="USGS-02196000",
        ts_id=daily_series.identity.published_id or "",
        parameter_code="00060",
        statistic_id="00003",
        unit="ft^3/s",
        time_str="2024-01-02",
        value="100.0",
        approval_status="Approved",
        qualifier="Ice",
    )
    duplicate = {
        **base,
        "id": "different-record-revision",
        "properties": {**dict(base["properties"]), "last_modified": "2024-02-01T00:00:00Z"},
    }
    body = json.dumps({"type": "FeatureCollection", "features": [base, duplicate], "links": []}).encode("utf-8")

    class SinglePageTransport:
        def send(self, request):
            return TransportResponse(
                body, 200, datetime(2026, 9, 28, tzinfo=UTC), "application/geo+json", request.url, request.params or {}
            )

    monkeypatch.setattr(discovery, "HttpClient", SinglePageTransport)
    result = rr.fetch(daily_sel, start="2024-01-01", end="2024-01-04", cache="bypass", on_issue="raise")
    assert result.data.height == 1
    assert not result.issues
    ann = rr.annotations(result, schema="usgs_nwis.daily")
    assert ann.height == 1
    assert ann["approval_status"].to_list() == ["Approved"]
    assert ann["qualifier"].to_list() == [["Ice"]]
    assert any(
        item.series_id == daily_series.series_id and item.status is OutcomeStatus.SUCCESS for item in result.outcomes
    )


def test_rr_fetch_single_page_conflicting_annotation_isolates_only_offending_series(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    sel = rr.find(provider="usgs_nwis", station="02196000", quantity="discharge", statistic="mean")
    assert len(sel.series) >= 2
    bad_series, good_series = sel.series[0], sel.series[1]

    bad_1 = _usgs_feature(
        location="USGS-02196000",
        ts_id=bad_series.identity.published_id or "",
        parameter_code="00060",
        statistic_id="00003",
        unit="ft^3/s",
        time_str="2024-01-02",
        value="100.0",
        approval_status="Approved",
        qualifier=None,
    )
    bad_2 = _usgs_feature(
        location="USGS-02196000",
        ts_id=bad_series.identity.published_id or "",
        parameter_code="00060",
        statistic_id="00003",
        unit="ft^3/s",
        time_str="2024-01-02",
        value="100.0",
        approval_status="Provisional",
        qualifier=["ESTIMATED"],
    )
    good = _usgs_feature(
        location="USGS-02196000",
        ts_id=good_series.identity.published_id or "",
        parameter_code="00060",
        statistic_id="00003",
        unit="ft^3/s",
        time_str="2024-01-02",
        value="250.0",
        approval_status="Approved",
        qualifier="Ice",
    )
    body = json.dumps({"type": "FeatureCollection", "features": [bad_1, bad_2, good], "links": []}).encode("utf-8")

    class BroadPageTransport:
        def send(self, request):
            return TransportResponse(
                body, 200, datetime(2026, 9, 28, tzinfo=UTC), "application/geo+json", request.url, request.params or {}
            )

    monkeypatch.setattr(discovery, "HttpClient", BroadPageTransport)
    result = rr.fetch(sel, start="2024-01-01", end="2024-01-04", cache="bypass", on_issue="ignore")
    assert result.data["series_id"].to_list() == [good_series.series_id]
    ann = rr.annotations(result, schema="usgs_nwis.daily")
    assert ann["series_id"].to_list() == [good_series.series_id]
    assert ann["approval_status"].to_list() == ["Approved"]
    assert ann["qualifier"].to_list() == [["Ice"]]
    assert any(issue.details.get("series_id") == bad_series.series_id for issue in result.issues)
    assert any(
        item.series_id == good_series.series_id and item.status is OutcomeStatus.SUCCESS for item in result.outcomes
    )
    assert any(
        item.series_id == bad_series.series_id and item.status is OutcomeStatus.UNSUPPORTED for item in result.outcomes
    )
