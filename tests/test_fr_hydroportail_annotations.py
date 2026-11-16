"""Source-independent tests for HydroPortail observation annotations (#817)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

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
from rivretrieve._internal.observations import ObservationDataSchema, ReceiptAuthorship
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.fr_hydroportail.config import FrHydroportailSourceCoordinates, config
from rivretrieve._internal.providers.fr_hydroportail.parse import parse
from rivretrieve._internal.source_annotations import CATALOG_SCHEMA, AnnotationScope
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_DEFAULT_ORIGIN = SourceCallOrigin(
    "https://hydro.eaufrance.fr/stationhydro/ajax/Y251002001/series",
    {},
    200,
    datetime(2026, 9, 21, tzinfo=UTC),
    "application/json",
    UnknownOriginFact(),
    UnknownOriginFact(),
)


def _payload(
    *,
    station: str = "Y251002001",
    product: str = "discharge_instantaneous",
    variant: str = "raw",
    rows: list[dict[str, object]],
) -> Payload:
    metric = "Q" if product == "discharge_instantaneous" else "H"
    unit = "l" if metric == "Q" else "mm"
    title = "Débit instantané - Test" if metric == "Q" else "Hauteur instantanée - Test"
    body = {
        "timezone": "UTC",
        "range": ["2020-01-01T00:00:00Z", "2020-01-01T23:59:59Z"],
        "statistics": {},
        "correctionCurves": [],
        "events": [],
        "thresholds": [],
        "tonnages": [],
        "unitH": "m",
        "unitQ": "m3",
        "unitRR": "mm",
        "series": {
            "code": station,
            "metric": metric,
            "timeStep": None,
            "statuses": variant,
            "rolling": False,
            "unit": unit,
            "title": title,
            "baseFilename": f"{station}_{metric}",
            "data": rows,
        },
    }
    window = _make_fetch_window(
        WindowEndpoint(2020, 1, 1, 0, 0, 0, 0),
        WindowEndpoint(2020, 1, 1, 23, 59, 59, 0),
    )
    return Payload(
        SourceCoordinates(FrHydroportailSourceCoordinates(metric, variant)),
        ((station, ProductId(product)),),
        window,
        json.dumps(body).encode(),
        _DEFAULT_ORIGIN,
        (),
    )


def test_hydroportail_annotation_schema_defines_verified_codes() -> None:
    from rivretrieve._internal.providers.fr_hydroportail.annotations import (
        FR_HYDROPORTAIL_SERIES_SCHEMA,
        HYDROPORTAIL_GLOSSAIRE_URL,
    )

    assert FR_HYDROPORTAIL_SERIES_SCHEMA.schema_id == "fr_hydroportail.series"
    assert FR_HYDROPORTAIL_SERIES_SCHEMA.provider_id == "fr_hydroportail"
    assert FR_HYDROPORTAIL_SERIES_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [field.name for field in FR_HYDROPORTAIL_SERIES_SCHEMA.fields] == ["s", "q", "m", "c"]
    assert [field.dtype for field in FR_HYDROPORTAIL_SERIES_SCHEMA.fields] == ["Int64", "Int64", "Int64", "Int64"]
    fields = {field.name: field for field in FR_HYDROPORTAIL_SERIES_SCHEMA.fields}
    for field in fields.values():
        assert field.description
        assert field.reference_url == HYDROPORTAIL_GLOSSAIRE_URL
    assert "status" in fields["s"].description.lower()
    assert "qualification" in fields["q"].description.lower()
    assert "method" in fields["m"].description.lower()
    assert "continuity" in fields["c"].description.lower()
    assert "correction" not in fields["c"].description.lower()


@pytest.mark.parametrize("product", ["discharge_instantaneous", "stage_instantaneous"])
@pytest.mark.parametrize("variant", ["raw", "validated", "pre_validated_and_validated", "most_valid"])
def test_parse_preserves_native_codes_nulls_and_sorting_alignment(product: str, variant: str) -> None:
    parsed = parse(
        _payload(
            product=product,
            variant=variant,
            rows=[
                {"t": "2020-01-01T02:00:00Z", "v": None, "md": None, "s": 16, "q": 12, "m": 10, "c": 1},
                {"t": "2020-01-01T00:00:00Z", "v": 1500, "md": None, "s": 4, "q": None, "m": 0, "c": 0},
                {"t": "2020-01-01T01:00:00Z", "v": 1600.5, "md": None, "s": 8, "q": 20, "m": 16, "c": 8},
            ],
        ),
        config(),
    )
    assert parsed.outcomes[0].status is OutcomeStatus.SUCCESS
    assert parsed.rows.height == 3
    assert parsed.rows["value"].to_list() == [1500.0, 1600.5, None]
    assert set(parsed.annotations.observation_tables) == {"fr_hydroportail.series"}
    assert not parsed.annotations.series_tables
    table = parsed.annotations.observation_tables["fr_hydroportail.series"]
    assert table.measurement_indices == (0, 1, 2)
    assert table.rows["time"].to_list() == parsed.rows["time"].to_list()
    assert table.rows["measured"].to_list() == [True, True, True]
    assert table.rows["s"].dtype == pl.Int64()
    assert table.rows["s"].to_list() == [4, 8, 16]
    assert table.rows["q"].to_list() == [None, 20, 12]
    assert table.rows["m"].to_list() == [0, 16, 10]
    assert table.rows["c"].to_list() == [0, 8, 1]
    assert "md" not in table.rows.columns
    assert "baseFilename" not in table.rows.columns


def test_parse_empty_series_emits_empty_annotations() -> None:
    parsed = parse(_payload(rows=[]), config())
    assert parsed.outcomes[0].status is OutcomeStatus.EMPTY
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty


@pytest.mark.parametrize("field", ["s", "q", "m", "c"])
@pytest.mark.parametrize(
    "bad_value",
    [
        "__MISSING__",
        True,
        False,
        "4",
        4.0,
        [4],
        {"code": 4},
        1 << 63,
        -(1 << 63) - 1,
    ],
)
def test_parse_rejects_missing_or_non_integer_annotation_codes(field: str, bad_value: object) -> None:
    row: dict[str, object] = {"t": "2020-01-01T00:00:00Z", "v": 1500, "s": 4, "q": 16, "m": 0, "c": 0}
    if bad_value == "__MISSING__":
        del row[field]
    else:
        row[field] = bad_value
    parsed = parse(_payload(rows=[row]), config())
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty
    assert parsed.outcomes[0].status is OutcomeStatus.UNSUPPORTED
    assert parsed.outcomes[0].reason
    assert any(issue.code == "unsupported_source_structure" for issue in parsed.issues)


def test_parse_rejects_mixed_missing_annotation_key_across_rows_without_partial_annotations() -> None:
    payload = _payload(
        rows=[
            {"t": "2020-01-01T00:00:00Z", "v": 1500, "s": 4, "q": 16, "m": 0, "c": 0},
            {"t": "2020-01-01T01:00:00Z", "v": 1600, "s": 4, "q": 16, "m": 0},
        ]
    )
    parsed = parse(replace(payload), config())
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty
    assert parsed.outcomes[0].status is OutcomeStatus.UNSUPPORTED


@pytest.mark.parametrize("field", ["s", "q", "m", "c"])
@pytest.mark.parametrize("boundary", [-(1 << 63), (1 << 63) - 1])
def test_parse_accepts_int64_boundaries(field: str, boundary: int) -> None:
    row: dict[str, object] = {"t": "2020-01-01T00:00:00Z", "v": 1500, "s": 4, "q": 16, "m": 0, "c": 0}
    row[field] = boundary
    parsed = parse(_payload(rows=[row]), config())
    assert parsed.outcomes[0].status is OutcomeStatus.SUCCESS
    table = parsed.annotations.observation_tables["fr_hydroportail.series"]
    assert table.rows[field].to_list() == [boundary]


class _PublicAnnotationTransport:
    def __init__(self, handler: Callable[[str, str], list[dict[str, object]]]) -> None:
        self.handler = handler
        self.calls: list[tuple[str, str]] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        params = dict(request.params)
        variant = params["hydro_series[statusData]"]
        metric = params["hydro_series[simpleAndInterpolatedAndHourlyVariable]"]
        self.calls.append((metric, variant))
        rows = self.handler(metric, variant)
        body = {
            "timezone": "UTC",
            "range": ["2019-12-30T00:00:00Z", "2020-01-04T23:59:59Z"],
            "statistics": {},
            "correctionCurves": [],
            "events": [],
            "thresholds": [],
            "tonnages": [],
            "unitH": "m",
            "unitQ": "m3",
            "unitRR": "mm",
            "series": {
                "code": "Y251002001",
                "metric": metric,
                "timeStep": None,
                "statuses": variant,
                "rolling": False,
                "unit": "l" if metric == "Q" else "mm",
                "title": "Débit instantané - Test" if metric == "Q" else "Hauteur instantanée - Test",
                "baseFilename": f"Y251002001_{metric}",
                "data": rows,
            },
        }
        return TransportResponse(
            json.dumps(body).encode(),
            200,
            datetime(2026, 9, 21, tzinfo=UTC),
            "application/json",
            request.url,
            params,
        )


def _install_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, handler: Callable[[str, str], list[dict[str, object]]]
) -> _PublicAnnotationTransport:
    transport = _PublicAnnotationTransport(handler)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    return transport


@pytest.mark.parametrize("quantity", ["discharge", "stage"])
def test_public_discovery_and_default_projection_schemas_remain_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, quantity: str
) -> None:
    _install_transport(
        monkeypatch,
        tmp_path,
        lambda _metric, variant: [
            {"t": "2019-12-31T23:59:59Z", "v": 900, "s": 4, "q": 16, "m": 0, "c": 0},
            {
                "t": "2020-01-01T00:00:00Z",
                "v": 1500,
                "s": 16 if variant == "validated" else 4,
                "q": 20,
                "m": 10,
                "c": 0,
            },
            {"t": "2020-01-01T01:00:00Z", "v": None, "s": 4, "q": None, "m": 0, "c": 1},
            {"t": "2020-01-03T00:00:00Z", "v": 900, "s": 4, "q": 16, "m": 0, "c": 0},
        ],
    )
    selection = rr.find(provider="fr_hydroportail", station="Y251002001", quantity=quantity, statistic="instantaneous")
    assert rr.annotations(selection).is_empty()
    base_series = rr.series(selection)

    result = rr.fetch(
        rr.pick(selection, variant="validated"),
        start="2020-01-01",
        end="2020-01-02",
        on_issue="ignore",
    )
    assert list(result.data.columns) == list(ObservationDataSchema.polars_schema)
    assert result.data.height == 2
    pl_testing.assert_frame_equal(result.to_polars(), result.data)
    assert rr.series(result).columns == base_series.columns

    catalog = rr.annotations(result)
    assert list(catalog.columns) == list(CATALOG_SCHEMA)
    assert catalog["schema"].to_list() == ["fr_hydroportail.series"] * 4
    assert catalog["name"].to_list() == ["s", "q", "m", "c"]
    assert catalog["dtype"].to_list() == ["Int64"] * 4
    assert catalog["row_count"].to_list() == [2] * 4
    assert catalog["unmeasured_count"].to_list() == [0] * 4

    schema_table = rr.annotations(result, schema="fr_hydroportail.series")
    assert schema_table.height == 2
    assert schema_table["measured"].to_list() == [True, True]
    assert schema_table["time"].to_list() == [datetime(2020, 1, 1, 0, 0), datetime(2020, 1, 1, 1, 0)]

    projected_all = result.to_polars(annotations=True)
    assert projected_all.columns == [*result.data.columns, "s", "q", "m", "c"]
    assert projected_all["value"].to_list() == [1.5, None]
    assert projected_all["s"].to_list() == [16, 4]
    assert projected_all["q"].to_list() == [20, None]
    assert projected_all["m"].to_list() == [10, 0]
    assert projected_all["c"].to_list() == [0, 1]

    pl_testing.assert_frame_equal(
        result.to_polars(annotations="q"),
        projected_all.select(*result.data.columns, "q"),
    )
    pl_testing.assert_frame_equal(
        result.to_polars(annotations=["c", "s"]),
        projected_all.select(*result.data.columns, "c", "s"),
    )
    pandas_df = result.to_pandas(annotations=True)
    assert isinstance(pandas_df, pd.DataFrame)
    assert list(pandas_df.columns) == [*result.data.columns, "s", "q", "m", "c"]
    assert pd.isna(pandas_df["q"].iloc[1])


def test_overlapping_divergent_variants_clipping_pick_to_utc_reuse_and_bundles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    variant_rows = {
        "raw": [
            {"t": "2019-12-31T23:55:00Z", "v": 500, "s": 4, "q": 16, "m": 0, "c": 0},
            {"t": "2020-01-01T00:00:00Z", "v": 1000, "s": 4, "q": 16, "m": 0, "c": 0},
            {"t": "2020-01-01T01:00:00Z", "v": 2000, "s": 4, "q": 12, "m": 8, "c": 4},
        ],
        "validated": [
            {"t": "2020-01-01T00:00:00Z", "v": 1200, "s": 16, "q": 20, "m": 10, "c": 0},
            {"t": "2020-01-03T00:00:00Z", "v": 9999, "s": 16, "q": 20, "m": 10, "c": 0},
        ],
        "pre_validated_and_validated": [
            {"t": "2020-01-01T00:00:00Z", "v": 1150, "s": 12, "q": 16, "m": 10, "c": 0},
        ],
        # most_valid mixes s=16 and s=4 points without inventing a ranking or filtering out s=4.
        "most_valid": [
            {"t": "2020-01-01T00:00:00Z", "v": 1200, "s": 16, "q": 20, "m": 10, "c": 0},
            {"t": "2020-01-01T01:00:00Z", "v": 2000, "s": 4, "q": 12, "m": 8, "c": 8},
        ],
    }
    transport = _install_transport(monkeypatch, tmp_path, lambda _m, variant: variant_rows[variant])
    selection = rr.find(
        provider="fr_hydroportail", station="Y251002001", quantity="discharge", statistic="instantaneous"
    )
    result = rr.fetch(selection, start="2020-01-01", end="2020-01-02", cache="reuse", receipts=True, on_issue="ignore")
    assert len(transport.calls) == 4
    assert result.data.height == 6

    annotated = result.to_polars(annotations=True).join(
        rr.series(result).select("series_id", "variant"), on="series_id"
    )
    by_variant = {variant: annotated.filter(pl.col("variant") == variant).sort("time") for variant in variant_rows}
    assert by_variant["raw"]["time"].to_list() == [datetime(2020, 1, 1, 0, 0), datetime(2020, 1, 1, 1, 0)]
    assert by_variant["raw"]["s"].to_list() == [4, 4]
    assert by_variant["raw"]["c"].to_list() == [0, 4]
    assert by_variant["validated"]["value"].to_list() == [1.2]
    assert by_variant["validated"]["s"].to_list() == [16]
    assert by_variant["pre_validated_and_validated"]["s"].to_list() == [12]
    assert by_variant["most_valid"]["s"].to_list() == [16, 4]
    assert by_variant["most_valid"]["c"].to_list() == [0, 8]

    picked = rr.pick(result, variant="most_valid", on_issue="ignore")
    picked_df = picked.to_polars(annotations=True).sort("time")
    assert picked_df["s"].to_list() == [16, 4]
    assert picked_df["c"].to_list() == [0, 8]

    utc_result = rr.to_utc(result)
    assert_cols = ["series_id", "time", "value", "s", "q", "m", "c"]
    pl_testing.assert_frame_equal(
        utc_result.to_polars(annotations=True).select(assert_cols).sort(["series_id", "time"]),
        result.to_polars(annotations=True).select(assert_cols).sort(["series_id", "time"]),
    )

    closed = rr.pick(selection, variant=list(variant_rows))
    reused = rr.fetch(closed, start="2020-01-01", end="2020-01-02", cache="reuse", receipts=True, on_issue="ignore")
    assert len(transport.calls) == 4
    assert all(entry.authorship is ReceiptAuthorship.STORE_EXCERPT for entry in reused.receipts.entries)
    pl_testing.assert_frame_equal(
        reused.to_polars(annotations=True).sort(["series_id", "time"]),
        result.to_polars(annotations=True).sort(["series_id", "time"]),
    )

    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(rr.annotations(restored), rr.annotations(result))
    pl_testing.assert_frame_equal(
        rr.annotations(restored, schema="fr_hydroportail.series").sort(["series_id", "time"]),
        rr.annotations(result, schema="fr_hydroportail.series").sort(["series_id", "time"]),
    )
    pl_testing.assert_frame_equal(
        restored.to_polars(annotations=True).sort(["series_id", "time"]),
        result.to_polars(annotations=True).sort(["series_id", "time"]),
    )


def test_refresh_replaces_flags_with_unchanged_values_and_failed_refresh_preserves_held_annotations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    phase = {"step": "initial"}

    class _RefreshTransport(_PublicAnnotationTransport):
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params)
            variant = params["hydro_series[statusData]"]
            if phase["step"] == "fail_validated" and variant == "validated":
                self.calls.append((params["hydro_series[simpleAndInterpolatedAndHourlyVariable]"], variant))
                raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
            return super().send(request)

    def handler(_metric: str, variant: str) -> list[dict[str, object]]:
        if phase["step"] == "initial":
            return [{"t": "2020-01-01T00:00:00Z", "v": 1500, "s": 4, "q": 16, "m": 0, "c": 0}]
        if phase["step"] == "reannotated":
            # Same value v=1500, revised annotation codes.
            return [{"t": "2020-01-01T00:00:00Z", "v": 1500, "s": 16, "q": 20, "m": 10, "c": 1}]
        if variant == "raw":
            return [{"t": "2020-01-01T00:00:00Z", "v": 1500, "s": 8, "q": 12, "m": 14, "c": 4}]
        if variant == "most_valid":
            # Missing mandatory 'q' key fails structurally without wiping held data.
            return [{"t": "2020-01-01T00:00:00Z", "v": 1500, "s": 16, "m": 10, "c": 0}]
        return [{"t": "2020-01-01T00:00:00Z", "v": 1500, "s": 12, "q": 16, "m": 10, "c": 0}]

    transport = _RefreshTransport(handler)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    selection = rr.find(
        provider="fr_hydroportail", station="Y251002001", quantity="discharge", statistic="instantaneous"
    )

    first = rr.fetch(selection, start="2020-01-01", end="2020-01-01", cache="reuse", on_issue="ignore")
    assert first.to_polars(annotations=True)["s"].unique().to_list() == [4]

    phase["step"] = "reannotated"
    refreshed = rr.fetch(selection, start="2020-01-01", end="2020-01-01", cache="refresh", on_issue="ignore")
    ref_df = refreshed.to_polars(annotations=True)
    assert ref_df["value"].unique().to_list() == [1.5]
    assert ref_df["s"].unique().to_list() == [16]
    assert ref_df["q"].unique().to_list() == [20]
    assert ref_df["m"].unique().to_list() == [10]
    assert ref_df["c"].unique().to_list() == [1]

    phase["step"] = "fail_validated"
    partial_refresh = rr.fetch(selection, start="2020-01-01", end="2020-01-01", cache="refresh", on_issue="ignore")
    outcomes = {
        dict(rr.series(partial_refresh).select("series_id", "variant").iter_rows())[o.series_id]: o.status
        for o in partial_refresh.outcomes
        if o.series_id
    }
    assert outcomes["raw"] is OutcomeStatus.SUCCESS
    assert outcomes["pre_validated_and_validated"] is OutcomeStatus.SUCCESS
    assert outcomes["validated"] is OutcomeStatus.FAILED
    assert outcomes["most_valid"] is OutcomeStatus.UNSUPPORTED

    held = rr.fetch(selection, start="2020-01-01", end="2020-01-01", cache="reuse", on_issue="ignore")
    held_by_var = {
        row["variant"]: (row["s"], row["q"], row["m"], row["c"])
        for row in held.to_polars(annotations=True)
        .join(rr.series(held).select("series_id", "variant"), on="series_id")
        .iter_rows(named=True)
    }
    # Succeeded siblings updated; failed/unsupported variants preserved previously held annotations.
    assert held_by_var["raw"] == (8, 12, 14, 4)
    assert held_by_var["pre_validated_and_validated"] == (12, 16, 10, 0)
    assert held_by_var["validated"] == (16, 20, 10, 1)
    assert held_by_var["most_valid"] == (16, 20, 10, 1)


def test_public_empty_series_leaves_annotations_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _install_transport(monkeypatch, tmp_path, lambda _m, _v: [])
    selection = rr.pick(
        rr.find(provider="fr_hydroportail", station="Y251002001", quantity="discharge", statistic="instantaneous"),
        variant="validated",
    )
    result = rr.fetch(selection, start="2020-01-01", end="2020-01-01", on_issue="ignore")
    assert result.outcomes[0].status is OutcomeStatus.EMPTY
    assert result.data.is_empty()
    assert rr.annotations(result).is_empty()
    assert result.to_polars(annotations=True).equals(result.data)
