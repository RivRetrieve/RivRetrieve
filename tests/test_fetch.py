from __future__ import annotations

import inspect
import warnings
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.engine import (
    FetchWindow,
    Instant,
    Payload,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    RenderedWindow,
    RowsSchema,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownOriginFact,
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
    WithIssues,
    ZoneValue,
)
from rivretrieve._internal.issues import InvalidObservationRequestError, Issue, IssuePolicyError
from rivretrieve._internal.observations import ObservationDataSchema, Receipts
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.registry import _registry
from rivretrieve._internal.source_series import (
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)

VALUES = {
    ("ca_eccc", "station-1", "level"): 10.0,
    ("ca_eccc", "station-2", "level_hourly"): 20.0,
    ("usgs_nwis", "station-1", "level"): 30.0,
    ("usgs_nwis", "station-2", "level_hourly"): 40.0,
}


def _test_definition(provider_id: str, station_id: str, product_id: str) -> SourceSeries:
    """Authored routing-contract definition, not provider scientific evidence."""
    quantity, unit = ("discharge", "m3/s") if product_id == "flow" else ("stage", "m")
    return SourceSeries(
        series_id=stable_id(provider_id, station_id, "test-route", product_id),
        provider_id=provider_id,
        station_id=station_id,
        product_id=product_id,
        identity=SourceIdentity(
            namespace="test-route", published_id=product_id, origin="mapping", evidence=("authored-routing-contract",)
        ),
        facts=(
            PhysicalFacts(
                facts_id="test-facts-" + product_id,
                quantity=known(quantity, "authored-routing-contract"),
                source_unit=known(unit, "authored-routing-contract"),
                normalized_unit=unit,
            ),
        ),
    )


def _expected_frame(data, *, provider_id="usgs_nwis"):
    frame = pl.DataFrame(data)
    definitions = [
        _test_definition(provider_id, station, product)
        for station, product in frame.select("station_id", "product_id").iter_rows()
    ]
    return (
        frame.with_columns(
            pl.Series("series_id", [item.series_id for item in definitions]),
            pl.Series("facts_id", [item.facts[0].facts_id for item in definitions]),
            pl.Series("quantity", [item.facts[0].quantity.value for item in definitions]),
            pl.Series("source_unit", [item.facts[0].source_unit.value for item in definitions]),
            pl.Series("unit", [item.facts[0].normalized_unit for item in definitions]),
        )
        .select(ObservationDataSchema.polars_schema.names())
        .cast(ObservationDataSchema.polars_schema)
    )


class _RecordingStages:
    zone = ZoneValue("+00:00")
    config = ProviderConfig(
        zone=zone,
        products={
            ProductId("level"): ProductConfig(
                coordinates=SourceCoordinates("level"),
                unit=Unit.M,
                semantics=Instant(),
            ),
            ProductId("flow"): ProductConfig(
                coordinates=SourceCoordinates("flow"),
                unit=Unit.M3_S,
                semantics=Instant(),
            ),
            ProductId("level_hourly"): ProductConfig(
                coordinates=SourceCoordinates("level_hourly"),
                unit=Unit.M,
                semantics=Instant(),
            ),
            ProductId("level_max"): ProductConfig(
                coordinates=SourceCoordinates("level_max"),
                unit=Unit.M,
                semantics=Instant(),
            ),
        },
        cache=None,
    )
    window_declarations = ProductWindowDeclarations(
        {
            ProductId(product_id): WindowDeclaration(
                WindowGranularity("date"),
                WindowRenderingVocabulary.DATE,
                StopConvention.INCLUSIVE,
            )
            for product_id in ("level", "flow", "level_hourly", "level_max")
        }
    )

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.observation_source = f"recording://{provider_id}"
        self.calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        self.fetch_windows: list[FetchWindow] = []
        self.issues_by_series: dict[tuple[str, str], tuple[Issue, ...]] = {}

    def fetch(
        self,
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
        fetch_window: FetchWindow,
        config: ProviderConfig,
        transport: object,
        *,
        scope=None,
        known_series=(),
    ) -> WithIssues[tuple[Payload, ...]]:
        del rendered_windows
        self.calls.append((stations, tuple(str(product) for product in products)))
        self.fetch_windows.append(fetch_window)
        payload = Payload(
            source_coordinates=config.products[products[0]].coordinates,
            station_products=((stations[0], products[0]),),
            fetch_window=fetch_window,
            content=f"{self.provider_id}|{stations[0]}|{products[0]}".encode(),
            origin=SourceCallOrigin(
                url=f"https://data.test/{self.provider_id}/{stations[0]}/{products[0]}",
                request_parameters={
                    "station_id": stations[0],
                    "product_id": str(products[0]),
                },
                status_code=200,
                retrieved_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                content_type="application/octet-stream",
                source_path=UnknownOriginFact(),
                query=UnknownOriginFact(),
            ),
            prerequisite_calls=(),
            scope=scope,
            known_series=known_series,
        )
        return WithIssues(
            value=(payload,),
            issues=self.issues_by_series.get((stations[0], str(products[0])), ()),
        )

    @staticmethod
    def parse(payload: Payload, config: ProviderConfig) -> ParsedSeries:
        del config
        provider_id, station_id, product_id = payload.content.decode().split("|")
        definition = _test_definition(provider_id, station_id, product_id)
        facts = definition.facts[0]
        rows = pl.DataFrame(
            {
                "station_id": [station_id],
                "product_id": [product_id],
                "series_id": [definition.series_id],
                "facts_id": [facts.facts_id],
                "source_unit": [facts.source_unit.value],
                "time": [datetime(2026, 1, 1, 12)],
                "value": [VALUES[(provider_id, station_id, product_id)]],
                "time_zone": ["+00:00"],
            },
            schema=RowsSchema.polars_schema,
        )
        window = SeriesWindow(
            start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
            end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
        )
        outcome = RetrievalOutcome(
            outcome_id=definition.series_id,
            series_id=definition.series_id,
            station_id=station_id,
            product_id=product_id,
            window=window,
            status=OutcomeStatus.SUCCESS,
            facts_ids=(facts.facts_id,),
        )
        return ParsedSeries(rows=rows, series=(definition,), inventories=(), outcomes=(outcome,))


@dataclass(frozen=True)
class _RegisteredRecorders:
    ca_eccc: _RecordingStages
    usgs_nwis: _RecordingStages


@pytest.fixture
def recording_stages(
    monkeypatch: pytest.MonkeyPatch,
    stub_packaged_catalogue_artifact_rich: Callable[..., PackagedCatalogArtifact],
) -> Iterator[_RegisteredRecorders]:
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    stages = {provider_id: _RecordingStages(provider_id) for provider_id in ("ca_eccc", "usgs_nwis")}
    for provider_id, provider_stages in stages.items():
        artifact = stub_packaged_catalogue_artifact_rich(provider_id)
        descriptions = []
        for product_id in artifact.products["product_id"].to_list():
            definition = _test_definition(provider_id, "station-1", product_id)
            descriptions.append(
                SourceDescription(product_id=product_id, identity=definition.identity, facts=definition.facts)
            )
        artifact = replace(
            artifact,
            source_descriptions=SourceDescriptions(provider_id=provider_id, descriptions=tuple(descriptions)),
            provider_info={
                **artifact.provider_info,
                "license": f"https://licenses.test/{provider_id}",
                "citation": f"Citation {provider_id}",
            },
        )
        _registry.register(provider_id, artifact, engine_provider_module=provider_stages)
    yield _RegisteredRecorders(ca_eccc=stages["ca_eccc"], usgs_nwis=stages["usgs_nwis"])


def _record_provider_lookups(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    provider_lookups: list[str] = []
    original_lookup = discovery._provider_lookup

    def lookup(provider_id: str):
        provider_lookups.append(provider_id)
        return original_lookup(provider_id)

    monkeypatch.setattr(discovery, "_provider_lookup", lookup)
    return provider_lookups


def _keys(selection: object) -> tuple[tuple[str, str, str], ...]:
    return tuple((series.provider_id, series.station_id, series.product_id) for series in selection.series)


def test_fetch_rejects_proven_empty_scope_before_lookup_or_fetch(
    monkeypatch: pytest.MonkeyPatch,
    recording_stages: _RegisteredRecorders,
) -> None:
    provider_lookups = _record_provider_lookups(monkeypatch)
    selected = rr.find(provider="usgs_nwis", station="station-1", variant="level")
    empty = rr.pick(selected, station="station-2", on_issue="ignore")
    with pytest.raises(discovery.EmptySelectionError) as raised:
        rr.fetch(empty, start="2026-01-01", end="2026-01-01")
    assert raised.value.reason is empty.empty_reason
    assert empty.empty_reason.code == "no_match"
    assert provider_lookups == []
    assert recording_stages.ca_eccc.calls == recording_stages.usgs_nwis.calls == []
    assert rr.fetch_by_provider(empty, start="2026-01-01", end="2026-01-01", on_issue="ignore") == {}


def test_fetch_rejects_mixed_provider_selection_before_lookup_or_fetch(
    monkeypatch: pytest.MonkeyPatch,
    recording_stages: _RegisteredRecorders,
) -> None:
    provider_lookups = _record_provider_lookups(monkeypatch)
    mixed = rr.find(variant="level")
    assert _keys(mixed) == (
        ("ca_eccc", "station-1", "level"),
        ("usgs_nwis", "station-1", "level"),
    )

    with pytest.raises(discovery.MultiProviderSelectionError) as raised:
        rr.fetch(mixed, start="2026-01-01", end="2026-01-01")

    assert raised.value.provider_ids == ("ca_eccc", "usgs_nwis")
    assert str(raised.value) == (
        "fetch() requires one provider; selection contains providers "
        "('ca_eccc', 'usgs_nwis'). Use fetch_by_provider() for multi-provider selections."
    )
    assert provider_lookups == []
    assert recording_stages.ca_eccc.calls == []
    assert recording_stages.usgs_nwis.calls == []


def test_fetch_routes_only_selected_sparse_series(recording_stages: _RegisteredRecorders) -> None:
    sparse = rr.pick(
        rr.find(provider="usgs_nwis"),
        station=["station-1", "station-2"],
        variant=["level", "level_hourly"],
    )
    assert _keys(sparse) == (
        ("usgs_nwis", "station-1", "level"),
        ("usgs_nwis", "station-2", "level_hourly"),
    )

    result = rr.fetch(sparse, start="2026-01-01", end="2026-01-01")

    assert recording_stages.usgs_nwis.calls == [
        (("station-1",), ("level",)),
        (("station-2",), ("level_hourly",)),
    ]
    expected = _expected_frame(
        {
            "time": [datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 12, 0)],
            "time_zone": ["+00:00", "+00:00"],
            "station_id": ["station-1", "station-2"],
            "product_id": ["level", "level_hourly"],
            "value": [30.0, 40.0],
        },
        provider_id="usgs_nwis",
    )
    pl_testing.assert_frame_equal(result.data, expected, check_exact=True)
    assert result.provenance.source == "recording://usgs_nwis"
    assert result.provenance.provider_id == ProviderId("usgs_nwis")
    assert result.provenance.catalogue_version == "2026.01"
    acquisition = result.provenance.acquisition_provenance
    assert acquisition is not None
    expected_terms = {
        statement.kind: statement.exact_text
        for source in acquisition.header.source_records
        for statement in source.statements
    }
    assert result.provenance.license == expected_terms["license"]
    assert result.provenance.citation == expected_terms["citation"]
    assert result.provenance.request == {
        "scope": result.scope.model_dump(mode="json"),
        "series": [
            {
                "station_id": "station-1",
                "product_id": "level",
                "series_id": _test_definition("usgs_nwis", "station-1", "level").series_id,
            },
            {
                "station_id": "station-2",
                "product_id": "level_hourly",
                "series_id": _test_definition("usgs_nwis", "station-2", "level_hourly").series_id,
            },
        ],
        "start": "2026-01-01T00:00:00",
        "end": "2026-01-01T23:59:59.999999",
    }
    assert result.issues == ()
    assert result.receipts == Receipts(provider_id=ProviderId("usgs_nwis"), entries=())
    assert {"data", "provenance", "issues", "receipts", "source_series", "scope", "inventories", "outcomes"}.issubset(
        type(result).model_fields
    )


def test_fetch_by_provider_returns_one_singular_result_per_provider(
    recording_stages: _RegisteredRecorders,
) -> None:
    results = rr.fetch_by_provider(
        rr.find(variant="level"),
        start="2026-01-01",
        end="2026-01-01",
    )
    assert tuple(results) == ("ca_eccc", "usgs_nwis")
    assert recording_stages.ca_eccc.calls == [(("station-1",), ("level",))]
    assert recording_stages.usgs_nwis.calls == [(("station-1",), ("level",))]
    expected_by_provider = {
        "ca_eccc": _expected_frame(
            {
                "time": [datetime(2026, 1, 1, 12, 0)],
                "time_zone": ["+00:00"],
                "station_id": ["station-1"],
                "product_id": ["level"],
                "value": [10.0],
            },
            provider_id="ca_eccc",
        ),
        "usgs_nwis": _expected_frame(
            {
                "time": [datetime(2026, 1, 1, 12, 0)],
                "time_zone": ["+00:00"],
                "station_id": ["station-1"],
                "product_id": ["level"],
                "value": [30.0],
            },
            provider_id="usgs_nwis",
        ),
    }
    for provider_id, result in results.items():
        pl_testing.assert_frame_equal(result.data, expected_by_provider[provider_id], check_exact=True)
        assert result.provenance.source == f"recording://{provider_id}"
        assert result.provenance.provider_id == ProviderId(provider_id)
        assert result.provenance.catalogue_version == "2026.01"
        acquisition = result.provenance.acquisition_provenance
        assert acquisition is not None
        expected_terms = {
            statement.kind: statement.exact_text
            for source in acquisition.header.source_records
            for statement in source.statements
        }
        assert result.provenance.license == expected_terms["license"]
        assert result.provenance.citation == expected_terms["citation"]
        assert result.provenance.request == {
            "scope": result.scope.model_dump(mode="json"),
            "series": [
                {
                    "station_id": "station-1",
                    "product_id": "level",
                    "series_id": _test_definition(provider_id, "station-1", "level").series_id,
                }
            ],
            "start": "2026-01-01T00:00:00",
            "end": "2026-01-01T23:59:59.999999",
        }
        assert result.issues == ()
        assert result.receipts == Receipts(provider_id=ProviderId(provider_id), entries=())
        assert {
            "data",
            "provenance",
            "issues",
            "receipts",
            "source_series",
            "scope",
            "inventories",
            "outcomes",
        }.issubset(type(result).model_fields)
        assert result.data.columns == ObservationDataSchema.polars_schema.names()
        assert "provider_id" not in result.data.columns


def test_fetch_receipts_true_retains_every_selected_series_parse_input_and_origin(
    recording_stages: _RegisteredRecorders,
) -> None:
    sparse = rr.pick(
        rr.find(provider="usgs_nwis"),
        station=["station-1", "station-2"],
        variant=["level", "level_hourly"],
    )

    result = rr.fetch(sparse, start="2026-01-01", end="2026-01-01", receipts=True)

    assert result.receipts.provider_id == ProviderId("usgs_nwis")
    assert tuple(entry.content for entry in result.receipts.entries) == (
        b"usgs_nwis|station-1|level",
        b"usgs_nwis|station-2|level_hourly",
    )
    assert tuple(entry.origin for entry in result.receipts.entries) == (
        SourceCallOrigin(
            url="https://data.test/usgs_nwis/station-1/level",
            request_parameters={"station_id": "station-1", "product_id": "level"},
            status_code=200,
            retrieved_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            content_type="application/octet-stream",
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        ),
        SourceCallOrigin(
            url="https://data.test/usgs_nwis/station-2/level_hourly",
            request_parameters={"station_id": "station-2", "product_id": "level_hourly"},
            status_code=200,
            retrieved_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            content_type="application/octet-stream",
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        ),
    )
    assert recording_stages.usgs_nwis.calls == [
        (("station-1",), ("level",)),
        (("station-2",), ("level_hourly",)),
    ]


def test_fetch_by_provider_receipts_true_retains_provider_scoped_parse_inputs_and_origins(
    recording_stages: _RegisteredRecorders,
) -> None:
    results = rr.fetch_by_provider(
        rr.find(variant="level"),
        start="2026-01-01",
        end="2026-01-01",
        receipts=True,
    )

    assert tuple(results) == ("ca_eccc", "usgs_nwis")
    assert {
        provider_id: tuple(entry.content for entry in result.receipts.entries)
        for provider_id, result in results.items()
    } == {
        "ca_eccc": (b"ca_eccc|station-1|level",),
        "usgs_nwis": (b"usgs_nwis|station-1|level",),
    }
    assert {
        provider_id: tuple(entry.origin for entry in result.receipts.entries) for provider_id, result in results.items()
    } == {
        "ca_eccc": (
            SourceCallOrigin(
                url="https://data.test/ca_eccc/station-1/level",
                request_parameters={"station_id": "station-1", "product_id": "level"},
                status_code=200,
                retrieved_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                content_type="application/octet-stream",
                source_path=UnknownOriginFact(),
                query=UnknownOriginFact(),
            ),
        ),
        "usgs_nwis": (
            SourceCallOrigin(
                url="https://data.test/usgs_nwis/station-1/level",
                request_parameters={"station_id": "station-1", "product_id": "level"},
                status_code=200,
                retrieved_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                content_type="application/octet-stream",
                source_path=UnknownOriginFact(),
                query=UnknownOriginFact(),
            ),
        ),
    }
    assert all(result.receipts.provider_id == ProviderId(provider_id) for provider_id, result in results.items())


def test_fetch_default_warns_once_per_actionable_merged_issue(
    recording_stages: _RegisteredRecorders,
) -> None:
    sparse = rr.pick(
        rr.find(provider="usgs_nwis"),
        station=["station-1", "station-2"],
        variant=["level", "level_hourly"],
    )
    first_issue = Issue(
        severity="warning",
        code="station_1_provisional",
        message="station-1 level is provisional",
        details={"station_id": "station-1", "product_id": "level"},
        provider_id=ProviderId("usgs_nwis"),
    )
    second_issue = Issue(
        severity="error",
        code="station_2_partial",
        message="station-2 level_hourly is partial",
        details={"station_id": "station-2", "product_id": "level_hourly"},
        provider_id=ProviderId("usgs_nwis"),
    )
    recording_stages.usgs_nwis.issues_by_series = {
        ("station-1", "level"): (first_issue,),
        ("station-2", "level_hourly"): (second_issue,),
    }

    with pytest.warns(RuntimeWarning) as captured_warnings:
        result = rr.fetch(sparse, start="2026-01-01", end="2026-01-01")

    assert [str(warning.message) for warning in captured_warnings] == [
        "station-1 level is provisional",
        "station-2 level_hourly is partial",
    ]
    assert result.issues == (first_issue, second_issue)


def test_fetch_on_issue_ignore_returns_all_merged_issues_without_warnings(
    recording_stages: _RegisteredRecorders,
) -> None:
    sparse = rr.pick(
        rr.find(provider="usgs_nwis"),
        station=["station-1", "station-2"],
        variant=["level", "level_hourly"],
    )
    first_issue = Issue(
        severity="warning",
        code="station_1_provisional",
        message="station-1 level is provisional",
        details={"station_id": "station-1", "product_id": "level"},
        provider_id=ProviderId("usgs_nwis"),
    )
    second_issue = Issue(
        severity="error",
        code="station_2_partial",
        message="station-2 level_hourly is partial",
        details={"station_id": "station-2", "product_id": "level_hourly"},
        provider_id=ProviderId("usgs_nwis"),
    )
    recording_stages.usgs_nwis.issues_by_series = {
        ("station-1", "level"): (first_issue,),
        ("station-2", "level_hourly"): (second_issue,),
    }

    with warnings.catch_warnings(record=True) as captured_warnings:
        result = rr.fetch(
            sparse,
            start="2026-01-01",
            end="2026-01-01",
            on_issue="ignore",
        )

    assert captured_warnings == []
    assert result.issues == (first_issue, second_issue)


def test_fetch_on_issue_raise_fetches_all_series_then_raises_for_merged_issues(
    recording_stages: _RegisteredRecorders,
) -> None:
    sparse = rr.pick(
        rr.find(provider="usgs_nwis"),
        station=["station-1", "station-2"],
        variant=["level", "level_hourly"],
    )
    first_issue = Issue(
        severity="warning",
        code="station_1_provisional",
        message="station-1 level is provisional",
        details={"station_id": "station-1", "product_id": "level"},
        provider_id=ProviderId("usgs_nwis"),
    )
    second_issue = Issue(
        severity="error",
        code="station_2_partial",
        message="station-2 level_hourly is partial",
        details={"station_id": "station-2", "product_id": "level_hourly"},
        provider_id=ProviderId("usgs_nwis"),
    )
    recording_stages.usgs_nwis.issues_by_series = {
        ("station-1", "level"): (first_issue,),
        ("station-2", "level_hourly"): (second_issue,),
    }

    with pytest.raises(
        IssuePolicyError,
        match="^Recoverable issue policy requested an exception$",
    ) as raised:
        rr.fetch(
            sparse,
            start="2026-01-01",
            end="2026-01-01",
            on_issue="raise",
        )

    assert raised.value.issues == (first_issue, second_issue)
    assert recording_stages.usgs_nwis.calls == [
        (("station-1",), ("level",)),
        (("station-2",), ("level_hourly",)),
    ]


def test_fetch_by_provider_applies_issue_policy_once_to_each_completed_provider_result(
    recording_stages: _RegisteredRecorders,
) -> None:
    first_issue = Issue(
        severity="warning",
        code="ca_eccc_provisional",
        message="ca_eccc station-1 level is provisional",
        details={"station_id": "station-1", "product_id": "level"},
        provider_id=ProviderId("ca_eccc"),
    )
    second_issue = Issue(
        severity="error",
        code="usgs_nwis_partial",
        message="usgs_nwis station-1 level is partial",
        details={"station_id": "station-1", "product_id": "level"},
        provider_id=ProviderId("usgs_nwis"),
    )
    recording_stages.ca_eccc.issues_by_series = {
        ("station-1", "level"): (first_issue,),
    }
    recording_stages.usgs_nwis.issues_by_series = {
        ("station-1", "level"): (second_issue,),
    }

    with warnings.catch_warnings(record=True) as captured_warnings:
        results = rr.fetch_by_provider(
            rr.find(variant="level"),
            start="2026-01-01",
            end="2026-01-01",
            on_issue="ignore",
        )

    assert captured_warnings == []
    assert tuple(results) == ("ca_eccc", "usgs_nwis")
    assert results["ca_eccc"].issues == (first_issue,)
    assert results["usgs_nwis"].issues == (second_issue,)


def test_fetch_functions_require_rivretrieve_selection_and_expose_request_controls(
    monkeypatch: pytest.MonkeyPatch,
    recording_stages: _RegisteredRecorders,
) -> None:
    del recording_stages
    provider_lookups = _record_provider_lookups(monkeypatch)
    for function in (rr.fetch, rr.fetch_by_provider):
        with pytest.raises(TypeError, match="^selection must be a RivRetrieve selection$"):
            function(object(), start="2026-01-01", end="2026-01-01")
        signature = inspect.signature(function)
        assert tuple(signature.parameters) == ("selection", "start", "end", "receipts", "cache", "on_issue")
        assert signature.parameters["selection"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert signature.parameters["selection"].default is inspect.Parameter.empty
        for name in ("start", "end"):
            assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
            assert signature.parameters[name].default is None
        assert signature.parameters["receipts"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["receipts"].default is False
        assert signature.parameters["cache"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["cache"].default == "bypass"
        assert signature.parameters["on_issue"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["on_issue"].default == "warn"
        assert inspect.get_annotations(function, eval_str=False) == {
            "selection": "_Selection",
            "start": "object",
            "end": "object",
            "receipts": "bool",
            "cache": "CacheMode",
            "on_issue": "OnIssue",
            "return": ("ObservationResult" if function is rr.fetch else "dict[str, ObservationResult]"),
        }
    assert provider_lookups == []


def test_fetch_refuses_zone_carrying_endpoint_before_stage_fetch(
    recording_stages: _RegisteredRecorders,
) -> None:
    selection = rr.find(provider="usgs_nwis", station="station-1", variant="level")

    with pytest.raises(InvalidObservationRequestError) as raised:
        rr.fetch(
            selection,
            start="2026-01-01T00:00:00+00:00",
            end="2026-01-01",
        )

    assert str(raised.value) == (
        "start must be wall-clock time without a time zone; remove it with "
        "`start = datetime.fromisoformat(start).replace(tzinfo=None)`."
    )
    assert recording_stages.usgs_nwis.calls == []


@pytest.mark.parametrize("provider_order", ["time-major", "product-major"])
def test_shared_observation_order_is_identical_across_provider_parse_orders(provider_order: str) -> None:
    rows = [
        {"station_id": "b", "product_id": "stage", "time": datetime(2026, 1, 2), "value": 2.0, "time_zone": "unknown"},
        {"station_id": "a", "product_id": "stage", "time": datetime(2026, 1, 2), "value": 3.0, "time_zone": "unknown"},
        {"station_id": "a", "product_id": "flow", "time": datetime(2026, 1, 2), "value": 4.0, "time_zone": "unknown"},
        {"station_id": "a", "product_id": "flow", "time": datetime(2026, 1, 1), "value": 1.0, "time_zone": "unknown"},
    ]
    if provider_order == "time-major":
        rows.sort(key=lambda row: (row["time"], row["product_id"], row["station_id"]))
    else:
        rows.sort(key=lambda row: (row["product_id"], row["station_id"], row["time"]))
    frame = _expected_frame(rows, provider_id="usgs_nwis")

    ordered = discovery._canonical_observation_order(frame)

    assert ordered.select("station_id", "product_id", "time").rows() == [
        ("a", "flow", datetime(2026, 1, 1)),
        ("a", "flow", datetime(2026, 1, 2)),
        ("a", "stage", datetime(2026, 1, 2)),
        ("b", "stage", datetime(2026, 1, 2)),
    ]


def test_fetch_defaults_end_to_the_callers_local_calendar_day(
    recording_stages: _RegisteredRecorders,
) -> None:
    selection = rr.find(provider="usgs_nwis", station="station-1", variant="level")

    result = rr.fetch(selection, start="2026-01-01", on_issue="ignore")

    local_day_end = datetime.combine(date.today(), time.max)
    assert result.provenance.request is not None
    assert result.provenance.request["end"] == local_day_end.isoformat()
    assert (
        recording_stages.usgs_nwis.fetch_windows[0].end.isoformat() == (local_day_end + timedelta(days=2)).isoformat()
    )


def test_fetch_without_start_raises_the_domain_error_before_fetch(
    recording_stages: _RegisteredRecorders,
) -> None:
    selection = rr.find(provider="usgs_nwis", station="station-1", variant="level")

    with pytest.raises(InvalidObservationRequestError, match="start is required"):
        rr.fetch(selection, end="2026-01-01")

    assert recording_stages.usgs_nwis.calls == []


def test_providers_declares_credentials_without_exposing_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "secret-sentinel")
    monkeypatch.delenv("ANA_IDENTIFICADOR", raising=False)
    monkeypatch.delenv("ANA_SENHA", raising=False)

    result = rr.providers()

    assert isinstance(result, pl.DataFrame)
    assert result.columns == ["provider_id", "credentials", "access"]
    no_nve = result.filter(pl.col("provider_id") == "no_nve").row(0, named=True)
    assert no_nve == {"provider_id": "no_nve", "credentials": ["NVE_API_KEY"], "access": "ready"}
    br_ana = result.filter(pl.col("provider_id") == "br_ana").row(0, named=True)
    assert br_ana == {
        "provider_id": "br_ana",
        "credentials": ["ANA_IDENTIFICADOR", "ANA_SENHA"],
        "access": "missing ANA_IDENTIFICADOR, ANA_SENHA",
    }
    assert "secret-sentinel" not in str(result)


def test_future_end_is_preserved_with_one_info_issue(
    recording_stages: _RegisteredRecorders,
) -> None:
    selection = rr.find(provider="usgs_nwis", station="station-1", variant="level")
    future = date.today() + timedelta(days=365)

    result = rr.fetch(
        selection,
        start="2026-01-01",
        end=future.isoformat(),
        on_issue="raise",
    )

    assert result.provenance.request is not None
    assert result.provenance.request["end"] == datetime.combine(future, time.max).isoformat()
    future_issues = tuple(issue for issue in result.issues if issue.code == "request.future_end")
    assert len(future_issues) == 1
    details = future_issues[0].details
    assert details is not None
    assert details["requested_end"] == datetime.combine(future, time.max).isoformat()
    assert date.today().isoformat() in future_issues[0].message


def test_fetch_by_provider_on_issue_raise_attempts_every_series_and_carries_all_issues(
    recording_stages: _RegisteredRecorders,
) -> None:
    ca_issue = Issue(
        severity="error",
        code="ca_failed",
        message="ca failed",
        provider_id=ProviderId("ca_eccc"),
    )
    us_issue = Issue(
        severity="warning",
        code="us_missing",
        message="us missing",
        provider_id=ProviderId("usgs_nwis"),
    )
    recording_stages.ca_eccc.issues_by_series[("station-1", "level")] = (ca_issue,)
    recording_stages.usgs_nwis.issues_by_series[("station-1", "level")] = (us_issue,)

    with pytest.raises(IssuePolicyError) as raised:
        rr.fetch_by_provider(
            rr.find(variant="level"),
            start="2026-01-01",
            end="2026-01-01",
            on_issue="raise",
        )

    assert raised.value.issues == (ca_issue, us_issue)
    assert recording_stages.ca_eccc.calls == [(("station-1",), ("level",))]
    assert recording_stages.usgs_nwis.calls == [(("station-1",), ("level",))]
