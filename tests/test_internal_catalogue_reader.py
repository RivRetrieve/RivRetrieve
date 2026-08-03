from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import cast

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    AvailabilityDtype,
)
from rivretrieve._internal.issues import (
    FatalContractError,
    InvalidCatalogueSourceError,
    IssuePolicyError,
    LiveCatalogueRoutingNotImplementedError,
)
from rivretrieve._internal.primitives import CatalogSource, OnIssue, ProviderId
from rivretrieve._internal.results import CatalogProvenance, CatalogResult


def _issue_policy_error_chain(exc: BaseException) -> list[IssuePolicyError]:
    found = []
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, IssuePolicyError):
            found.append(current)
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None:
            stack.append(current.__context__)
    return found


def _reader(artifact: PackagedCatalogArtifact) -> CatalogueReader:
    return CatalogueReader(artifact, ProviderId("stub_provider"))


def _expected_provenance() -> CatalogProvenance:
    return CatalogProvenance(
        source="packaged",
        provider_id=ProviderId("stub_provider"),
        rivretrieve_version=rr.__version__,
        catalogue_version="2026.01",
        artifact_id=None,
        artifact_path=None,
        artifact_hash=None,
        generated_at=None,
        retrieved_at=None,
        endpoints=(),
        query=None,
        response_version=None,
    )


def _expected_live_provenance() -> CatalogProvenance:
    return CatalogProvenance(
        source="live",
        provider_id=ProviderId("stub_provider"),
        rivretrieve_version=rr.__version__,
        catalogue_version="2026.01",
        artifact_id=None,
        artifact_path=None,
        artifact_hash=None,
        generated_at=None,
        retrieved_at=None,
        endpoints=(),
        query=None,
        response_version=None,
    )


def _assert_unsupported_issue(
    result: CatalogResult[pl.DataFrame],
    *,
    method: str,
    capability: str,
) -> None:
    (issue,) = result.issues
    assert issue.severity == "warning"
    assert issue.code == "live_catalogue_unsupported"
    assert issue.provider_id == ProviderId("stub_provider")
    assert issue.details == {"method": method, "capability": capability, "source": "live"}


def test_catalogue_reader_products_returns_packaged_catalog_result(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    artifact = stub_packaged_catalogue_artifact()

    result = _reader(artifact).read_products()

    assert isinstance(result, CatalogResult)
    pl_testing.assert_frame_equal(result.data, artifact.products, check_exact=True)
    assert result.data.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert result.provenance == _expected_provenance()
    assert result.issues == ()


def test_catalogue_reader_stations_returns_packaged_catalog_result(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    artifact = stub_packaged_catalogue_artifact()

    result = _reader(artifact).read_stations()

    assert isinstance(result, CatalogResult)
    pl_testing.assert_frame_equal(result.data, artifact.stations, check_exact=True)
    assert result.data.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert result.provenance == _expected_provenance()
    assert result.issues == ()


def test_catalogue_reader_station_products_returns_packaged_catalog_result(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    artifact = stub_packaged_catalogue_artifact()

    result = _reader(artifact).read_station_products()

    assert isinstance(result, CatalogResult)
    pl_testing.assert_frame_equal(result.data, artifact.station_products, check_exact=True)
    assert result.data.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert result.provenance == _expected_provenance()
    assert result.issues == ()


def test_catalogue_reader_product_filters_are_exact_and_case_sensitive(
    stub_packaged_catalogue_artifact_rich: Callable[..., PackagedCatalogArtifact],
) -> None:
    reader = _reader(stub_packaged_catalogue_artifact_rich())

    water_level = reader.read_products(observed_property="water_level").data
    daily = reader.read_products(frequency="daily").data
    mean = reader.read_products(statistic="mean").data
    combined = reader.read_products(observed_property="water_level", frequency="daily", statistic="mean").data
    wrong_case = reader.read_products(observed_property="Water_Level").data

    assert water_level["product_id"].to_list() == ["level", "level_hourly", "level_max"]
    assert daily["product_id"].to_list() == ["level", "flow", "level_max"]
    assert mean["product_id"].to_list() == ["level", "flow"]
    assert combined["product_id"].to_list() == ["level"]
    assert wrong_case.height == 0


def test_catalogue_reader_product_filter_no_match_returns_empty_result(
    stub_packaged_catalogue_artifact_rich: Callable[..., PackagedCatalogArtifact],
) -> None:
    result = _reader(stub_packaged_catalogue_artifact_rich()).read_products(observed_property="temperature")

    assert result.data.height == 0
    assert result.data.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert result.issues == ()


def test_catalogue_reader_products_use_exact_reduced_schema(
    stub_packaged_catalogue_artifact_rich: Callable[..., PackagedCatalogArtifact],
) -> None:
    result = _reader(stub_packaged_catalogue_artifact_rich()).read_products(observed_property="water_level")

    assert result.data.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert "flow" not in result.data["product_id"].to_list()


def test_catalogue_reader_station_products_filters_station_ids(
    stub_packaged_catalogue_artifact_rich: Callable[..., PackagedCatalogArtifact],
) -> None:
    result = _reader(stub_packaged_catalogue_artifact_rich()).read_station_products(stations=["station-2"])

    assert result.data["station_id"].to_list() == ["station-2", "station-2"]


def test_catalogue_reader_station_products_empty_sequence_matches_none(
    stub_packaged_catalogue_artifact_rich: Callable[..., PackagedCatalogArtifact],
) -> None:
    reader = _reader(stub_packaged_catalogue_artifact_rich())

    none_result = reader.read_station_products(stations=None)
    empty_result = reader.read_station_products(stations=[])

    pl_testing.assert_frame_equal(empty_result.data, none_result.data, check_exact=True)
    assert empty_result.data.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert empty_result.issues == ()


def test_catalogue_reader_station_products_unknown_ids_are_dropped(
    stub_packaged_catalogue_artifact_rich: Callable[..., PackagedCatalogArtifact],
) -> None:
    reader = _reader(stub_packaged_catalogue_artifact_rich())

    partial = reader.read_station_products(stations=["station-2", "missing"])
    empty = reader.read_station_products(stations=["missing"])

    assert partial.data["station_id"].to_list() == ["station-2", "station-2"]
    assert partial.issues == ()
    assert empty.data.height == 0
    assert empty.issues == ()


@pytest.mark.parametrize("source", ["archive", "", "garbage"])
def test_catalogue_reader_invalid_source_raises_direct_fatal(
    source: str,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    reader = _reader(stub_packaged_catalogue_artifact())

    with pytest.raises(InvalidCatalogueSourceError) as exc_info:
        reader.read_products(
            source=cast(CatalogSource, source),
            observed_property=cast(str, 123),
            on_issue="ignore",
        )

    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_catalogue_reader_invalid_source_ignores_on_issue_policy(
    on_issue: OnIssue,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    reader = _reader(stub_packaged_catalogue_artifact())

    with pytest.raises(InvalidCatalogueSourceError) as exc_info:
        reader.read_stations(source=cast(CatalogSource, "archive"), on_issue=on_issue)

    assert _issue_policy_error_chain(exc_info.value) == []


def test_catalogue_reader_non_string_filter_raises_direct_fatal(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    reader = _reader(stub_packaged_catalogue_artifact())

    with pytest.raises(FatalContractError) as exc_info:
        reader.read_products(observed_property=cast(str, 123), on_issue="raise")

    assert _issue_policy_error_chain(exc_info.value) == []


def test_reader_preserves_polars_schema_after_empty_filter(
    stub_packaged_catalogue_artifact_rich: Callable[..., PackagedCatalogArtifact],
) -> None:
    reader = _reader(stub_packaged_catalogue_artifact_rich())

    products = reader.read_products(observed_property="temperature").data
    station_products = reader.read_station_products(stations=["missing"]).data

    assert products.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert station_products.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert station_products.schema["availability"] == AvailabilityDtype


def test_catalogue_reader_packaged_products_unchanged_by_live_capability(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    stub_packaged_catalogue_artifact_live_capable: Callable[..., PackagedCatalogArtifact],
) -> None:
    for artifact in (stub_packaged_catalogue_artifact(), stub_packaged_catalogue_artifact_live_capable()):
        result = _reader(artifact).read_products(source="packaged")
        pl_testing.assert_frame_equal(result.data, artifact.products, check_exact=True)
        assert result.provenance == _expected_provenance()
        assert result.issues == ()


def test_catalogue_reader_packaged_stations_unchanged_by_live_capability(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    stub_packaged_catalogue_artifact_live_capable: Callable[..., PackagedCatalogArtifact],
) -> None:
    for artifact in (stub_packaged_catalogue_artifact(), stub_packaged_catalogue_artifact_live_capable()):
        result = _reader(artifact).read_stations(source="packaged")
        pl_testing.assert_frame_equal(result.data, artifact.stations, check_exact=True)
        assert result.provenance == _expected_provenance()
        assert result.issues == ()


def test_catalogue_reader_packaged_station_products_unchanged_by_live_capability(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    stub_packaged_catalogue_artifact_live_capable: Callable[..., PackagedCatalogArtifact],
) -> None:
    for artifact in (stub_packaged_catalogue_artifact(), stub_packaged_catalogue_artifact_live_capable()):
        result = _reader(artifact).read_station_products(source="packaged")
        pl_testing.assert_frame_equal(result.data, artifact.station_products, check_exact=True)
        assert result.provenance == _expected_provenance()
        assert result.issues == ()


def test_catalogue_reader_live_products_warn_returns_empty_result_with_issue(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    with pytest.warns(RuntimeWarning, match="does not support live catalogue method read_products"):
        result = _reader(stub_packaged_catalogue_artifact()).read_products(source="live", on_issue="warn")

    assert result.data.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert result.data.height == 0
    assert result.provenance == _expected_live_provenance()
    _assert_unsupported_issue(result, method="read_products", capability="live_products")


def test_catalogue_reader_live_stations_warn_returns_empty_result_with_issue(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    with pytest.warns(RuntimeWarning, match="does not support live catalogue method read_stations"):
        result = _reader(stub_packaged_catalogue_artifact()).read_stations(source="live", on_issue="warn")

    assert result.data.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert result.data.height == 0
    assert result.provenance == _expected_live_provenance()
    _assert_unsupported_issue(result, method="read_stations", capability="live_stations")


def test_catalogue_reader_live_station_products_warn_returns_empty_result_with_issue(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    with pytest.warns(RuntimeWarning, match="does not support live catalogue method read_station_products"):
        result = _reader(stub_packaged_catalogue_artifact()).read_station_products(source="live", on_issue="warn")

    assert result.data.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert result.data.height == 0
    assert result.provenance == _expected_live_provenance()
    _assert_unsupported_issue(result, method="read_station_products", capability="live_station_products")


def test_catalogue_reader_live_products_raise_wraps_unsupported_issue(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    with pytest.raises(IssuePolicyError) as exc_info:
        _reader(stub_packaged_catalogue_artifact()).read_products(source="live", on_issue="raise")

    assert exc_info.value.issues[0].code == "live_catalogue_unsupported"


def test_catalogue_reader_live_stations_raise_wraps_unsupported_issue(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    with pytest.raises(IssuePolicyError) as exc_info:
        _reader(stub_packaged_catalogue_artifact()).read_stations(source="live", on_issue="raise")

    assert exc_info.value.issues[0].code == "live_catalogue_unsupported"


def test_catalogue_reader_live_station_products_raise_wraps_unsupported_issue(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    with pytest.raises(IssuePolicyError) as exc_info:
        _reader(stub_packaged_catalogue_artifact()).read_station_products(source="live", on_issue="raise")

    assert exc_info.value.issues[0].code == "live_catalogue_unsupported"


def test_catalogue_reader_live_products_ignore_returns_issue_without_warning(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    with warnings.catch_warnings(record=True) as captured_warnings:
        result = _reader(stub_packaged_catalogue_artifact()).read_products(source="live", on_issue="ignore")

    assert captured_warnings == []
    assert result.data.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert result.data.height == 0
    _assert_unsupported_issue(result, method="read_products", capability="live_products")


def test_catalogue_reader_live_stations_ignore_returns_issue_without_warning(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    with warnings.catch_warnings(record=True) as captured_warnings:
        result = _reader(stub_packaged_catalogue_artifact()).read_stations(source="live", on_issue="ignore")

    assert captured_warnings == []
    assert result.data.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert result.data.height == 0
    _assert_unsupported_issue(result, method="read_stations", capability="live_stations")


def test_catalogue_reader_live_station_products_ignore_returns_issue_without_warning(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    with warnings.catch_warnings(record=True) as captured_warnings:
        result = _reader(stub_packaged_catalogue_artifact()).read_station_products(source="live", on_issue="ignore")

    assert captured_warnings == []
    assert result.data.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert result.data.height == 0
    _assert_unsupported_issue(result, method="read_station_products", capability="live_station_products")


@pytest.mark.parametrize(
    "method_name",
    ["read_products", "read_stations", "read_station_products"],
)
def test_catalogue_reader_invalid_source_remains_direct_fatal_for_all_methods(
    method_name: str,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    method = getattr(_reader(stub_packaged_catalogue_artifact()), method_name)

    with pytest.raises(InvalidCatalogueSourceError) as exc_info:
        method(source=cast(CatalogSource, "archive"), on_issue="ignore")

    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("live_capable", [False, True])
@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_catalogue_reader_invalid_source_ignores_capability_and_on_issue(
    live_capable: bool,
    on_issue: OnIssue,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    artifact = stub_packaged_catalogue_artifact(
        live_stations=live_capable,
        live_products=live_capable,
        live_station_products=live_capable,
    )

    with pytest.raises(InvalidCatalogueSourceError) as exc_info:
        _reader(artifact).read_products(source=cast(CatalogSource, "archive"), on_issue=on_issue)

    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_catalogue_reader_live_capable_products_raise_defensive_fatal_for_every_on_issue(
    on_issue: OnIssue,
    stub_packaged_catalogue_artifact_live_capable: Callable[..., PackagedCatalogArtifact],
) -> None:
    with pytest.raises(LiveCatalogueRoutingNotImplementedError) as exc_info:
        _reader(stub_packaged_catalogue_artifact_live_capable()).read_products(source="live", on_issue=on_issue)

    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_catalogue_reader_live_capable_stations_raise_defensive_fatal_for_every_on_issue(
    on_issue: OnIssue,
    stub_packaged_catalogue_artifact_live_capable: Callable[..., PackagedCatalogArtifact],
) -> None:
    with pytest.raises(LiveCatalogueRoutingNotImplementedError) as exc_info:
        _reader(stub_packaged_catalogue_artifact_live_capable()).read_stations(source="live", on_issue=on_issue)

    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_catalogue_reader_live_capable_station_products_raise_defensive_fatal_for_every_on_issue(
    on_issue: OnIssue,
    stub_packaged_catalogue_artifact_live_capable: Callable[..., PackagedCatalogArtifact],
) -> None:
    with pytest.raises(LiveCatalogueRoutingNotImplementedError) as exc_info:
        _reader(stub_packaged_catalogue_artifact_live_capable()).read_station_products(source="live", on_issue=on_issue)

    assert _issue_policy_error_chain(exc_info.value) == []


def test_catalogue_reader_live_products_invalid_filter_remains_direct_fatal(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    with pytest.raises(FatalContractError) as exc_info:
        _reader(stub_packaged_catalogue_artifact()).read_products(
            source="live",
            observed_property=cast(str, 123),
            on_issue="ignore",
        )

    assert _issue_policy_error_chain(exc_info.value) == []
