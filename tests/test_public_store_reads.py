"""Public local reads share preparation without widening station routes."""

from collections import Counter
from dataclasses import replace
from datetime import datetime

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.engine import (
    CacheConfig,
    Instant,
    ObservationStoreConfig,
    Payload,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    RowsSchema,
    SourceCoordinates,
    Unit,
    WindowEndpoint,
    WithIssues,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.registry import _registry
from rivretrieve._internal.selection import _Selection
from rivretrieve._internal.source_series import SeriesScope
from rivretrieve._internal.store import StoreReader, StoreRoot, integrity
from tests.store.test_reader_refusal import _published
from tests.test_internal_registry import _EngineModule, _origin, _parsed


def _selection(provider, definitions):
    return _Selection(
        scope=SeriesScope(provider_ids=(provider,)),
        known_series=tuple(definitions),
    )


def _read_work(monkeypatch, store):
    """Count actual metadata inspection and observation-byte digest work separately."""
    inspected, digested = [], []
    inspect = integrity.inspect_integrity
    digest = integrity._digest

    def counted_inspect(root, provider, **kwargs):
        result = inspect(root, provider, **kwargs)
        if root == store:
            inspected.append(result.generation_id)
        return result

    def counted_digest(path):
        if path.is_relative_to(store) and path.suffix == ".parquet":
            digested.append(path.relative_to(store).as_posix())
        return digest(path)

    monkeypatch.setattr(integrity, "inspect_integrity", counted_inspect)
    monkeypatch.setattr(integrity, "_digest", counted_digest)
    return inspected, digested


@pytest.fixture
def bulk_store(tmp_path, monkeypatch, stub_packaged_catalogue_artifact):
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    provider = "fixture_bulk"
    published = _published(tmp_path / provider)
    store = StoreRoot(published.rename(tmp_path / provider / "store"))
    config = ProviderConfig(
        zone=ZoneValue("unknown"),
        products={
            ProductId("discharge"): ProductConfig(SourceCoordinates({}), Unit.M3_S, Instant()),
            ProductId("level"): ProductConfig(SourceCoordinates({}), Unit.M, Instant()),
        },
        cache=CacheConfig(ObservationStoreConfig(format_version=5)),
    )
    _registry.register(
        provider, stub_packaged_catalogue_artifact(provider), bulk_config=config, observation_store=store
    )
    manifest = StoreReader().status(store, ProviderId(provider)).manifest
    return _selection(provider, manifest.series), store


def test_public_bulk_stations_share_metadata_and_candidate_hashes(bulk_store, monkeypatch):
    selected, store = bulk_store
    inspected, digested = _read_work(monkeypatch, store)
    expected_hashes = Counter(
        {
            "product=discharge/year=2023/data.parquet": 1,
            "product=discharge/year=2024/data.parquet": 1,
            "product=level/year=2024/data.parquet": 1,
        }
    )
    for _ in range(2):
        inspected.clear()
        digested.clear()
        result = rr.fetch(selected, start="2024-01-01", end="2024-01-01", cache="reuse", on_issue="raise")
        expected = pl.DataFrame(
            {
                "station_id": ["ca-001", "ca-001", "ca-002"],
                "product_id": ["discharge", "level", "discharge"],
                "value": [None, 1.25, None],
            },
            schema={"station_id": pl.String, "product_id": pl.String, "value": pl.Float64},
        )
        pt.assert_frame_equal(result.data.select(expected.columns).sort("station_id", "product_id"), expected)
        assert len(inspected) == 1
        assert Counter(digested) == expected_hashes


@pytest.fixture
def live_routes(tmp_path, monkeypatch, stub_packaged_catalogue_artifact):
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    provider = "fixture_live"

    class Source:
        observation_source = "authored response"
        config = replace(
            _EngineModule.config,
            products={
                ProductId(name): _EngineModule.config.products[ProductId("level")] for name in ("level", "level_hourly")
            },
        )
        window_declarations = ProductWindowDeclarations(
            {
                ProductId(name): _EngineModule.window_declarations.products[ProductId("level")]
                for name in ("level", "level_hourly")
            }
        )

        def __init__(self):
            self.calls = []
            self.value = 1.0

        def fetch(self, stations, products, rendered_windows, fetch_window, config, transport, *, scope, known_series):
            self.calls.append((stations, products, fetch_window))
            return WithIssues(
                (
                    Payload(
                        source_coordinates=SourceCoordinates({}),
                        station_products=((stations[0], products[0]),),
                        fetch_window=fetch_window,
                        content=b"authored",
                        origin=_origin(),
                        prerequisite_calls=(),
                    ),
                )
            )

        def parse(self, payload, config):
            station, product = payload.station_products[0]
            rows = pl.DataFrame(
                {
                    "station_id": [station],
                    "product_id": [product],
                    "time": [datetime(2026, 1, 2)],
                    "value": [self.value],
                    "time_zone": ["+00:00"],
                    "series_id": [f"{station}:{product}"],
                    "facts_id": [f"{station}:{product}:facts"],
                    "source_unit": ["m"],
                },
                schema=RowsSchema.polars_schema,
            )
            return _parsed(rows, payload, config)

    source = Source()
    _registry.register(provider, stub_packaged_catalogue_artifact(provider), engine_provider_module=source)
    # Reuse the existing response-definition fixture for an authored selection.
    payload = Payload(
        source_coordinates=SourceCoordinates({}),
        station_products=(
            ("station-1", ProductId("level")),
            ("station-1", ProductId("level_hourly")),
            ("station-2", ProductId("level")),
        ),
        fetch_window=_make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2026, 1, 1)), WindowEndpoint.from_datetime(datetime(2026, 1, 4))
        ),
        content=b"authored",
        origin=_origin(),
        prerequisite_calls=(),
        scope=SeriesScope(provider_ids=(provider,)),
    )
    definitions = _parsed(pl.DataFrame(schema=RowsSchema.polars_schema), payload, source.config).series
    return source, _selection(provider, definitions), StoreRoot(tmp_path / provider / "store")


def test_public_live_stations_and_routes_share_preparation(live_routes, monkeypatch):
    import json

    from rivretrieve._internal.source_series import CatalogueSeriesClaim, InventoryCompleteness, InventorySnapshot

    source, selected, store = live_routes
    catalogue = InventorySnapshot(
        snapshot_id="authored-catalogue",
        scope=selected.scope,
        members=(),
        catalogue_claims=tuple(
            CatalogueSeriesClaim(
                provider_id=definition.provider_id,
                station_id=definition.station_id,
                product_id=definition.product_id,
                identity=definition.identity.model_copy(update={"origin": "catalogue"}),
            )
            for definition in selected.known_series
        ),
        completeness=InventoryCompleteness.INCOMPLETE,
        reason="Catalogue listings do not establish exhaustive response membership",
        access="authored packaged catalogue",
        origin="catalogue",
        evidence=("authored catalogue source",),
    )
    selected = replace(selected, inventories=(catalogue,))
    fresh = rr.fetch(selected, start="2026-01-01", end="2026-01-04", cache="refresh", on_issue="raise")
    assert [(stations, products) for stations, products, _ in source.calls] == [
        (("station-1",), ("level",)),
        (("station-1",), ("level_hourly",)),
        (("station-2",), ("level",)),
    ]
    source.calls.clear()
    generation = json.loads((store / "integrity.json").read_text())["generation_id"]
    inspected, digested = _read_work(monkeypatch, store)
    for _ in range(2):
        inspected.clear()
        digested.clear()
        held = rr.fetch(selected, start="2026-01-01", end="2026-01-04", cache="reuse", on_issue="raise")
        pt.assert_frame_equal(held.data, fresh.data)
        assert source.calls == []
        assert catalogue in held.inventories
        assert json.loads((store / "integrity.json").read_text())["generation_id"] == generation
        assert len(inspected) == 1
        assert Counter(digested) == Counter(
            {
                "product=level/year=2026/rows.parquet": 1,
                "product=level_hourly/year=2026/rows.parquet": 1,
            }
        )


def test_public_live_write_invalidates_before_next_station_read(live_routes, monkeypatch):
    source, selected, store = live_routes
    # Both stations' level routes are covered. Only station-1's hourly route
    # needs an extended acquisition; station-2 has no selected hourly route.
    levels = _selection("fixture_live", (item for item in selected.known_series if item.product_id == "level"))
    hourly = _selection("fixture_live", (item for item in selected.known_series if item.product_id == "level_hourly"))
    rr.fetch(levels, start="2026-01-01", end="2026-01-04", cache="refresh", on_issue="raise")
    rr.fetch(hourly, start="2026-01-01", end="2026-01-02", cache="refresh", on_issue="raise")
    before = StoreReader().status(store, ProviderId("fixture_live"))
    source.calls.clear()
    source.value = 2.0
    reads = []
    original_query = StoreReader.query

    def recorded_query(reader, query):
        result = original_query(reader, query)
        reads.append((query.stations, result.manifest.built_at))
        return result

    monkeypatch.setattr(StoreReader, "query", recorded_query)
    result = rr.fetch(selected, start="2026-01-01", end="2026-01-04", cache="reuse", on_issue="raise")
    after = StoreReader().status(store, ProviderId("fixture_live"))
    assert before.generation_id != after.generation_id
    assert reads == [(("station-1",), before.manifest.built_at), (("station-2",), after.manifest.built_at)]
    assert len(source.calls) == 1
    stations, products, window = source.calls[0]
    assert (stations, products) == (("station-1",), ("level_hourly",))
    assert window.start.isoformat() == "2025-12-30T00:00:00"
    assert window.end.isoformat() == "2026-01-06T23:59:59.999999"
    expected = pl.DataFrame(
        {
            "station_id": ["station-1", "station-1", "station-2"],
            "product_id": ["level", "level_hourly", "level"],
            "value": [1.0, 2.0, 1.0],
        }
    )
    pt.assert_frame_equal(result.data.select(expected.columns).sort("station_id", "product_id"), expected)


def test_public_fact_reuse_keeps_original_acquisition_and_only_applicable_diagnostics(live_routes, monkeypatch):
    from rivretrieve._internal.issues import Issue
    from rivretrieve._internal.source_series import OutcomeStatus, known

    source, selected, store = live_routes
    original_parse = source.parse
    original = selected.known_series[0]
    mean = original.facts[0].model_copy(update={"statistic": known("mean", "authored fact")})
    maximum = mean.model_copy(update={"facts_id": mean.facts_id + ":max", "statistic": known("max", "authored fact")})
    definition = original.model_copy(update={"facts": (mean, maximum)})
    selected = _selection("fixture_live", (definition,))
    count_note = Issue(
        severity="info", code="source.note", message="Publisher acquisition-wide count", details={"count": 7}
    )

    def parse(payload, config):
        parsed = original_parse(payload, config)
        success = parsed.outcomes[0].model_copy(update={"outcome_id": "mean-acquisition"})
        failure = success.model_copy(
            update={
                "outcome_id": "max-acquisition",
                "facts_ids": (maximum.facts_id,),
                "status": OutcomeStatus.FAILED,
                "reason": "Maximum series request failed",
            }
        )
        issue = Issue(
            severity="error",
            code="source.request_failed",
            message=failure.reason,
            details={"outcome_id": failure.outcome_id, "facts_id": maximum.facts_id, "count": 11},
        )
        inventory = parsed.inventories[0].model_copy(
            update={
                "evidence": ("retrieval-outcome:mean-acquisition", "retrieval-outcome:max-acquisition"),
            }
        )
        return replace(
            parsed,
            series=(definition,),
            outcomes=(success, failure),
            inventories=(inventory,),
            issues=(issue, count_note),
        )

    monkeypatch.setattr(source, "parse", parse)
    rr.fetch(selected, start="2026-01-01", end="2026-01-04", cache="refresh", on_issue="ignore")
    stored = StoreReader().status(store, ProviderId("fixture_live")).manifest
    acquired = next(item for item in stored.outcomes if item.status is OutcomeStatus.SUCCESS)
    failed = next(item for item in stored.outcomes if item.status is OutcomeStatus.FAILED)
    source.calls.clear()
    precise = rr.pick(selected, series_id=definition.series_id, statistic="mean")
    result = rr.fetch(precise, start="2026-01-02", end="2026-01-02", cache="reuse", on_issue="raise")
    assert source.calls == []
    assert result.data["facts_id"].to_list() == [mean.facts_id]
    assert result.outcomes == (acquired,)
    assert result.outcomes[0].window.start == datetime(2026, 1, 1)
    assert result.outcomes[0].window.end == datetime(2026, 1, 4, 23, 59, 59, 999999)
    assert failed in result.supporting_outcomes
    assert count_note in result.issues
    assert not any(item.code == "source.request_failed" for item in result.issues)
    assert all(item in stored.inventories for item in result.inventories)


def test_public_compiled_empty_inventory_keeps_transitive_acquisition_support(bulk_store):
    import json

    from rivretrieve._internal.issues import Issue
    from rivretrieve._internal.source_series import (
        InventoryCompleteness,
        InventorySnapshot,
        OutcomeStatus,
        RetrievalOutcome,
        SeriesWindow,
    )

    selection, store = bulk_store
    placeholder = selection.known_series[0].model_copy(
        update={"series_id": "empty-route", "station_id": "empty-station"}
    )
    requested = _selection("fixture_bulk", (placeholder,))
    failed = RetrievalOutcome(
        outcome_id="historical-failure",
        series_id=None,
        station_id="empty-station",
        product_id="discharge",
        window=SeriesWindow(start=datetime(2024, 1, 1), end=datetime(2024, 1, 2)),
        status=OutcomeStatus.FAILED,
        reason="Historical census failed",
        calls=("historical-call",),
    )
    old = InventorySnapshot(
        snapshot_id="original-census",
        scope=SeriesScope(provider_ids=("fixture_bulk",), station_ids=("empty-station",), product_ids=("discharge",)),
        members=(),
        completeness=InventoryCompleteness.INCOMPLETE,
        reason="Historical census failed",
        access="authored compiled source",
        origin="compiled",
        evidence=("retrieval-outcome:historical-failure",),
    )
    empty = old.model_copy(
        update={
            "snapshot_id": "complete-empty",
            "completeness": InventoryCompleteness.COMPLETE,
            "reason": None,
            "evidence": ("source-inventory:original-census", "source-call:empty-census-call"),
        }
    )
    issue = Issue(
        severity="error", code="source.request_failed", message=failed.reason, details={"outcome_id": failed.outcome_id}
    )
    manifest_path = store / "manifest.json"
    raw = json.loads(manifest_path.read_text())
    raw.update(
        inventories=[item.model_dump(mode="json") for item in (old, empty)],
        outcomes=[failed.model_dump(mode="json")],
        issues=[issue.model_dump(mode="json")],
        source_calls=[{"call_id": key} for key in ("historical-call", "empty-census-call", "unrelated-call")],
    )
    manifest_path.write_text(json.dumps(raw))
    integrity.seal_store(store, ProviderId("fixture_bulk"))
    result = rr.fetch(requested, start="2024-01-01", end="2024-01-01", cache="reuse", on_issue="ignore")
    assert result.data.is_empty()
    assert tuple(item.status for item in result.outcomes) == (OutcomeStatus.NO_MATCH,)
    assert result.inventories == (old, empty)
    assert result.supporting_outcomes == (failed,)
    assert result.provenance.calls_made == ({"call_id": "historical-call"}, {"call_id": "empty-census-call"})
    assert not any(item.code == "source.request_failed" for item in result.issues)
    assert any(item.code == "source.no_match" for item in result.issues)
