from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import datetime

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.engine import (
    FetchWindow,
    Instant,
    Payload,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    RenderedWindow,
    Rows,
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
from rivretrieve._internal.issues import InvalidObservationRequestError
from rivretrieve._internal.observations import ObservationDataSchema, RawPayload
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.registry import _registry

VALUES = {
    ("ca_eccc", "station-1", "level"): 10.0,
    ("ca_eccc", "station-2", "level_hourly"): 20.0,
    ("usgs_nwis", "station-1", "level"): 30.0,
    ("usgs_nwis", "station-2", "level_hourly"): 40.0,
}


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

    def fetch(
        self,
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
        fetch_window: FetchWindow,
        config: ProviderConfig,
    ) -> WithIssues[tuple[Payload, ...]]:
        del rendered_windows
        self.calls.append((stations, tuple(str(product) for product in products)))
        payload = Payload(
            source_coordinates=config.products[products[0]].coordinates,
            station_products=((stations[0], products[0]),),
            fetch_window=fetch_window,
            content=f"{self.provider_id}|{stations[0]}|{products[0]}".encode(),
            origin=SourceCallOrigin(
                UnknownOriginFact(),
                UnknownOriginFact(),
                UnknownOriginFact(),
                UnknownOriginFact(),
                UnknownOriginFact(),
                UnknownOriginFact(),
                UnknownOriginFact(),
            ),
        )
        return WithIssues(value=(payload,), issues=())

    @staticmethod
    def parse(payload: Payload, config: ProviderConfig) -> WithIssues[Rows]:
        del config
        parsed_provider_id, station_id, product_id = payload.content.decode().split("|")
        rows = pl.DataFrame(
            {
                "station_id": [station_id],
                "product_id": [product_id],
                "time": [datetime(2026, 1, 1, 12, 0)],
                "value": [VALUES[(parsed_provider_id, station_id, product_id)]],
                "time_zone": ["+00:00"],
            },
            schema=RowsSchema.polars_schema,
        )
        return WithIssues(value=rows, issues=())


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
        artifact = replace(
            artifact,
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


def test_fetch_rejects_reason_carrying_empty_selection_before_lookup_or_fetch(
    monkeypatch: pytest.MonkeyPatch,
    recording_stages: _RegisteredRecorders,
) -> None:
    provider_lookups = _record_provider_lookups(monkeypatch)
    empty = rr.find(provider="usgs_nwis", station="station-2", product="level_max")

    with pytest.raises(discovery.EmptySelectionError) as raised:
        rr.fetch(empty, start="2026-01-01", end="2026-01-01")

    assert raised.value.reason is empty.empty_reason
    assert str(raised.value) == (
        "fetch() cannot retrieve an empty selection: code='no_catalogue_edge', "
        "provider_ids=('usgs_nwis',), station_ids=('station-2',), "
        "product_ids=('level_max',), published_products=('level_hourly',)"
    )
    assert provider_lookups == []
    assert recording_stages.ca_eccc.calls == []
    assert recording_stages.usgs_nwis.calls == []
    assert rr.fetch_by_provider(empty, start="2026-01-01", end="2026-01-01") == {}
    assert provider_lookups == []
    assert recording_stages.ca_eccc.calls == []
    assert recording_stages.usgs_nwis.calls == []


def test_fetch_rejects_mixed_provider_selection_before_lookup_or_fetch(
    monkeypatch: pytest.MonkeyPatch,
    recording_stages: _RegisteredRecorders,
) -> None:
    provider_lookups = _record_provider_lookups(monkeypatch)
    mixed = rr.find(product="level")
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
        product=["level", "level_hourly"],
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
    expected = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 12, 0)],
            "time_zone": ["+00:00", "+00:00"],
            "station_id": ["station-1", "station-2"],
            "product_id": ["level", "level_hourly"],
            "value": [30.0, 40.0],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.data, expected, check_exact=True)
    assert result.provenance.source == "recording://usgs_nwis"
    assert result.provenance.provider_id == ProviderId("usgs_nwis")
    assert result.provenance.catalogue_version == "2026.01"
    assert result.provenance.license == "https://licenses.test/usgs_nwis"
    assert result.provenance.citation == "Citation usgs_nwis"
    assert result.provenance.request == {
        "series": [
            {"station_id": "station-1", "product_id": "level"},
            {"station_id": "station-2", "product_id": "level_hourly"},
        ],
        "start": "2026-01-01T00:00:00",
        "end": "2026-01-01T23:59:59.999999",
    }
    assert result.issues == ()
    assert result.raw == RawPayload(provider_id=ProviderId("usgs_nwis"), entries=())
    assert tuple(type(result).model_fields) == ("data", "provenance", "issues", "raw")


def test_fetch_by_provider_returns_one_singular_result_per_provider(
    recording_stages: _RegisteredRecorders,
) -> None:
    results = rr.fetch_by_provider(
        rr.find(product="level"),
        start="2026-01-01",
        end="2026-01-01",
    )
    assert tuple(results) == ("ca_eccc", "usgs_nwis")
    assert recording_stages.ca_eccc.calls == [(("station-1",), ("level",))]
    assert recording_stages.usgs_nwis.calls == [(("station-1",), ("level",))]
    expected_by_provider = {
        "ca_eccc": pl.DataFrame(
            {
                "time": [datetime(2026, 1, 1, 12, 0)],
                "time_zone": ["+00:00"],
                "station_id": ["station-1"],
                "product_id": ["level"],
                "value": [10.0],
            },
            schema=ObservationDataSchema.polars_schema,
        ),
        "usgs_nwis": pl.DataFrame(
            {
                "time": [datetime(2026, 1, 1, 12, 0)],
                "time_zone": ["+00:00"],
                "station_id": ["station-1"],
                "product_id": ["level"],
                "value": [30.0],
            },
            schema=ObservationDataSchema.polars_schema,
        ),
    }
    for provider_id, result in results.items():
        pl_testing.assert_frame_equal(result.data, expected_by_provider[provider_id], check_exact=True)
        assert result.provenance.source == f"recording://{provider_id}"
        assert result.provenance.provider_id == ProviderId(provider_id)
        assert result.provenance.catalogue_version == "2026.01"
        assert result.provenance.license == f"https://licenses.test/{provider_id}"
        assert result.provenance.citation == f"Citation {provider_id}"
        assert result.provenance.request == {
            "series": [{"station_id": "station-1", "product_id": "level"}],
            "start": "2026-01-01T00:00:00",
            "end": "2026-01-01T23:59:59.999999",
        }
        assert result.issues == ()
        assert result.raw == RawPayload(provider_id=ProviderId(provider_id), entries=())
        assert tuple(type(result).model_fields) == ("data", "provenance", "issues", "raw")
        assert tuple(result.data.columns) == (
            "time",
            "time_zone",
            "station_id",
            "product_id",
            "value",
        )
        assert "provider_id" not in result.data.columns


def test_fetch_functions_require_rivretrieve_selection_and_defer_request_controls(
    monkeypatch: pytest.MonkeyPatch,
    recording_stages: _RegisteredRecorders,
) -> None:
    del recording_stages
    provider_lookups = _record_provider_lookups(monkeypatch)
    for function in (rr.fetch, rr.fetch_by_provider):
        with pytest.raises(TypeError, match="^selection must be a RivRetrieve selection$"):
            function(object(), start="2026-01-01", end="2026-01-01")
        signature = inspect.signature(function)
        assert tuple(signature.parameters) == ("selection", "start", "end")
        assert signature.parameters["selection"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert signature.parameters["selection"].default is inspect.Parameter.empty
        for name in ("start", "end"):
            assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
            assert signature.parameters[name].default is inspect.Parameter.empty
        assert "raw" not in signature.parameters
        assert "on_issue" not in signature.parameters
    assert provider_lookups == []


def test_fetch_refuses_zone_carrying_endpoint_before_stage_fetch(
    recording_stages: _RegisteredRecorders,
) -> None:
    selection = rr.find(provider="usgs_nwis", station="station-1", product="level")

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
