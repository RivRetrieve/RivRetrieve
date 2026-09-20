"""Finite requested selectors cannot disappear behind a successful sibling."""

from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.recordings import ReplayTransport, read_recording


def _counted_replay(monkeypatch, recordings):
    replay = ReplayTransport(recordings)
    original = replay.send
    calls = []

    def send(request):
        calls.append(request)
        return original(request)

    monkeypatch.setattr(replay, "send", send)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    return calls


def test_offline_mixed_explicit_members_preserve_each_unresolved_selector():
    selected = rr.pick(
        rr.find(provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"),
        variant=("2", "unresolved-selector", "another-unresolved-selector"),
        on_issue="ignore",
    )
    unresolved = [item for item in selected.issues if item.code == "selection.unresolved_inventory"]
    assert {item.details["requested_selector"]["value"] for item in unresolved} == {
        "unresolved-selector",
        "another-unresolved-selector",
    }
    assert all(item.details["requested_selector"]["kind"] == "variant" for item in unresolved)


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_public_mixed_nve_member_is_not_silently_omitted(monkeypatch, tmp_path, policy):
    recording = read_recording(
        Path(__file__).parent / "test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    calls = _counted_replay(monkeypatch, (recording,))
    selected = rr.pick(
        rr.find(provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"),
        variant=("2", "unresolved-selector"),
        on_issue="ignore",
    )
    if policy == "raise":
        with pytest.raises(IssuePolicyError):
            rr.fetch(selected, start="2024-01-02", end="2024-01-02", on_issue=policy)
        assert len(calls) == 1
        assert dict(calls[0].params)["VersionNumber"] == 2
        return
    if policy == "warn":
        with pytest.warns(RuntimeWarning):
            result = rr.fetch(selected, start="2024-01-02", end="2024-01-02", on_issue=policy)
    else:
        result = rr.fetch(selected, start="2024-01-02", end="2024-01-02", on_issue=policy)
    assert len(calls) == 1
    assert dict(calls[0].params)["VersionNumber"] == 2
    assert result.data.height == 1
    unresolved = [item for item in result.outcomes if item.status.value == "unresolved"]
    assert unresolved, "The unmatched literal selector needs its own unresolved outcome"
    assert len(unresolved) == 1
    assert unresolved[0].requested_selector.value == "unresolved-selector"
    assert unresolved[0].series_id is None
    assert not unresolved[0].facts_ids
    assert not unresolved[0].calls
    assert unresolved[0].retrieved_at is None
    assert not any(item.variant == "unresolved-selector" for item in result.source_series)


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_narrowed_result_policy_ignores_excluded_failure_but_preserves_history(monkeypatch, tmp_path, policy):
    import warnings

    import polars.testing as pl_testing

    recordings = tuple(
        read_recording(
            Path(__file__).parent
            / f"test_data/no_nve_109.42.0_1001_1440_version-{version}_engine_2024-01-02.recording.json"
        )
        for version in (1, 99999)
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(recordings))
    selected = rr.pick(
        rr.find(provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily"),
        variant=("1", "99999"),
        on_issue="ignore",
    )
    result = rr.fetch(selected, start="2024-01-02", end="2024-01-02", receipts=True, on_issue="ignore")
    assert result.data.height == 1
    assert any(item.status.value == "failed" for item in result.outcomes)

    def forbidden(*args, **kwargs):
        raise AssertionError("Narrowing a returned result must not access the source")

    monkeypatch.setattr(ReplayTransport, "send", forbidden)
    monkeypatch.setattr(discovery, "HttpClient", forbidden)
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        narrowed = rr.pick(result, variant="1", on_issue=policy)
    assert not emitted
    pl_testing.assert_frame_equal(narrowed.data, result.data)
    assert narrowed.outcomes == result.outcomes
    assert narrowed.provenance == result.provenance
    assert narrowed.receipts == result.receipts
    assert all(item in narrowed.issues for item in result.issues)
    if policy == "raise":
        with pytest.raises(IssuePolicyError):
            rr.pick(result, variant="99999", on_issue=policy)
    elif policy == "warn":
        with pytest.warns(RuntimeWarning):
            rr.pick(result, variant="99999", on_issue=policy)
    else:
        failed_view = rr.pick(result, variant="99999", on_issue=policy)
        assert failed_view.data.is_empty()
        assert failed_view.outcomes == result.outcomes
    with pytest.raises(IssuePolicyError) as empty_error:
        rr.pick(result, series_id=[], on_issue="raise")
    assert [item.code for item in empty_error.value.issues] == ["selection.no_match"]


def test_public_mixed_missing_member_survives_inspection_bundle_and_narrowing(monkeypatch, tmp_path):
    import polars as pl
    import polars.testing as pl_testing

    recording = read_recording(
        Path(__file__).parent / "test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selected = rr.pick(
        rr.find(provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"),
        variant=("2", "unresolved-selector"),
        on_issue="ignore",
    )
    result = rr.fetch(selected, start="2024-01-02", end="2024-01-02", on_issue="ignore", receipts=True)
    inspected = rr.series(result)
    missing = inspected.filter(pl.col("requested_selector_value") == "unresolved-selector")
    assert missing.height == 1
    assert missing["requested_selector_kind"].item() == "variant"
    assert missing.select("series_id", "facts_id", "published_id").null_count().row(0) == (1, 1, 1)
    assert missing["outcomes"].item().to_list() == ["unresolved"]
    restored = rr.from_bundle(rr.to_bundle(result))
    assert restored.outcomes == result.outcomes
    assert restored.issues == result.issues
    assert restored.receipts == result.receipts
    pl_testing.assert_frame_equal(rr.series(restored), inspected)
    narrowed = rr.pick(restored, variant="2", on_issue="raise")
    assert narrowed.data.height == 1
    assert rr.series(narrowed).filter(pl.col("requested_selector_value") == "unresolved-selector").is_empty()
    assert narrowed.outcomes == result.outcomes
    assert narrowed.issues[: len(result.issues)] == result.issues


def test_complete_recorded_inventory_classifies_missing_member_without_fake_identity(monkeypatch, tmp_path):
    recording = read_recording(
        Path(__file__).parent / "test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selected = rr.pick(
        rr.find(provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"),
        variant=("61176", "not-published"),
        on_issue="ignore",
    )
    result = rr.fetch(selected, start="2023-01-01", end="2023-01-01", on_issue="ignore")
    assert result.data.height == 1
    missing = [
        item
        for item in result.outcomes
        if item.requested_selector is not None and item.requested_selector.value == "not-published"
    ]
    assert len(missing) == 1
    assert missing[0].status.value == "no_match"
    assert missing[0].series_id is None
    assert not missing[0].facts_ids
    assert not any(
        item.variant == "not-published" or item.identity.published_id == "not-published"
        for item in result.source_series
    )
    assert any(item.completeness.value == "complete" for item in result.inventories)
    assert rr.from_bundle(rr.to_bundle(result)).outcomes == result.outcomes
    missing_view = rr.pick(result, variant="not-published", on_issue="ignore")
    assert not any(item.code == "selection.unresolved_inventory" for item in missing_view.issues)


def test_global_series_ids_do_not_become_missing_in_other_access_coordinates(monkeypatch, tmp_path):
    recording = read_recording(Path(__file__).parent / "test_data/ch_foen_2251_rest_engine_2026-09-19.recording.json")
    monkeypatch.chdir(tmp_path)
    calls = _counted_replay(monkeypatch, (recording,))
    broad = rr.find(provider="ch_foen", station="2251")
    identities = tuple(item.series_id for item in broad.known_series if item.variant in ("flow_ls", "height_abs"))
    assert len(identities) == 2
    selected = rr.pick(broad, series_id=identities, on_issue="raise")
    result = rr.fetch(selected, start="2026-09-19T00:00:00", end="2026-09-19T03:00:00", on_issue="raise")
    assert len(calls) == 2
    assert set(result.data["series_id"]) == set(identities)
    assert result.data.height == 8
    assert not any(item.status.value in ("no_match", "unresolved") for item in result.outcomes)


def test_response_discovered_global_ids_are_settled_across_station_results(monkeypatch, tmp_path):
    """Controlled protocol bodies exercise real USGS parsing and public result composition.

    The second station response is authored test input, not publisher evidence.
    """
    import json

    from rivretrieve._internal.engine import Payload, SourceCallOrigin, UnknownOriginFact, WithIssues
    from rivretrieve._internal.providers.usgs_nwis.declaration import declaration

    recording = read_recording(
        Path(__file__).parent / "test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )
    calls = []

    def acquire(stations, products, rendered_windows, fetch_window, config, transport, *, scope=None, known_series=()):
        station, product = stations[0], products[0]
        calls.append((station, product))
        document = json.loads(recording.content)
        for series in document["value"]["timeSeries"]:
            series["sourceInfo"]["siteCode"][0]["value"] = station
            series["sourceInfo"]["siteName"] = "Controlled protocol fixture"
            series["sourceInfo"].pop("geoLocation", None)
            if "name" in series:
                series["name"] = series["name"].replace("07374000", station)
        unknown = UnknownOriginFact()
        return WithIssues(
            (
                Payload(
                    config.products[product].coordinates,
                    ((station, product),),
                    fetch_window,
                    json.dumps(document).encode(),
                    SourceCallOrigin(
                        "fixture://finite-selector-composition",
                        {"station": station},
                        unknown,
                        unknown,
                        unknown,
                        unknown,
                        unknown,
                    ),
                    (),
                    scope=scope,
                    known_series=known_series,
                ),
            )
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(declaration.observations.stages, "fetch", staticmethod(acquire))
    broad = rr.find(
        provider="usgs_nwis",
        station=("07374000", "01010000"),
        quantity="discharge",
        frequency="daily",
        statistic="mean",
    )
    discovered = rr.fetch(broad, start="2023-01-01", end="2023-01-01", on_issue="ignore")
    identifiers = tuple(discovered.data["series_id"].unique())
    assert len(identifiers) == 2
    assert set(identifiers).isdisjoint(item.series_id for item in broad.known_series)
    calls.clear()
    selected = rr.pick(broad, series_id=identifiers, on_issue="ignore")
    result = rr.fetch(selected, start="2023-01-01", end="2023-01-01", on_issue="raise")
    assert len(calls) == 2
    assert result.data.height == 2
    assert set(result.data["series_id"]) == set(identifiers)
    assert not any(item.requested_selector is not None for item in result.outcomes)


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_finite_view_does_not_report_original_all_inventory_uncertainty(monkeypatch, tmp_path, policy):
    import warnings

    recordings = tuple(
        read_recording(
            Path(__file__).parent
            / f"test_data/no_nve_109.42.0_1001_1440_version-{version}_engine_2024-01-02.recording.json"
        )
        for version in (1, 2, 3)
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    metadata = read_recording(Path(__file__).parent / "test_data/no_nve_109.42.0_1001_series.recording.json")
    calls = _counted_replay(monkeypatch, (*recordings, metadata))
    broad = rr.find(provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean")
    result = rr.fetch(broad, start="2024-01-02", end="2024-01-02", receipts=True, on_issue="ignore")
    assert [call.url.rsplit("/", 1)[-1] for call in calls] == ["Series", "Observations", "Observations", "Observations"]
    assert [call.params["VersionNumber"] for call in calls[1:]] == [1, 2, 3]
    request_count = len(calls)
    inventory_warning = next(item for item in result.issues if item.code == "source.inventory_unresolved")

    def forbidden(*args, **kwargs):
        raise AssertionError("A result view must not make a source request")

    monkeypatch.setattr(ReplayTransport, "send", forbidden)
    monkeypatch.setattr(discovery, "HttpClient", forbidden)
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        narrowed = rr.pick(result, variant="2", on_issue=policy)
    assert not emitted
    assert narrowed.data.height == 1
    assert narrowed.issues == result.issues
    assert narrowed.inventories == result.inventories
    assert narrowed.outcomes == result.outcomes
    assert narrowed.provenance == result.provenance
    assert narrowed.receipts == result.receipts
    restored = rr.from_bundle(rr.to_bundle(narrowed))
    assert restored.issues == result.issues
    assert restored.inventories == result.inventories
    assert restored.outcomes == result.outcomes
    with pytest.raises(IssuePolicyError):
        rr.pick(result, on_issue="raise")
    with pytest.warns(RuntimeWarning):
        rr.pick(result, on_issue="warn")
    with pytest.raises(IssuePolicyError) as unresolved:
        rr.pick(result, variant=("2", "not-established"), on_issue="raise")
    assert inventory_warning in unresolved.value.issues
    with pytest.warns(RuntimeWarning):
        rr.pick(result, variant=("2", "not-established"), on_issue="warn")
    assert len(calls) == request_count

    with warnings.catch_warnings(record=True) as positive_warnings:
        warnings.simplefilter("always")
        rr.pick(result, variant=("2", "3"), on_issue=policy)
        null_view = rr.pick(result, variant="1", on_issue=policy)
        assert null_view.data["value"].null_count() == 1
        rr.pick(result, series_id=tuple(narrowed.data["series_id"].unique()), on_issue=policy)
    assert not positive_warnings


def test_global_id_view_excludes_other_inventory_search_coordinates(monkeypatch, tmp_path):
    """Use real Swiss acquisition/parsing with authored ALL-inventory diagnostics."""
    import warnings

    from rivretrieve._internal.engine import WithIssues
    from rivretrieve._internal.issues import Issue
    from rivretrieve._internal.providers.ch_foen.declaration import declaration
    from rivretrieve._internal.source_series import SeriesScope

    recording = read_recording(Path(__file__).parent / "test_data/ch_foen_2251_rest_engine_2026-09-19.recording.json")
    calls = _counted_replay(monkeypatch, (recording,))
    original = declaration.observations.stages.fetch

    def acquire(stations, products, rendered_windows, fetch_window, config, transport, *, scope=None, known_series=()):
        acquired = original(
            stations,
            products,
            rendered_windows,
            fetch_window,
            config,
            transport,
            scope=scope,
            known_series=known_series,
        )
        diagnostics = tuple(
            Issue(
                severity="warning",
                code="source.inventory_unresolved",
                message="Controlled inventory-completeness diagnostic",
                details={
                    "station_id": station,
                    "product_id": product,
                    "inventory_scope": SeriesScope(
                        provider_ids=("ch_foen",), station_ids=(station,), product_ids=(product,)
                    ).model_dump(mode="json"),
                },
            )
            for station in stations
            for product in products
        )
        return WithIssues(acquired.value, (*acquired.issues, *diagnostics))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(declaration.observations.stages, "fetch", staticmethod(acquire))
    result = rr.fetch(
        rr.find(provider="ch_foen", station="2251"),
        start="2026-09-19T00:00:00",
        end="2026-09-19T03:00:00",
        on_issue="ignore",
    )
    target = next(item.series_id for item in result.source_series if item.variant == "height_abs")
    assert result.data["series_id"].n_unique() == 2
    count = len(calls)
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        narrowed = rr.pick(result, series_id=target, on_issue="raise")
    assert not emitted
    assert narrowed.data.height == 4
    assert narrowed.outcomes == result.outcomes
    assert narrowed.issues == result.issues
    rr.pick(result, series_id=tuple(result.data["series_id"].unique()), on_issue="raise")
    with pytest.raises(IssuePolicyError) as unresolved:
        rr.pick(result, series_id="unresolved-global-id", on_issue="raise")
    assert any(item.code == "source.inventory_unresolved" for item in unresolved.value.issues)
    assert len(calls) == count


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
@pytest.mark.parametrize("restriction", ["disjoint", "empty-list"])
def test_current_empty_result_view_diagnostics_follow_policy(monkeypatch, tmp_path, policy, restriction):
    recording = read_recording(
        Path(__file__).parent / "test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    calls = _counted_replay(monkeypatch, (recording,))
    selected = rr.pick(
        rr.find(provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"),
        variant="2",
        on_issue="raise",
    )
    result = rr.fetch(selected, start="2024-01-02", end="2024-01-02", on_issue="raise", receipts=True)
    restriction_values = {"variant": "1"} if restriction == "disjoint" else {"series_id": []}

    def check(value):
        if policy == "raise":
            with pytest.raises(IssuePolicyError) as raised:
                rr.pick(value, **restriction_values, on_issue=policy)
            assert any(item.code == "selection.no_match" for item in raised.value.issues)
            return None
        if policy == "warn":
            with pytest.warns(RuntimeWarning, match="No source series matches"):
                return rr.pick(value, **restriction_values, on_issue=policy)
        return rr.pick(value, **restriction_values, on_issue=policy)

    check(selected)
    check(rr.pick(selected, **restriction_values, on_issue="ignore"))
    check(rr.pick(result, **restriction_values, on_issue="ignore"))
    narrowed = check(result)
    if narrowed is not None:
        assert narrowed.data.is_empty()
        assert narrowed.scope == result.scope
        assert narrowed.outcomes == result.outcomes
        assert narrowed.provenance == result.provenance
        assert narrowed.receipts == result.receipts
        assert narrowed.issues[: len(result.issues)] == result.issues
        assert any(item.code == "selection.no_match" for item in narrowed.issues)
        check(narrowed)
    assert len(calls) == 1
